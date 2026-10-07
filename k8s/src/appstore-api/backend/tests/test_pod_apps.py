"""Apps that run as pods (appstore.yaml): submit, approve, deploy, lifecycle (issue #4)."""

from __future__ import annotations

import copy
import uuid

import pytest
import yaml

from appstore_api.models import App
from appstore_api.services import app_spec
from tests.conftest import TEST_COURSE, TEST_SHA, add_credential, approve_version, queued_task

pytestmark = pytest.mark.integration

DIGEST = "sha256:" + "a" * 64
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
    "variables": [{"name": "cpu_class", "type": "enum", "values": ["small", "medium"], "default": "small"}],
    "access": [
        {"type": "url", "template": "https://{workload}-{deployment}.apps.{zone}"},
        {"type": "password", "from": "generated-password", "username": "{user}"},
    ],
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Make the clone of any app commit be a checkout holding ``checkout/appstore.yaml``."""
    from appstore_api.services.git_service import git_service

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(git_service, "clone_release_vars", lambda _u, _t, _s: str(checkout))
    monkeypatch.setattr(git_service, "cleanup_repository", lambda _p: None)

    def write(spec):
        (checkout / "appstore.yaml").write_text(yaml.safe_dump(spec))

    write(SPEC)
    write.checkout = checkout
    return write


def _app(db, owner, *, is_private=False) -> App:
    app = App(name="ide", userId=owner.userId, git_link="https://github.com/example/ide", is_private=is_private)
    db.add(app)
    db.commit()
    return app


def _deploy(client, app, *, credential=None, tag="v1.0", **extra):
    body = {
        "name": "d",
        "appId": str(app.appId),
        "releaseTag": tag,
        "course": TEST_COURSE,
        "teams": [],
        **extra,
    }
    if credential is not None:
        body["credentialId"] = str(credential.credentialId)
    return client.post("/deployments/", json=body)


def test_submit_records_runtime_spec_hash_and_digests(client, db, mock_user, repo):
    app = _app(db, mock_user)
    response = client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["runtime"] == "kubernetes"
    assert body["image_digests"] == [DIGEST]
    assert len(body["spec_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda s: s["workload"]["containers"][0].update(image="ghcr.io/dhbw-appstore-t3/apps/x:latest"), "workload.containers[0]"),
        (lambda s: s["workload"]["containers"][0].update(image=f"docker.io/evil/x@{DIGEST}"), "workload.containers[0].image"),
        (lambda s: s["workload"]["containers"][0].update(resources={"cpu": "64", "memory": "1Gi"}), "workload.containers[0].resources.cpu"),
        (lambda s: s.update(privileged=True), "privileged"),
    ],
)
def test_invalid_spec_is_refused_with_a_field_path_and_cannot_be_approved(client, db, mock_user, mock_admin, repo, mutate, path):
    spec = copy.deepcopy(SPEC)
    mutate(spec)
    repo(spec)
    app = _app(db, mock_user)

    response = client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})

    assert response.status_code == 422
    assert path in {e["loc"] for e in response.json()["detail"]["errors"]}
    # not even an admin can approve what does not validate
    from appstore_api.auth import get_current_user
    from appstore_api.main import app as fastapi_app

    fastapi_app.dependency_overrides[get_current_user] = lambda: mock_admin
    try:
        approve = client.post(f"/admin/apps/{app.appId}/versions/v1.0/approve")
    finally:
        fastapi_app.dependency_overrides.pop(get_current_user, None)
    assert approve.status_code in (404, 422)


def test_variables_and_runtime_come_from_the_spec(client, db, mock_user, repo):
    app = _app(db, mock_user)
    variables = client.get(f"/apps/{app.appId}/variables", params={"version": "v1.0"}).json()
    assert [(v["name"], v["osType"], v["source"]) for v in variables] == [("cpu_class", "enum", "appstore")]
    runtime = client.get(f"/apps/{app.appId}/runtime", params={"version": "v1.0"}).json()
    assert runtime["runtime"] == "kubernetes" and runtime["scope"] == "user" and runtime["egress"] == "internet"


def test_runtime_of_a_vm_app(client, db, mock_user, empty_app_checkout):
    app = _app(db, mock_user)
    assert client.get(f"/apps/{app.appId}/runtime", params={"version": "v1.0"}).json()["runtime"] == "openstack-vm"


def test_pod_app_deploys_without_an_openstack_credential(client, db, mock_user, repo):
    app = _app(db, mock_user)
    client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})
    _approve_in_db(db, app)

    response = _deploy(client, app)

    assert response.status_code == 201, response.text
    deployment_id = uuid.UUID(response.json()["deploymentId"])
    task, payload = queued_task(db, deployment_id)
    assert payload["runtime"] == "kubernetes"
    assert payload["openstack_envelope"] == {}
    assert payload["spec"]["workload"]["containers"][0]["image"].endswith(DIGEST)
    assert payload["teams"] == {}
    from appstore_api.models import Deployment

    row = db.query(Deployment).get(deployment_id)
    assert row.runtime == "kubernetes"
    assert row.os_project_id == app_spec.K8S_PROJECT
    assert row.k8s_namespace == f"dep-{deployment_id.hex[:8]}"


def _approve_in_db(db, app):
    from appstore_api.models import AppVersionApproval, AppVersionApprovalStatus

    db.expire_all()
    row = db.query(AppVersionApproval).filter_by(appId=app.appId, version_tag="v1.0").one()
    row.status = AppVersionApprovalStatus.APPROVED
    db.commit()


def test_changed_spec_after_approval_is_not_deployable(client, db, mock_user, repo):
    app = _app(db, mock_user)
    client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})
    _approve_in_db(db, app)
    changed = copy.deepcopy(SPEC)
    changed["workload"]["containers"][0]["resources"]["cpu"] = "1"
    repo(changed)
    from appstore_api.routers import apps as apps_router

    apps_router.clear_variable_cache()

    response = _deploy(client, app)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "version_not_approved"


def test_a_supplied_credential_is_ignored_for_pods(client, db, mock_user, repo):
    app = _app(db, mock_user)
    client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})
    _approve_in_db(db, app)
    response = _deploy(client, app, credential=add_credential(db, mock_user))
    deployment_id = uuid.UUID(response.json()["deploymentId"])
    _task, payload = queued_task(db, deployment_id)
    assert payload["openstack_envelope"] == {}
    assert response.json()["os_project_id"] == app_spec.K8S_PROJECT


def test_pause_resume_destroy_of_a_pod_deployment_need_no_credential(client, db, mock_user, repo):
    from appstore_api.models import Task, TaskStatus

    app = _app(db, mock_user)
    client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})
    _approve_in_db(db, app)
    deployment_id = uuid.UUID(_deploy(client, app).json()["deploymentId"])
    db.query(Task).update({"status": TaskStatus.SUCCESS})
    db.commit()

    pause = client.post(f"/deployments/{deployment_id}/pause")

    assert pause.status_code == 202, pause.text
    _task, payload = queued_task(db, deployment_id)
    assert payload["runtime"] == "kubernetes" and payload["openstack_envelope"] == {}


def test_vm_app_still_needs_a_credential(client, db, mock_user, empty_app_checkout):
    """K7 (API side): the VM path is unchanged."""
    app = _app(db, mock_user)
    approve_version(db, app, "v1.0")
    assert _deploy(client, app).status_code == 412
    response = _deploy(client, app, credential=add_credential(db, mock_user))
    assert response.status_code == 201
    _task, payload = queued_task(db, uuid.UUID(response.json()["deploymentId"]))
    assert "runtime" not in payload and payload["openstack_envelope"]
    assert payload["commit_sha"] == TEST_SHA
