"""Follow-up work for finished tasks, and failing tasks whose worker died.

Runs as a background loop in every API process. Both jobs claim rows with
``FOR UPDATE SKIP LOCKED``, so several replicas can run the loop at once
without doing anything twice. That is what makes the notification mails go
out once per deployment, not once per API worker as in the original project.

- **Reap**: a RUNNING task whose lease ran out belongs to a worker that
  stopped renewing it — crashed, killed, or cut off from the database. The
  task is failed, with a terminal event so open streams close. Nothing is
  retried: a half-applied OpenTofu run needs a person to look at it.
- **Finalize**: a finished task with ``finalized_at`` unset gets its
  follow-up work — the access mails after a deploy, the soft-delete and
  dropping the OpenTofu state after a destroy — and is then marked finalized in the same transaction.

``run_forever`` is started from the FastAPI lifespan in ``main.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from appstore_api.crud import deployments as crud_deployments
from appstore_api.database import SessionLocal
from appstore_api.models import Task, TaskEvent, TaskStatus, TaskType
from appstore_api.services import deployment_notifier, tf_state_store
from appstore_api.utils.crypto import cipher
from appstore_api.utils.time import utcnow
from appstore_shared.jobs import FAILURE_KIND_WORKER_LOST, open_outputs, terminal_event

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 5
# Rows per pass. A backlog is worked off over consecutive passes.
BATCH = 20

FINISHED = (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)

WORKER_LOST_MESSAGE = (
    "Der Worker, der diesen Auftrag ausgeführt hat, antwortet nicht mehr "
    "(abgestürzt oder neu gestartet). Der Auftrag wurde abgebrochen und wird "
    "nicht automatisch wiederholt. Bitte prüfen Sie den Zustand der "
    "Ressourcen und starten Sie die Aktion bei Bedarf erneut."
)


def reap_expired(db: Session) -> int:
    """Fail RUNNING tasks whose lease has run out. Returns how many.

    Handles at most ``BATCH`` tasks per call. Appends ``WORKER_LOST_MESSAGE``
    to the task log, writes the terminal event (so SSE log streams end) and
    commits.
    """
    tasks = db.scalars(
        select(Task)
        .where(Task.status == TaskStatus.RUNNING, Task.lease_until < utcnow())
        .with_for_update(skip_locked=True)
        .limit(BATCH)
    ).all()
    for task in tasks:
        logger.warning("task %s: lease of worker %s expired, failing it", task.taskId, task.claimed_by)
        task.status = TaskStatus.FAILED
        task.finished_at = utcnow()
        task.lease_until = None
        task.logs = f"{task.logs}\n\n{WORKER_LOST_MESSAGE}" if task.logs else WORKER_LOST_MESSAGE
        event_type, payload = terminal_event(task, FAILURE_KIND_WORKER_LOST)
        db.add(TaskEvent(taskId=task.taskId, type=event_type, payload=json.dumps(payload)))
    db.commit()
    return len(tasks)


def _outputs(task: Task) -> dict[str, Any] | None:
    """Decrypt the task's OpenTofu outputs (None if it has none)."""
    return open_outputs(cipher, task.outputs)


def _follow_up(db: Session, task: Task) -> None:
    """Do the follow-up work for one finished task; only successful DEPLOY/DESTROY tasks have any."""
    if task.status != TaskStatus.SUCCESS:
        return
    if task.type == TaskType.DEPLOY:
        # The notifier handles SMTP errors itself; a flaky relay must not
        # keep the task unfinalized and the mail retried forever.
        deployment_notifier.notify_deployment_succeeded(
            db, task.deploymentId, terraform_outputs=_outputs(task)
        )
    elif task.type == TaskType.DESTROY:
        # The OpenStack resources are gone; hide the deployment but keep
        # the row and its tasks for the record. The state has nothing left
        # to describe, and it held the resources' secrets (plan E3).
        tf_state_store.drop(db, task.deploymentId)
        crud_deployments.soft_delete_deployment(db, task.deploymentId)


def finalize_finished(db: Session) -> int:
    """Run the follow-up work of finished tasks. Returns how many.

    Handles at most ``BATCH`` tasks, oldest ``finished_at`` first. One task
    per transaction, marked finalized *before* its follow-up runs, so no
    other replica can pick it up in between. For a deploy the mark is
    committed before the mails go out: a crash in between loses the mails
    (the UI can resend them) rather than sending them twice. Other follow-ups
    (dropping state, soft-delete) are idempotent and commit with the mark,
    so a crash repeats them instead of skipping them.
    """
    done = 0
    for _ in range(BATCH):
        task = db.scalars(
            select(Task)
            .where(Task.status.in_(FINISHED), Task.finalized_at.is_(None))
            .order_by(Task.finished_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        ).first()
        if task is None:
            break
        task.finalized_at = utcnow()
        if task.type == TaskType.DEPLOY and task.status == TaskStatus.SUCCESS:
            db.commit()
        else:
            db.flush()
        try:
            _follow_up(db, task)
        except Exception:
            # Logged and left finalized: retrying would resend the mails
            # that did go out. The user can resend access from the UI.
            logger.exception("follow-up for task %s failed", task.taskId)
            task_id = task.taskId
            # The session may be unusable after a database error.
            db.rollback()
            db.execute(update(Task).where(Task.taskId == task_id).values(finalized_at=utcnow()))
        db.commit()
        done += 1
    return done


def run_once() -> None:
    """One pass: reap, then finalize, each in its own session."""
    with SessionLocal() as db:
        reap_expired(db)
    with SessionLocal() as db:
        finalize_finished(db)


async def run_forever() -> None:
    """Run ``run_once`` every ``INTERVAL_SECONDS`` until cancelled; a failed pass is logged, not fatal.

    Top-level coroutine started from the FastAPI lifespan.
    """
    logger.info("task finalizer running every %ss", INTERVAL_SECONDS)
    while True:
        try:
            # The database work is synchronous; keep it off the event loop.
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("task finalizer pass failed")
        await asyncio.sleep(INTERVAL_SECONDS)
