"""Generic database access for task rows (the job queue).

Enqueuing a job goes through ``services/task_service.py``, which also builds
the encrypted payload; the functions here are plain row reads and writes.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from appstore_api.models import Task, TaskStatus


def get_task(db: Session, task_id: UUID) -> Task | None:
    """Get task by ID."""
    return db.query(Task).filter(Task.taskId == task_id).first()


def get_tasks(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    deployment_id: UUID | None = None,
    status: TaskStatus | None = None
) -> list[Task]:
    """Get tasks, optionally of one deployment and/or with one status, newest first.

    Ordered so that the page ``skip``/``limit`` cuts is the most recent one.
    """
    query = db.query(Task)
    if deployment_id:
        query = query.filter(Task.deploymentId == deployment_id)
    if status:
        query = query.filter(Task.status == status)
    return query.order_by(Task.created_at.desc()).offset(skip).limit(limit).all()


def create_task(db: Session, task: dict[str, Any]) -> Task:
    """Insert a task from a dict of column values and commit."""
    db_task = Task(**task)
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def update_task(db: Session, task_id: UUID, task_update) -> Task | None:
    """Set the given fields (a dict or a ``TaskUpdate``, unset fields skipped) and commit."""
    db_task = get_task(db, task_id)
    if not db_task:
        return None

    # Handle both dict and Pydantic model
    if isinstance(task_update, dict):
        update_data = task_update
    else:
        update_data = task_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(db_task, field, value)
    db.commit()
    db.refresh(db_task)
    return db_task


def delete_task(db: Session, task_id: UUID) -> bool:
    """Delete a task and commit; False if it does not exist."""
    db_task = get_task(db, task_id)
    if not db_task:
        return False
    db.delete(db_task)
    db.commit()
    return True
