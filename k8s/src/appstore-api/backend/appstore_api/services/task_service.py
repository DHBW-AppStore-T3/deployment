"""Queue a task for the worker.

The ``tasks`` table is the job queue (plan D4). ``prepare_task_in_tx``
inserts a PENDING row carrying the sealed job payload in the caller's
transaction; committing it is all it takes to hand the job to a worker.
Deployment, teams and the task therefore become visible together or not at
all, and there is no second system that could have accepted a job the
database never saw.
"""
from __future__ import annotations

import logging
import secrets
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from appstore_api.crud import tasks as crud_tasks
from appstore_api.models import Task, TaskStatus, TaskType
from appstore_api.utils.crypto import cipher
from appstore_shared.jobs import JobPayload, seal_payload, state_token_hash

logger = logging.getLogger(__name__)


# Name of the Postgres partial unique index backing the "one active
# task per deployment" rule. String-matched when translating
# IntegrityError → ActiveTaskExistsError so other unique-constraint
# violations aren't swallowed.
_ACTIVE_TASK_UNIQUE_INDEX = "uq_tasks_active_per_deployment"


class ActiveTaskExistsError(Exception):
    """A PENDING/RUNNING task already exists for this deployment."""


def prepare_task_in_tx(
    db: Session,
    deployment_id: uuid.UUID,
    task_type: TaskType,
    payload: JobPayload,
) -> Task:
    """Insert a PENDING task row in the caller's transaction.

    ``payload`` is what the worker needs to run the job; it is stored
    encrypted and removed again when a worker claims the task. A fresh
    random ``state_token`` is added to it and only its hash is stored on
    the row: the worker uses the token to reach this deployment's OpenTofu
    state (see ``tf_state_store.authorize``).

    Does NOT call `db.commit()` — the caller is responsible for
    committing the surrounding state alongside this row, so that
    deployment + teams + task are all visible (or all rolled back)
    atomically.

    Raises `ActiveTaskExistsError` if the deployment already has a
    PENDING/RUNNING task. A Postgres partial unique index enforces this
    at the DB level too: the pre-check catches the common case, and the
    ``except IntegrityError`` around ``db.flush()`` catches the racy one
    (two concurrent requests both pass the pre-check). After that
    IntegrityError the session needs a rollback by the caller.
    """
    existing = crud_tasks.get_tasks(db, deployment_id=deployment_id)
    for task in existing:
        if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
            raise ActiveTaskExistsError(
                f"Deployment {deployment_id} already has active task {task.taskId}"
            )

    state_token = secrets.token_urlsafe(32)
    db_task = Task(
        deploymentId=deployment_id,
        type=task_type,
        status=TaskStatus.PENDING,
        payload=seal_payload(cipher, {**payload, "state_token": state_token}),
        state_token_hash=state_token_hash(state_token),
    )
    db.add(db_task)
    try:
        db.flush()
    except IntegrityError as e:
        # Race: another transaction inserted a PENDING/RUNNING task for
        # the same deployment between our pre-check and flush. Translate
        # the constraint violation into the domain exception so the
        # caller's 409 branch fires.
        if _ACTIVE_TASK_UNIQUE_INDEX in str(e.orig):
            raise ActiveTaskExistsError(
                f"Deployment {deployment_id} already has an active task "
                "(detected via DB unique constraint)"
            ) from e
        raise
    db.refresh(db_task)
    return db_task
