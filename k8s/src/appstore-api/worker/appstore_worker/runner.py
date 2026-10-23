"""The worker process: claim tasks, run their jobs, record the results.

``python -m appstore_worker`` starts ``WORKER_CONCURRENCY`` threads that each
poll the queue. On SIGTERM they stop claiming and let running jobs finish;
the deployment should give the pod enough time for that (an OpenTofu apply
can take many minutes). A pod killed mid-job leaves a task whose lease runs
out, and the API's reaper fails it.
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import threading
from collections.abc import Callable
from typing import Any

from appstore_shared.jobs import FAILURE_KIND_JOB, JobPayload
from appstore_shared.models import Task, TaskStatus, TaskType

from . import job_context, job_queue, k8s_runtime, simulate, tasks
from .config import settings
from .db import SessionLocal
from .services.terraform_executor import StateBackend

logger = logging.getLogger(__name__)

# Task type -> job function. Every job takes (events, **payload kwargs); see run_job.
JOBS: dict[TaskType, Callable[..., Any]] = {
    TaskType.DEPLOY: tasks.deploy_application,
    TaskType.DESTROY: tasks.destroy_deployment,
    TaskType.PAUSE: tasks.pause_deployment,
    TaskType.RESUME: tasks.resume_deployment,
    TaskType.REDEPLOY: tasks.redeploy_resource,
}


# Jobs for apps that run as pods (payload ``runtime: kubernetes``), same signatures.
K8S_JOBS: dict[TaskType, Callable[..., Any]] = {
    TaskType.DEPLOY: k8s_runtime.deploy_application,
    TaskType.DESTROY: k8s_runtime.destroy_deployment,
    TaskType.PAUSE: k8s_runtime.pause_deployment,
    TaskType.RESUME: k8s_runtime.resume_deployment,
    TaskType.REDEPLOY: k8s_runtime.redeploy_resource,
}


# Same signatures, used instead of JOBS when WORKER_SIMULATE is on (simulate.py).
SIMULATED_JOBS: dict[TaskType, Callable[..., Any]] = {
    TaskType.DEPLOY: simulate.deploy_application,
    TaskType.DESTROY: simulate.destroy_deployment,
    TaskType.PAUSE: simulate.pause_deployment,
    TaskType.RESUME: simulate.resume_deployment,
    TaskType.REDEPLOY: simulate.redeploy_resource,
}


def run_job(task: Task, payload: JobPayload, events: tasks.JobEvents) -> Any:
    """Call the job function for ``task`` with its decrypted payload.

    Maps the payload onto the job's keyword arguments and, when the API
    issued a state token, builds the OpenTofu HTTP state backend for it.
    Raises ValueError for a task type without a job; whatever the job
    raises (usually ``tasks.Failure``) propagates to ``process_next``.
    """
    is_k8s = payload.get("runtime") == "kubernetes"
    table = SIMULATED_JOBS if settings.WORKER_SIMULATE else K8S_JOBS if is_k8s else JOBS
    job = table.get(task.type)
    if job is None:
        raise ValueError(f"no job for task type {task.type.value}")
    kwargs: dict[str, Any] = {
        "deployment_id": str(task.deploymentId),
        "app_id": payload["app_id"],
        "app_git_link": payload["app_git_link"],
        "release": payload["release"],
        "commit_sha": payload["commit_sha"],
        "user_vars": payload["user_vars"],
        "teams": payload["teams"],
        "openstack_envelope": payload["openstack_envelope"],
    }
    if is_k8s and not settings.WORKER_SIMULATE:
        kwargs.update(spec=payload.get("spec"), course=payload.get("course", ""), owner=payload.get("owner", ""))
    if task.type == TaskType.REDEPLOY:
        kwargs["resource_address"] = payload.get("resource_address")
    token = payload.get("state_token")
    if token:
        kwargs["state_backend"] = StateBackend.for_job(
            str(task.deploymentId), str(task.taskId), token
        )
    return job(events, **kwargs)


def process_next(worker_id: str, session_factory=SessionLocal, slot: int = 0) -> bool:
    """Run one task if there is one. Returns whether there was one.

    Claims the task, runs its job under a renewed lease and inside the
    slot's ``job_context``, then records success or failure on the row.
    ``slot`` is the worker thread's number; it picks the user the job's
    tools run as (see ``job_context``).
    """
    with session_factory() as session:
        claimed = job_queue.claim_next(session, worker_id, settings.WORKER_LEASE_SECONDS)
    if claimed is None:
        return False
    task, payload = claimed
    logger.info("running %s task %s for deployment %s", task.type.value, task.taskId, task.deploymentId)

    events = job_queue.TaskEventSink(session_factory, task.taskId)
    kind: str | None = None
    with job_queue.Lease(session_factory, task.taskId, worker_id, settings.WORKER_LEASE_SECONDS):
        try:
            with job_context.bind(job_context.for_slot(slot)):
                result = run_job(task, payload, events)
        except Exception as e:
            logger.info("task %s failed: %s", task.taskId, e)
            status, columns, kind = TaskStatus.FAILED, job_queue.failure_columns(e), FAILURE_KIND_JOB
        else:
            status, columns = TaskStatus.SUCCESS, job_queue.success_columns(result)
    job_queue.record_result(session_factory, task.taskId, worker_id, status, columns, kind)
    logger.info("task %s finished: %s", task.taskId, status.value)
    return True


def _poll_loop(worker_id: str, slot: int, stop: threading.Event) -> None:
    """Body of one worker thread: process tasks until ``stop`` is set, sleeping when idle."""
    while not stop.is_set():
        try:
            if process_next(worker_id, slot=slot):
                continue
        except Exception:
            # Most likely the database is unreachable. Back off and retry;
            # the process stays up so it recovers on its own.
            logger.exception("worker loop error")
        stop.wait(settings.WORKER_POLL_INTERVAL_SECONDS)


def main() -> None:
    """Start the worker threads, install the SIGTERM/SIGINT handlers and wait for shutdown."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    stop = threading.Event()

    def _shutdown(signum: int, _frame: Any) -> None:
        logger.info("signal %s: finishing running jobs, claiming no new ones", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    threads = [
        threading.Thread(target=_poll_loop, args=(f"{worker_id}-{i}", i, stop), name=f"worker-{i}")
        for i in range(settings.WORKER_CONCURRENCY)
    ]
    if settings.WORKER_JOB_UID_BASE is not None:
        # The image creates these 0711 (a slot's user may enter its own
        # directory but not list the others); a volume mounted over them
        # (emptyDir in the chart) comes up 0777, so set it again.
        for base in (settings.TEMP_REPO_BASE_PATH, settings.WORKER_JOB_HOME_BASE):
            os.makedirs(base, exist_ok=True)
            os.chmod(base, 0o711)
    if settings.WORKER_SIMULATE:
        logger.warning("WORKER_SIMULATE is on: jobs are played through, nothing is created in OpenStack")
    logger.info("worker %s polling with %d threads", worker_id, len(threads))
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    logger.info("worker %s stopped", worker_id)
