"""Claim tasks from the queue, report on them while they run, record the result.

The queue is the ``tasks`` table (plan D4). A task is claimed with
``SELECT … FOR UPDATE SKIP LOCKED``, so any number of worker processes can
poll the same table without handing one task to two of them. While the job
runs, a lease on the row is renewed; if the worker dies the lease runs out
and the API's reaper fails the task. Nothing is retried automatically: a
half-applied OpenTofu run is not something to repeat blindly.
"""

from __future__ import annotations

import json
import logging
import threading
import traceback
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from appstore_shared.crypto import InvalidToken
from appstore_shared.jobs import (
    EVENT_PROGRESS,
    FAILURE_KIND_JOB,
    JobPayload,
    open_payload,
    seal_outputs,
    terminal_event,
)
from appstore_shared.models import Task, TaskEvent, TaskStatus, utcnow

from .utils.crypto import cipher

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Claiming
# ----------------------------------------------------------------
def claim_next(session: Session, worker_id: str, lease_seconds: int) -> tuple[Task, JobPayload] | None:
    """Take the oldest pending task, or return None when there is none.

    The payload is decrypted and removed from the row in the same
    transaction: from here on it exists only in this worker's memory.
    """
    task = session.execute(
        select(Task)
        .where(Task.status == TaskStatus.PENDING)
        .order_by(Task.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if task is None:
        session.rollback()
        return None

    sealed, task.payload = task.payload, None
    try:
        if sealed is None:
            raise ValueError("the task has no job payload")
        payload = open_payload(cipher, sealed)
    except (InvalidToken, ValueError) as e:
        # Unrunnable as queued (e.g. the API and worker disagree on the key).
        # Failing it here beats leaving it pending for the next worker to
        # trip over.
        logger.error("cannot run task %s: %s", task.taskId, e)
        _finish(session, task, TaskStatus.FAILED, {"logs": f"Task failed: {e}"}, FAILURE_KIND_JOB)
        session.commit()
        return None

    now = utcnow()
    task.status = TaskStatus.RUNNING
    task.started_at = now
    task.claimed_by = worker_id
    task.lease_until = now + timedelta(seconds=lease_seconds)
    session.commit()
    return task, payload


# ----------------------------------------------------------------
# While a job runs
# ----------------------------------------------------------------
class TaskEventSink:
    """Appends a running job's events to ``task_events``.

    Handed to the job as its first argument (``send_event`` is what the job
    bodies call). Each event is committed on its own so the live stream sees
    it right away. A failed write is logged and dropped: losing a log line
    must not fail an OpenTofu run that is otherwise fine.
    """

    def __init__(self, session_factory, task_id: uuid.UUID) -> None:
        self._session_factory = session_factory
        self._task_id = task_id
        # Tool output arrives from reader threads; one writer at a time.
        self._lock = threading.Lock()

    def is_cancelled(self) -> bool:
        """Whether the API cancelled this task while it runs (pod deployments)."""
        session = self._session_factory()
        try:
            status = session.execute(select(Task.status).where(Task.taskId == self._task_id)).scalar_one_or_none()
            return status == TaskStatus.CANCELLED
        except Exception:
            logger.warning("could not read the status of task %s", self._task_id, exc_info=True)
            return False
        finally:
            session.close()

    def send_event(self, event_type: str, **payload: Any) -> None:
        """Append one event row; progress events also update the task's phase and percent."""
        body = {"type": event_type, **payload}
        with self._lock:
            session = self._session_factory()
            try:
                session.add(TaskEvent(taskId=self._task_id, type=event_type, payload=json.dumps(body, default=str)))
                if event_type == EVENT_PROGRESS:
                    # Also on the row, so a page reload shows where the task is.
                    changes: dict[str, Any] = {}
                    if body.get("phase") is not None:
                        changes["current_phase"] = str(body["phase"])[:50]
                    if body.get("progress_pct") is not None:
                        changes["progress_pct"] = max(0, min(100, int(body["progress_pct"])))
                    if changes:
                        session.execute(update(Task).where(Task.taskId == self._task_id).values(**changes))
                session.commit()
            except Exception:
                session.rollback()
                logger.warning("could not record %s event for task %s", event_type, self._task_id, exc_info=True)
            finally:
                session.close()


class Lease:
    """Renews this worker's claim on a task while its job runs.

    Renewing only succeeds while the row still says it is ours and running.
    If the reaper got there first (the renewals stalled for a whole lease),
    ``lost`` is set; the job is not interrupted — its result is still worth
    recording — but the task's status is no longer this worker's to set.
    """

    def __init__(self, session_factory, task_id: uuid.UUID, worker_id: str, lease_seconds: int) -> None:
        self._session_factory = session_factory
        self._task_id = task_id
        self._worker_id = worker_id
        self._lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"lease-{task_id}", daemon=True)
        self.lost = False

    def __enter__(self) -> Lease:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        self._thread.join()

    def renew(self) -> bool:
        """Extend the lease by ``lease_seconds``; False if the row is no longer ours and running."""
        session = self._session_factory()
        try:
            result = session.execute(
                update(Task)
                .where(
                    Task.taskId == self._task_id,
                    Task.claimed_by == self._worker_id,
                    Task.status == TaskStatus.RUNNING,
                )
                .values(lease_until=utcnow() + timedelta(seconds=self._lease_seconds))
            )
            session.commit()
            return bool(getattr(result, "rowcount", 0))
        finally:
            session.close()

    def _run(self) -> None:
        """Lease thread: renew every third of the lease until stopped or the lease is lost."""
        while not self._stop.wait(self._lease_seconds / 3):
            try:
                if not self.renew():
                    self.lost = True
                    logger.error("lost the lease on task %s", self._task_id)
                    return
            except Exception:
                # A database blip; the next tick tries again, and the lease
                # has two more intervals before it runs out.
                logger.warning("could not renew the lease on task %s", self._task_id, exc_info=True)


# ----------------------------------------------------------------
# Recording the result
# ----------------------------------------------------------------
def _as_text(value: Any, *, indent: int | None = None) -> str | None:
    """Render a log value for a text column: strings as-is, anything else as JSON, empty as None."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=indent, ensure_ascii=False, default=str)


def success_columns(result: Any) -> dict[str, Any]:
    """Task columns for a job function's return value."""
    result = result if isinstance(result, dict) else {}
    return {
        "logs": _as_text(result.get("logs")),
        "outputs": seal_outputs(cipher, result.get("terraform_outputs")),
    }


def failure_columns(error: BaseException) -> dict[str, Any]:
    """Task columns for a job that raised.

    A ``Failure`` carries what the job produced before it failed — the log
    and the outputs of a half-finished apply — and all of it is kept.
    Anything else is a bug in the worker; the traceback goes into the log.
    """
    from .tasks import Failure  # the jobs module imports this one

    if not isinstance(error, Failure):
        details = "".join(traceback.format_exception(error)).strip()
        return {"logs": f"Task failed: {details}"}

    logs = _as_text(error.logs_dict) or ""
    logs += f"\n\n[err] Error: {error.message}"
    commit = error.commit_info
    if isinstance(commit, dict):
        logs += f"\nCommit: {str(commit.get('hash', 'N/A'))[:8]}"
        logs += f"\n   Message: {commit.get('message', 'N/A')}"
        logs += f"\n   Author: {commit.get('author', 'N/A')}"
    return {
        "logs": logs,
        "outputs": seal_outputs(cipher, error.terraform_outputs),
    }


def _finish(
    session: Session,
    task: Task,
    status: TaskStatus,
    columns: dict[str, Any],
    failure_kind: str | None = None,
) -> None:
    """Set the terminal status and result columns and append the terminal event.

    Does not commit; the caller owns the transaction.
    """
    for name, value in columns.items():
        setattr(task, name, value)
    task.status = status
    task.finished_at = utcnow()
    task.lease_until = None
    event_type, payload = terminal_event(task, failure_kind)
    session.add(TaskEvent(taskId=task.taskId, type=event_type, payload=json.dumps(payload)))


def record_result(
    session_factory,
    task_id: uuid.UUID,
    worker_id: str,
    status: TaskStatus,
    columns: dict[str, Any],
    failure_kind: str | None = None,
) -> None:
    """Store a finished job's result and end the task's event stream.

    Results are always stored — the outputs describe what exists in
    OpenStack whatever the bookkeeping says. The status is only set while
    the task is still ours; if the reaper already failed it, it stays failed.
    """
    session = session_factory()
    try:
        task = session.execute(select(Task).where(Task.taskId == task_id).with_for_update()).scalar_one()
        if task.status == TaskStatus.RUNNING and task.claimed_by == worker_id:
            _finish(session, task, status, columns, failure_kind)
        else:
            logger.warning(
                "task %s finished after its lease was taken over; keeping its status %s",
                task_id,
                task.status.value,
            )
            for name, value in columns.items():
                if value is not None:
                    setattr(task, name, value)
        session.commit()
    finally:
        session.close()
