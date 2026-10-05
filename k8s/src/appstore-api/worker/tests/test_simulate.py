"""The simulated jobs (WORKER_SIMULATE, plan AP7)."""

from __future__ import annotations

import json

import pytest

from appstore_shared.models import TaskType
from appstore_worker import runner, simulate
from appstore_worker.config import settings
from appstore_worker.services.terraform_executor import StateBackend
from appstore_worker.tasks import Failure


class Events:
    def __init__(self):
        self.events = []

    def send_event(self, event_type, **payload):
        self.events.append((event_type, payload))


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_SIMULATE_STEP_SECONDS", 0)


@pytest.fixture
def state_posts(monkeypatch):
    posted = []

    def post(backend, body):
        posted.append((backend.address, json.loads(body), (backend.username, backend.password)))

    monkeypatch.setattr(simulate, "_post", post)
    return posted


TEAMS = {"Team-1": [{"email": "anna.b@dhbw.de"}, {"email": "ben@dhbw.de"}], "Team-2": [{"email": "cem@dhbw.de"}]}


def test_a_simulated_deploy_looks_like_a_real_one(state_posts):
    events = Events()
    backend = StateBackend(address="http://api/internal/tfstate/d1", username="t1", password="tok")

    result = simulate.deploy_application(
        events, "d1", user_vars={"terraform": {}}, teams=TEAMS, state_backend=backend, commit_sha="c" * 40
    )

    outputs = result["terraform_outputs"]
    assert set(outputs["team_vms"]["value"]) == {"Team-1", "Team-2"}
    # Account keys as the Online-IDE builds them, so "Meine Zugänge" matches.
    assert set(outputs["user_accounts"]["value"]) == {"Team-1-anna-b", "Team-1-ben", "Team-2-cem"}
    assert outputs["user_accounts"]["sensitive"] is True
    progress = [p for name, p in events.events if name == "task-progress"]
    assert progress and progress[-1]["phase_index"] == progress[-1]["total_phases"]

    [(url, state, auth)] = state_posts
    assert url == backend.address and auth == ("t1", "tok")
    servers = state["resources"][0]["instances"]
    assert {s["attributes"]["metadata"]["team"] for s in servers} == {"Team-1", "Team-2"}


def test_simulate_failure_fails_in_the_apply_phase(state_posts):
    with pytest.raises(Failure) as exc:
        simulate.deploy_application(Events(), "d1", user_vars={"terraform": {"simulate_failure": True}}, teams=TEAMS)
    assert "TERRAFORM_APPLY" in str(exc.value)
    assert state_posts == []


def test_the_runner_switches_to_simulated_jobs(monkeypatch):
    monkeypatch.setattr(settings, "WORKER_SIMULATE", True)
    called = {}
    monkeypatch.setitem(runner.SIMULATED_JOBS, TaskType.PAUSE, lambda _events, **kw: called.update(kw) or {"ok": 1})

    class _Task:
        type = TaskType.PAUSE
        deploymentId = "d1"
        taskId = "t1"

    payload = {
        "app_id": "a", "app_git_link": "", "release": "v1", "commit_sha": "c" * 40,
        "user_vars": {}, "teams": {}, "openstack_envelope": {},
    }
    assert runner.run_job(_Task(), payload, Events()) == {"ok": 1}
    assert called["deployment_id"] == "d1"
