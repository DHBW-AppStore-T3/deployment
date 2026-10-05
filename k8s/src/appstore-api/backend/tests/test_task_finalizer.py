"""Reaping tasks of dead workers and the once-only follow-up of finished tasks."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

import pytest

from appstore_api.models import Deployment, Task, TaskEvent, TaskStatus, TaskType, TerraformState
from appstore_api.services import task_finalizer
from appstore_api.utils.crypto import cipher
from appstore_api.utils.time import utcnow
from appstore_shared.jobs import seal_outputs
from tests.conftest import TEST_COURSE, TEST_PROJECT, TEST_SHA, create_app_in_db

pytestmark = pytest.mark.integration


def _deployment(db, owner) -> Deployment:
    app = create_app_in_db(db, owner)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name="d", appId=app.appId, userId=owner.userId)
    db.add(dep)
    db.commit()
    return dep


def _task(db, dep, **fields) -> Task:
    task = Task(deploymentId=dep.deploymentId, type=fields.pop("type", TaskType.DEPLOY), **fields)
    db.add(task)
    db.commit()
    return task


# ----------------------------------------------------------------
# reap
# ----------------------------------------------------------------
def test_expired_lease_fails_the_task_and_ends_its_stream(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.RUNNING, claimed_by="w1", lease_until=utcnow() - timedelta(seconds=1))

    assert task_finalizer.reap_expired(db) == 1

    db.refresh(task)
    assert task.status == TaskStatus.FAILED
    assert task.finished_at is not None
    assert "antwortet nicht mehr" in task.logs
    [event] = db.query(TaskEvent).filter(TaskEvent.taskId == task.taskId).all()
    assert event.type == "task-failed"
    assert json.loads(event.payload)["failure_kind"] == "worker_lost"


def test_live_lease_is_left_alone(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.RUNNING, claimed_by="w1", lease_until=utcnow() + timedelta(minutes=1))

    assert task_finalizer.reap_expired(db) == 0
    db.refresh(task)
    assert task.status == TaskStatus.RUNNING


# ----------------------------------------------------------------
# finalize
# ----------------------------------------------------------------
def test_successful_deploy_sends_the_mails_once(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.SUCCESS, finished_at=utcnow(), outputs=seal_outputs(cipher, {"team_vms": {}}))

    with patch.object(task_finalizer.deployment_notifier, "notify_deployment_succeeded") as notify:
        assert task_finalizer.finalize_finished(db) == 1
        assert task_finalizer.finalize_finished(db) == 0

    notify.assert_called_once()
    assert notify.call_args.kwargs["terraform_outputs"] == {"team_vms": {}}
    db.refresh(task)
    assert task.finalized_at is not None


def test_successful_destroy_soft_deletes_the_deployment_and_drops_its_state(db, mock_user):
    dep = _deployment(db, mock_user)
    db.add(TerraformState(deploymentId=dep.deploymentId, state=b"sealed"))
    _task(db, dep, type=TaskType.DESTROY, status=TaskStatus.SUCCESS, finished_at=utcnow())

    task_finalizer.finalize_finished(db)

    db.refresh(dep)
    assert dep.deleted_at is not None
    assert db.get(TerraformState, dep.deploymentId) is None


def test_failed_tasks_are_finalized_without_follow_up(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.FAILED, finished_at=utcnow())

    with patch.object(task_finalizer.deployment_notifier, "notify_deployment_succeeded") as notify:
        task_finalizer.finalize_finished(db)

    notify.assert_not_called()
    db.refresh(task)
    assert task.finalized_at is not None


def test_running_tasks_are_not_finalized(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.RUNNING)

    assert task_finalizer.finalize_finished(db) == 0
    db.refresh(task)
    assert task.finalized_at is None


def test_a_failing_follow_up_is_not_retried(db, mock_user):
    dep = _deployment(db, mock_user)
    task = _task(db, dep, status=TaskStatus.SUCCESS, finished_at=utcnow())

    with patch.object(
        task_finalizer.deployment_notifier, "notify_deployment_succeeded", side_effect=RuntimeError("smtp")
    ) as notify:
        task_finalizer.finalize_finished(db)
        task_finalizer.finalize_finished(db)

    notify.assert_called_once()
    db.refresh(task)
    assert task.finalized_at is not None
