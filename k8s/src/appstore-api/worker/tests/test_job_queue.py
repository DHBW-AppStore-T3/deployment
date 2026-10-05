"""The Postgres job queue: claiming, events, leases, results."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from appstore_shared.jobs import EVENT_FAILED, EVENT_SUCCEEDED, open_outputs
from appstore_shared.models import Task, TaskEvent, TaskStatus
from appstore_worker import job_queue as queue
from appstore_worker.tasks import Failure
from appstore_worker.utils.crypto import cipher

pytestmark = pytest.mark.integration


def _task(session_factory, task_id) -> Task:
    with session_factory() as s:
        return s.get(Task, task_id)


def _events(session_factory, task_id) -> list[TaskEvent]:
    with session_factory() as s:
        return list(s.scalars(select(TaskEvent).where(TaskEvent.taskId == task_id).order_by(TaskEvent.id)))


# ----------------------------------------------------------------
# claim_next
# ----------------------------------------------------------------
def test_empty_queue(session_factory):
    with session_factory() as s:
        assert queue.claim_next(s, "w1", 60) is None


def test_claim_takes_the_task_and_removes_the_payload(session_factory, make_task):
    task_id = make_task()

    with session_factory() as s:
        task, payload = queue.claim_next(s, "w1", 60)

    assert task.taskId == task_id
    assert payload["release"] == "v1"
    assert payload["openstack_envelope"] == {"project_id": "p1"}
    row = _task(session_factory, task_id)
    assert row.status == TaskStatus.RUNNING
    assert row.claimed_by == "w1"
    assert row.lease_until is not None and row.started_at is not None
    # Credentials and variables left the database with the claim.
    assert row.payload is None


def test_oldest_task_first(session_factory, make_task):
    first = make_task()
    make_task()
    with session_factory() as s:
        task, _ = queue.claim_next(s, "w1", 60)
    assert task.taskId == first


def test_a_task_being_claimed_is_skipped_by_other_workers(session_factory, make_task):
    locked = make_task()
    other = make_task()
    holder = session_factory()
    try:
        # Worker A is in the middle of claiming ``locked``.
        holder.execute(select(Task).where(Task.taskId == locked).with_for_update())
        with session_factory() as s:
            task, _ = queue.claim_next(s, "w2", 60)
        assert task.taskId == other
    finally:
        holder.rollback()
        holder.close()


def test_running_tasks_are_not_claimed_again(session_factory, make_task):
    make_task(status=TaskStatus.RUNNING)
    with session_factory() as s:
        assert queue.claim_next(s, "w1", 60) is None


def test_undecryptable_payload_fails_the_task(session_factory, make_task):
    task_id = make_task(sealed=b"not a fernet token")

    with session_factory() as s:
        assert queue.claim_next(s, "w1", 60) is None

    row = _task(session_factory, task_id)
    assert row.status == TaskStatus.FAILED
    assert row.payload is None
    assert [e.type for e in _events(session_factory, task_id)] == [EVENT_FAILED]


# ----------------------------------------------------------------
# events and lease
# ----------------------------------------------------------------
def test_event_sink_appends_and_tracks_progress(session_factory, make_task):
    task_id = make_task(status=TaskStatus.RUNNING)
    sink = queue.TaskEventSink(session_factory, task_id)

    sink.send_event("task-log", deployment_id="d", line="terraform init")
    sink.send_event("task-progress", deployment_id="d", phase="terraform_apply", progress_pct=140)

    events = _events(session_factory, task_id)
    assert [e.type for e in events] == ["task-log", "task-progress"]
    assert json.loads(events[0].payload) == {"type": "task-log", "deployment_id": "d", "line": "terraform init"}
    row = _task(session_factory, task_id)
    assert (row.current_phase, row.progress_pct) == ("terraform_apply", 100)


def test_lease_renews_only_while_the_task_is_ours(session_factory, make_task):
    task_id = make_task()
    with session_factory() as s:
        queue.claim_next(s, "w1", 60)

    assert queue.Lease(session_factory, task_id, "w1", 60).renew() is True
    assert queue.Lease(session_factory, task_id, "someone-else", 60).renew() is False

    with session_factory() as s:
        s.get(Task, task_id).status = TaskStatus.FAILED  # the reaper took it
        s.commit()
    assert queue.Lease(session_factory, task_id, "w1", 60).renew() is False


# ----------------------------------------------------------------
# results
# ----------------------------------------------------------------
def test_success_is_recorded_with_a_terminal_event(session_factory, make_task):
    task_id = make_task()
    with session_factory() as s:
        queue.claim_next(s, "w1", 60)

    columns = queue.success_columns({"logs": [{"m": "ok"}], "terraform_outputs": {"ip": "1.2.3.4"}})
    queue.record_result(session_factory, task_id, "w1", TaskStatus.SUCCESS, columns)

    row = _task(session_factory, task_id)
    assert row.status == TaskStatus.SUCCESS
    assert row.finished_at is not None and row.lease_until is None
    # Encrypted at rest: they carry the generated credentials.
    assert b"1.2.3.4" not in row.outputs
    assert open_outputs(cipher, row.outputs) == {"ip": "1.2.3.4"}
    terminal = _events(session_factory, task_id)[-1]
    assert terminal.type == EVENT_SUCCEEDED
    assert json.loads(terminal.payload)["status"] == "success"


def test_result_of_a_reaped_task_is_kept_but_its_status_is_not_changed(session_factory, make_task):
    task_id = make_task()
    with session_factory() as s:
        queue.claim_next(s, "w1", 60)
        s.get(Task, task_id).status = TaskStatus.FAILED  # reaper
        s.commit()

    columns = queue.success_columns({"terraform_outputs": {"ip": "1.2.3.4"}})
    queue.record_result(session_factory, task_id, "w1", TaskStatus.SUCCESS, columns)

    row = _task(session_factory, task_id)
    assert row.status == TaskStatus.FAILED
    # What exists in OpenStack is still worth knowing.
    assert open_outputs(cipher, row.outputs) == {"ip": "1.2.3.4"}


def test_failure_columns_keep_partial_results():
    error = Failure(
        "Terraform apply failed",
        "dep-1",
        logs_dict=[{"m": "apply"}],
        commit_info={"hash": "0123456789", "message": "fix", "author": "a"},
        terraform_outputs={"ip": "1.2.3.4"},
    )

    columns = queue.failure_columns(error)

    assert "[err] Error: Terraform apply failed" in columns["logs"]
    assert "Commit: 01234567" in columns["logs"]
    assert open_outputs(cipher, columns["outputs"]) == {"ip": "1.2.3.4"}


def test_failure_columns_for_a_bug_carry_the_traceback():
    try:
        raise KeyError("missing")
    except KeyError as e:
        columns = queue.failure_columns(e)
    assert columns["logs"].startswith("Task failed: Traceback")
    assert "KeyError: 'missing'" in columns["logs"]
