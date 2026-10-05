"""The live stream reads a task's events from ``task_events``."""

from __future__ import annotations

import json

import pytest

from appstore_api.models import Deployment, Task, TaskEvent, TaskStatus, TaskType
from tests.conftest import TEST_COURSE, TEST_PROJECT, TEST_SHA, create_app_in_db

pytestmark = pytest.mark.integration


def _deployment_with_events(db, owner, events, status=TaskStatus.SUCCESS) -> tuple[Deployment, list[int]]:
    app = create_app_in_db(db, owner)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name="d", appId=app.appId, userId=owner.userId)
    db.add(dep)
    db.flush()
    task = Task(deploymentId=dep.deploymentId, type=TaskType.DEPLOY, status=status)
    db.add(task)
    db.flush()
    rows = [TaskEvent(taskId=task.taskId, type=t, payload=json.dumps({"type": t, **p})) for t, p in events]
    db.add_all(rows)
    db.commit()
    return dep, [r.id for r in rows]


def _frames(body: str) -> list[dict]:
    frames = []
    for block in body.strip().split("\n\n"):
        frame: dict = {}
        for line in block.splitlines():
            if line.startswith(":"):
                continue
            key, _, value = line.partition(": ")
            frame[key] = value
        if frame:
            frames.append(frame)
    return frames


def test_stream_replays_the_task_and_ends_with_its_terminal_event(client, db, mock_user):
    dep, ids = _deployment_with_events(
        db,
        mock_user,
        [
            ("task-progress", {"phase": "git_clone", "progress_pct": 10}),
            ("task-log", {"message": "Cloning"}),
            ("task-succeeded", {"status": "success"}),
        ],
    )

    with client.stream("GET", f"/deployments/{dep.deploymentId}/stream") as response:
        body = response.read().decode()

    frames = _frames(body)
    assert [f["event"] for f in frames] == ["snapshot", "progress", "log", "succeeded"]
    assert [int(f["id"]) for f in frames[1:]] == ids
    assert json.loads(frames[2]["data"])["message"] == "Cloning"


def test_reconnect_resumes_after_last_event_id(client, db, mock_user):
    dep, ids = _deployment_with_events(
        db,
        mock_user,
        [("task-log", {"message": "one"}), ("task-log", {"message": "two"}), ("task-failed", {"status": "failed"})],
        status=TaskStatus.FAILED,
    )

    with client.stream(
        "GET", f"/deployments/{dep.deploymentId}/stream", headers={"Last-Event-ID": str(ids[0])}
    ) as response:
        frames = _frames(response.read().decode())

    assert [f["event"] for f in frames] == ["snapshot", "log", "failed"]
    assert json.loads(frames[1]["data"])["message"] == "two"


def test_finished_task_without_terminal_event_still_ends_the_stream(client, db, mock_user):
    dep, _ = _deployment_with_events(db, mock_user, [("task-log", {"message": "only"})], status=TaskStatus.FAILED)

    with client.stream("GET", f"/deployments/{dep.deploymentId}/stream") as response:
        frames = _frames(response.read().decode())

    assert [f["event"] for f in frames] == ["snapshot", "log"]


def test_deployment_without_tasks_sends_only_the_snapshot(client, db, mock_user):
    app = create_app_in_db(db, mock_user)
    dep = Deployment(commit_sha=TEST_SHA, course=TEST_COURSE, os_project_id=TEST_PROJECT, name="d", appId=app.appId, userId=mock_user.userId)
    db.add(dep)
    db.commit()

    with client.stream("GET", f"/deployments/{dep.deploymentId}/stream") as response:
        frames = _frames(response.read().decode())

    assert [f["event"] for f in frames] == ["snapshot"]
