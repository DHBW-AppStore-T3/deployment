"""OpenTofu's HTTP state backend in the API (plan E3)."""

from __future__ import annotations

import json
import uuid

import pytest

from appstore_api.models import Deployment, Task, TaskStatus, TaskType, TerraformState
from appstore_api.services import task_service
from appstore_shared.jobs import state_token_hash
from tests.conftest import TEST_COURSE, TEST_PROJECT, TEST_SHA, create_app_in_db, queued_task

pytestmark = pytest.mark.integration

_STATE = json.dumps({"version": 4, "serial": 1, "resources": [{"type": "random_password", "name": "pw"}]})


def _running_task(db, owner, token="tok-1") -> Task:
    app = create_app_in_db(db, owner)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name="d", appId=app.appId, userId=owner.userId)
    db.add(dep)
    db.flush()
    task = Task(
        deploymentId=dep.deploymentId,
        type=TaskType.DEPLOY,
        status=TaskStatus.RUNNING,
        state_token_hash=state_token_hash(token),
    )
    db.add(task)
    db.commit()
    return task


def _url(task: Task) -> str:
    return f"/internal/tfstate/{task.deploymentId}"


def _auth(task: Task, token="tok-1") -> tuple[str, str]:
    return (str(task.taskId), token)


def _lock_body(lock_id: str) -> str:
    return json.dumps({"ID": lock_id, "Operation": "OperationTypeApply", "Who": "w@x"})


def test_state_round_trip_is_encrypted_at_rest(unauth_client, db, mock_user):
    task = _running_task(db, mock_user)

    assert unauth_client.get(_url(task), auth=_auth(task)).status_code == 204
    assert unauth_client.post(_url(task), content=_STATE, auth=_auth(task)).status_code == 200

    response = unauth_client.get(_url(task), auth=_auth(task))
    assert response.status_code == 200
    assert response.text == _STATE
    db.expire_all()
    stored = db.get(TerraformState, task.deploymentId).state
    assert b"random_password" not in stored


@pytest.mark.parametrize(
    "tamper",
    ["no_auth", "wrong_token", "finished_task", "other_deployment", "not_a_uuid"],
)
def test_the_token_opens_only_its_own_running_task(unauth_client, db, mock_user, tamper):
    task = _running_task(db, mock_user)
    url, auth = _url(task), _auth(task)
    if tamper == "no_auth":
        auth = None
    elif tamper == "wrong_token":
        auth = (str(task.taskId), "guess")
    elif tamper == "finished_task":
        task.status = TaskStatus.SUCCESS
        db.commit()
    elif tamper == "other_deployment":
        other = _running_task(db, mock_user, token="tok-2")
        url = _url(other)
    elif tamper == "not_a_uuid":
        auth = ("x", "tok-1")

    response = unauth_client.get(url, auth=auth)

    assert response.status_code == 401


def test_a_held_lock_blocks_other_lockers_and_writers(unauth_client, db, mock_user):
    task = _running_task(db, mock_user)
    auth = _auth(task)

    assert unauth_client.request("LOCK", _url(task), content=_lock_body("a"), auth=auth).status_code == 200

    competing = unauth_client.request("LOCK", _url(task), content=_lock_body("b"), auth=auth)
    assert competing.status_code == 423
    assert competing.json()["ID"] == "a"
    assert unauth_client.post(f"{_url(task)}?ID=b", content=_STATE, auth=auth).status_code == 423
    assert unauth_client.post(f"{_url(task)}?ID=a", content=_STATE, auth=auth).status_code == 200
    assert unauth_client.request("UNLOCK", _url(task), content=_lock_body("b"), auth=auth).status_code == 409

    assert unauth_client.request("UNLOCK", _url(task), content=_lock_body("a"), auth=auth).status_code == 200
    assert unauth_client.request("LOCK", _url(task), content=_lock_body("b"), auth=auth).status_code == 200


def test_the_lock_of_a_task_that_ended_is_taken_over(unauth_client, db, mock_user):
    first = _running_task(db, mock_user)
    assert (
        unauth_client.request("LOCK", _url(first), content=_lock_body("a"), auth=_auth(first)).status_code == 200
    )
    # The worker died mid-apply; the reaper failed the task. The next task of
    # the deployment must not be blocked by the lock it left behind.
    first.status = TaskStatus.FAILED
    second = Task(
        deploymentId=first.deploymentId,
        type=TaskType.DESTROY,
        status=TaskStatus.RUNNING,
        state_token_hash=state_token_hash("tok-2"),
    )
    db.add(second)
    db.commit()

    response = unauth_client.request("LOCK", _url(second), content=_lock_body("b"), auth=(str(second.taskId), "tok-2"))

    assert response.status_code == 200


def test_state_endpoints_are_not_in_the_public_api(unauth_client):
    paths = unauth_client.get("/swagger.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/internal")]


def test_queued_task_carries_the_token_and_the_row_only_its_hash(db, mock_user):
    app = create_app_in_db(db, mock_user)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name="d", appId=app.appId, userId=mock_user.userId)
    db.add(dep)
    db.flush()
    payload = {
        "app_id": str(uuid.uuid4()),
        "app_git_link": "https://github.com/example/app",
        "release": "v1",
        "user_vars": {},
        "teams": {},
        "openstack_envelope": {},
    }
    task_service.prepare_task_in_tx(db, dep.deploymentId, TaskType.DEPLOY, payload)
    db.commit()

    task, sealed = queued_task(db, dep.deploymentId)

    assert sealed["state_token"]
    assert task.state_token_hash == state_token_hash(sealed["state_token"])
