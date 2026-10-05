"""Read-only access to the jobs (tasks) of a deployment, mounted under ``/tasks``.

Tasks are rows in the Postgres job queue, created by the deployment routes and
executed by the worker; this router exposes their status and logs so the
frontend can render progress.

Every endpoint requires the owner view of the task's deployment (see
``utils/capabilities``): task logs show IPs and worker errors, which team
members must not see.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.auth import get_current_user
from appstore_api.crud import deployments as crud_deployments
from appstore_api.crud import tasks as crud_tasks
from appstore_api.database import get_db
from appstore_api.models import User
from appstore_api.schemas import TaskResponse
from appstore_api.utils.capabilities import ensure_view_deployment_owner

router = APIRouter()


@router.get("/deployment/{deployment_id}", response_model=list[TaskResponse])
def list_deployment_tasks(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all tasks (jobs) of a deployment with their status and logs.

    Requires the owner view of the deployment (owner, project peers,
    admins); team members get 403. 404 if the deployment does not exist.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    ensure_view_deployment_owner(current_user, deployment, db)
    return crud_tasks.get_tasks(db, deployment_id=deployment_id)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single task (job) with its status and log.

    Requires the owner view of the task's deployment (403 otherwise). 404
    if the task or its deployment does not exist.
    """
    task = crud_tasks.get_task(db, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    deployment = crud_deployments.get_deployment(db, task.deploymentId)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment for task not found",
        )
    ensure_view_deployment_owner(current_user, deployment, db)
    return task
