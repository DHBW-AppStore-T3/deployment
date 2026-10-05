"""The runner end to end: claim a queued task, run its job, record the result."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from appstore_shared.jobs import open_outputs
from appstore_shared.models import Task, TaskEvent, TaskStatus, TaskType
from appstore_worker import runner
from appstore_worker.tasks import Failure
from appstore_worker.utils.crypto import cipher

pytestmark = pytest.mark.integration


def _row(session_factory, task_id) -> Task:
    with session_factory() as s:
        return s.get(Task, task_id)


def test_nothing_to_do(session_factory):
    assert runner.process_next("w1", session_factory) is False


def test_job_gets_its_payload_and_events_reach_the_table(session_factory, make_task, monkeypatch):
    task_id = make_task(TaskType.DEPLOY)
    seen = {}

    def fake_deploy(job, **kwargs):
        seen.update(kwargs)
        job.send_event("task-log", deployment_id=kwargs["deployment_id"], line="hello")
        return {"status": "success", "logs": [], "terraform_outputs": {"ip": "1.2.3.4"}}

    monkeypatch.setitem(runner.JOBS, TaskType.DEPLOY, fake_deploy)

    assert runner.process_next("w1", session_factory) is True

    assert seen["release"] == "v1"
    assert seen["teams"] == {"T1": [{"email": "s@dhbw.de"}]}
    row = _row(session_factory, task_id)
    assert row.status == TaskStatus.SUCCESS
    assert open_outputs(cipher, row.outputs) == {"ip": "1.2.3.4"}
    with session_factory() as s:
        types = [e.type for e in s.scalars(select(TaskEvent).where(TaskEvent.taskId == task_id).order_by(TaskEvent.id))]
    assert types == ["task-log", "task-succeeded"]


def test_redeploy_gets_its_resource_address(session_factory, make_task, monkeypatch):
    make_task(
        TaskType.REDEPLOY,
        payload={
            "app_id": "a",
            "app_git_link": "https://example.org/a/b",
            "release": "v1",
            "commit_sha": "c" * 40,
            "user_vars": {},
            "teams": {},
            "openstack_envelope": {},
            "resource_address": 'openstack_compute_instance_v2.vm["T1"]',
        },
    )
    seen = {}
    monkeypatch.setitem(runner.JOBS, TaskType.REDEPLOY, lambda _job, **kw: seen.update(kw) or {})

    runner.process_next("w1", session_factory)

    assert seen["resource_address"] == 'openstack_compute_instance_v2.vm["T1"]'


def test_failing_job_is_recorded_as_failed(session_factory, make_task, monkeypatch):
    task_id = make_task(TaskType.DESTROY)

    def fake_destroy(job, **kwargs):
        raise Failure(
            "Terraform destroy failed", kwargs["deployment_id"], logs_dict=[], terraform_outputs={"ip": "1.2.3.4"}
        )

    monkeypatch.setitem(runner.JOBS, TaskType.DESTROY, fake_destroy)

    runner.process_next("w1", session_factory)

    row = _row(session_factory, task_id)
    assert row.status == TaskStatus.FAILED
    assert "Terraform destroy failed" in row.logs
    assert open_outputs(cipher, row.outputs) == {"ip": "1.2.3.4"}


def test_task_type_without_a_job_fails_instead_of_crashing(session_factory, make_task):
    task_id = make_task(TaskType.UPDATE)

    runner.process_next("w1", session_factory)

    row = _row(session_factory, task_id)
    assert row.status == TaskStatus.FAILED
    assert "no job for task type update" in row.logs
