"""The pod jobs against an in-memory cluster."""

from __future__ import annotations

import copy

import pytest

from appstore_shared.k8s.fake import FakeKube
from appstore_shared.models import TaskType
from appstore_worker import k8s_runtime, runner
from appstore_worker.config import settings
from appstore_worker.tasks import Failure

DIGEST = "sha256:" + "a" * 64
DEP = "123e4567-e89b-12d3-a456-426614174000"
NS = "dep-123e4567"
SPEC = {
    "apiVersion": "appstore/v2",
    "name": "online-ide",
    "runtime": "kubernetes",
    "scope": "user",
    "workload": {
        "containers": [
            {
                "name": "ide",
                "image": f"ghcr.io/dhbw-appstore-t3/apps/code-server@{DIGEST}",
                "expose": {"port": 8080},
                "resources": {"cpu": "500m", "memory": "1Gi"},
                "env": [{"name": "PASSWORD", "from": "generated-password"}],
            }
        ],
        "storage": {"size": "5Gi", "mountPath": "/home/coder"},
    },
    "egress": "internet",
    "access": [
        {"type": "url", "template": "https://{workload}-{deployment}.apps.{zone}"},
        {"type": "password", "from": "generated-password", "username": "{user}"},
    ],
}
TEAMS = {
    "Team-1": [{"email": "anna.b@dhbw.de"}, {"email": "ben@dhbw.de"}],
    "Team-2": [{"email": "cem@dhbw.de"}, {"email": "dora@dhbw.de"}],
    "Team-3": [{"email": "eli@dhbw.de"}, {"email": "fay@dhbw.de"}],
}


class Events:
    def __init__(self):
        self.events = []

    def send_event(self, event_type, **payload):
        self.events.append((event_type, payload))

    def phases(self):
        return [p["phase"] for t, p in self.events if t == "task-progress"]


@pytest.fixture(autouse=True)
def cluster(monkeypatch):
    monkeypatch.setattr(settings, "K8S_ZONE", "z.example.org")
    monkeypatch.setattr(settings, "K8S_WORKER_NAMESPACE", "appstore-staging")
    monkeypatch.setattr(settings, "K8S_POLL_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(settings, "K8S_READY_TIMEOUT_SECONDS", 5)
    monkeypatch.setattr(settings, "K8S_DELETE_TIMEOUT_SECONDS", 5)
    kube = FakeKube()
    k8s_runtime.set_kube_factory(lambda: kube)
    return kube


def deploy(spec=SPEC, teams=TEAMS, events=None):
    return k8s_runtime.deploy_application(
        events or Events(), DEP, {}, teams, commit_sha="c" * 40, spec=spec, course="group:wwi24", owner="doz@dhbw.de"
    )


def test_deploy_creates_namespace_and_six_ready_workloads(cluster):
    events = Events()
    result = deploy(events=events)
    assert result["status"] == "success"
    assert cluster.workloads(NS) == {
        "team-1-anna-b", "team-1-ben", "team-2-cem", "team-2-dora", "team-3-eli", "team-3-fay"
    }
    assert events.phases() == list(k8s_runtime.PHASES_DEPLOY)
    assert cluster.deployment_label(NS) == DEP
    kinds = cluster.kinds(NS)
    assert {"ResourceQuota", "LimitRange", "NetworkPolicy", "RoleBinding", "StatefulSet", "Ingress"} <= set(kinds)


def test_outputs_give_every_person_their_own_url_and_password():
    out = deploy()["terraform_outputs"]
    accounts = out["user_accounts"]["value"]
    assert out["user_accounts"]["sensitive"] is True
    assert set(accounts) == {
        "Team-1-anna-b", "Team-1-ben", "Team-2-cem", "Team-2-dora", "Team-3-eli", "Team-3-fay"
    }
    assert accounts["Team-1-anna-b"]["auth"] != accounts["Team-1-ben"]["auth"]
    assert accounts["Team-1-anna-b"]["url"] == "https://team-1-anna-b-123e4567.apps.z.example.org"
    assert accounts["Team-1-ben"]["username"] == "ben"
    assert set(out["team_vms"]["value"]) == {"Team-1", "Team-2", "Team-3"}


def test_team_scope_shares_one_workload_per_team():
    out = deploy(spec={**SPEC, "scope": "team"})["terraform_outputs"]["user_accounts"]["value"]
    assert out["Team-1-anna-b"]["auth"] == out["Team-1-ben"]["auth"]
    assert out["Team-1-anna-b"]["auth"] != out["Team-2-cem"]["auth"]


@pytest.mark.parametrize(
    ("reason", "text"),
    [
        ("ImagePullBackOff", "image cannot be pulled"),
        ("CrashLoopBackOff", "keeps crashing"),
        ("Unschedulable", "no capacity"),
        ("quota", "quota exceeded"),
    ],
)
def test_failures_are_explained_and_the_namespace_is_removed(cluster, reason, text):
    cluster.fail_reason = reason
    with pytest.raises(Failure, match=text):
        deploy()
    cluster.snapshot(NS)
    cluster.snapshot(NS)
    assert cluster.namespaces(f"appstore.dhbw/deployment-id={DEP}") in ([], [NS])  # being removed
    assert NS in cluster._terminating or NS not in cluster.namespace_labels


def test_timeout_is_reported(cluster, monkeypatch):
    monkeypatch.setattr(settings, "K8S_READY_TIMEOUT_SECONDS", 0)
    cluster.ready_after_polls = 10**6
    with pytest.raises(Failure, match="timed out"):
        deploy()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["workload"]["containers"][0].update(image="ghcr.io/dhbw-appstore-t3/apps/x:latest"),
        lambda s: s["workload"]["containers"][0].update(image=f"docker.io/evil/x@{DIGEST}"),
        lambda s: s["workload"]["containers"][0].update(resources={"cpu": "64", "memory": "1Gi"}),
        lambda s: s.update(hostNetwork=True),
    ],
)
def test_deploy_validates_the_spec_again_and_touches_nothing(cluster, mutate):
    spec = copy.deepcopy(SPEC)
    mutate(spec)
    with pytest.raises(Failure, match="appstore.yaml is invalid"):
        deploy(spec=spec)
    assert cluster.objects == {}


def test_deploy_without_members_fails():
    with pytest.raises(Failure, match="no teams or members"):
        deploy(teams={})


def test_pause_stops_all_pods_and_resume_brings_them_back(cluster):
    deploy()
    k8s_runtime.pause_deployment(Events(), DEP)
    snap = cluster.snapshot(NS)
    assert snap.pods == [] and all(s.replicas == 0 for s in snap.statefulsets)
    assert "StatefulSet" in cluster.kinds(NS)  # volumes claims and secrets stay
    k8s_runtime.resume_deployment(Events(), DEP)
    snap = cluster.snapshot(NS)
    assert len(snap.pods) == 6 and all(p.ready for p in snap.pods)


def test_destroy_removes_the_namespace_and_everything_with_the_label(cluster):
    deploy()
    result = k8s_runtime.destroy_deployment(Events(), DEP)
    assert result["status"] == "success"
    assert NS not in cluster.namespace_labels
    assert cluster.namespaces(f"appstore.dhbw/deployment-id={DEP}") == []
    assert cluster.objects == {}


def test_destroy_of_an_already_removed_namespace_succeeds(cluster):
    assert k8s_runtime.destroy_deployment(Events(), DEP)["status"] == "success"


def test_destroy_in_the_middle_of_a_deploy_leaves_nothing(cluster):
    cluster.ready_after_polls = 10**6
    cluster.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NS, "labels": {"appstore.dhbw/deployment-id": DEP}}})
    k8s_runtime.destroy_deployment(Events(), DEP)
    assert cluster.namespaces(f"appstore.dhbw/deployment-id={DEP}") == []


def test_redeploy_restarts_only_that_workload_and_keeps_its_data(cluster):
    deploy()
    k8s_runtime.redeploy_resource(Events(), DEP, resource_address="team-1-ben")
    assert cluster.deleted_pods == ["team-1-ben-0"]
    assert cluster.deleted_pvcs == []


def test_redeploy_reset_deletes_the_volume(cluster):
    deploy()
    k8s_runtime.redeploy_resource(Events(), DEP, resource_address="reset:team-1-ben")
    assert cluster.deleted_pvcs == [(NS, "team-1-ben")]


@pytest.mark.parametrize("address", ["nope", "../x", "team-1-ben;rm", ""])
def test_redeploy_rejects_unknown_or_malformed_workloads(address):
    deploy()
    with pytest.raises(Failure):
        k8s_runtime.redeploy_resource(Events(), DEP, resource_address=address)


def test_runner_routes_pod_payloads_to_the_pod_jobs(monkeypatch):
    import uuid

    from appstore_shared.models import Task

    called = {}
    monkeypatch.setitem(runner.K8S_JOBS, TaskType.DEPLOY, lambda _events, **kw: called.update(kw) or {})
    task = Task(taskId=uuid.uuid4(), deploymentId=uuid.UUID(DEP), type=TaskType.DEPLOY)
    payload: dict = {
        "app_id": "a", "app_git_link": "", "release": "v1", "commit_sha": "c", "user_vars": {},
        "teams": TEAMS, "openstack_envelope": {}, "runtime": "kubernetes", "spec": SPEC, "course": "c", "owner": "o",
    }
    runner.run_job(task, payload, Events())
    assert called["spec"] == SPEC and called["course"] == "c"


def test_cancel_while_deploying_removes_the_namespace_again(cluster):
    class CancelledAfterNamespace(Events):
        def is_cancelled(self):
            return NS in cluster.namespace_labels  # cancelled the moment something exists

    with pytest.raises(Failure, match="cancelled"):
        deploy(events=CancelledAfterNamespace())
    cluster.snapshot(NS)
    cluster.snapshot(NS)
    assert NS not in cluster.namespace_labels


def test_cancel_before_anything_is_created_creates_nothing(cluster):
    class AlreadyCancelled(Events):
        def is_cancelled(self):
            return True

    with pytest.raises(Failure, match="cancelled"):
        deploy(events=AlreadyCancelled())
    assert cluster.objects == {}
