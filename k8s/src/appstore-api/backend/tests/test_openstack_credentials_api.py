"""OpenStack credentials per project, and project peers (plan AP5, E2).

Keystone is patched at ``openstack_validator.validate``; what is tested is
that only accepted credentials are stored, that their project comes from
Keystone and not from the request, and who may do what with a deployment
in a project.
"""
from __future__ import annotations

import base64
import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from appstore_api.crud import openstack_credentials as crud_creds
from appstore_api.models import App, Deployment, Task, TaskStatus, TaskType, UserOpenStackCredential
from appstore_api.services import openstack_validator
from appstore_api.services.openstack_validator import CredentialRejected, Scope
from appstore_api.utils import crypto
from tests.conftest import (
    TEST_COURSE,
    TEST_PROJECT,
    TEST_SHA,
    _make_client,
    add_credential,
    queued_task,
)

pytestmark = pytest.mark.integration

VALIDATE = "appstore_api.routers.openstack_credentials.openstack_validator.validate"

_PASSWORD_PAYLOAD = {
    "auth_type": "password",
    "auth_url": "https://keystone.example/v3",
    "region_name": "RegionOne",
    "project_name": "demo",
    "user_domain_name": "Default",
    "project_domain_name": "Default",
    "identifier": "alice",
    "secret": "s3cret",
}

_APPCRED_PAYLOAD = {
    "auth_type": "v3applicationcredential",
    "auth_url": "https://keystone.example/v3",
    "region_name": "RegionOne",
    # Claims a project; only what Keystone says counts.
    "project_id": "claimed-project",
    "identifier": "appcred-id",
    "secret": "appcred-secret",
}

_CLOUDS_YAML = """\
clouds:
  mycloud:
    auth_type: v3applicationcredential
    auth:
      auth_url: https://keystone.example/v3
      application_credential_id: appcred-id
      application_credential_secret: appcred-secret
    region_name: RegionOne
"""


def _accepted(project_id=TEST_PROJECT, project_name="Projekt 1"):
    return patch(VALIDATE, return_value=Scope(project_id=project_id, project_name=project_name))


# ----------------------------------------------------------------
# saving
# ----------------------------------------------------------------
def test_an_accepted_credential_is_stored_for_the_tokens_project(client, db, mock_user):
    with _accepted():
        response = client.post("/me/openstack-credentials", json=_APPCRED_PAYLOAD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["project_id"] == TEST_PROJECT
    assert body["project_name"] == "Projekt 1"
    assert "secret" not in json.dumps(body) and "appcred-secret" not in json.dumps(body)
    [row] = crud_creds.list_for_user(db, mock_user.userId)
    assert crypto.decrypt(row.encrypted_secret) == "appcred-secret"
    assert row.last_validated_at is not None


def test_a_rejected_credential_is_not_stored(client, db, mock_user):
    with patch(VALIDATE, side_effect=CredentialRejected("invalid_credentials", 401)):
        response = client.post("/me/openstack-credentials", json=_PASSWORD_PAYLOAD)

    assert response.status_code == 422
    assert response.json()["detail"] == {"reason": "openstack_credentials_invalid", "cause": "invalid_credentials"}
    assert crud_creds.list_for_user(db, mock_user.userId) == []


def test_one_credential_per_project_saving_again_rotates_it(client, db, mock_user):
    with _accepted():
        first = client.post("/me/openstack-credentials", json=_APPCRED_PAYLOAD).json()
    with _accepted():
        second = client.post("/me/openstack-credentials", json={**_APPCRED_PAYLOAD, "secret": "rotated"})
    with _accepted("project-2", "Projekt 2"):
        other = client.post("/me/openstack-credentials", json=_PASSWORD_PAYLOAD)

    assert second.status_code == 200
    assert second.json()["credentialId"] == first["credentialId"]
    assert other.status_code == 201
    rows = {r.project_id: r for r in crud_creds.list_for_user(db, mock_user.userId)}
    assert set(rows) == {TEST_PROJECT, "project-2"}
    assert crypto.decrypt(rows[TEST_PROJECT].encrypted_secret) == "rotated"
    listed = client.get("/me/openstack-credentials").json()
    assert [c["project_name"] for c in listed] == ["Projekt 1", "Projekt 2"]


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({**_PASSWORD_PAYLOAD, "user_domain_name": None}, "user_domain_name"),
        ({**_PASSWORD_PAYLOAD, "project_name": None}, "project_id or project_name"),
    ],
)
def test_password_credentials_need_domain_and_project(client, payload, message):
    with patch(VALIDATE) as validate:
        response = client.post("/me/openstack-credentials", json=payload)
    assert response.status_code == 422
    assert message in response.text
    validate.assert_not_called()


def test_from_yaml(client, db, mock_user):
    with _accepted():
        response = client.post(
            "/me/openstack-credentials/from-yaml", json={"clouds_yaml": _CLOUDS_YAML, "cloud_name": "mycloud"}
        )

    assert response.status_code == 201, response.text
    [row] = crud_creds.list_for_user(db, mock_user.userId)
    assert crypto.decrypt(row.encrypted_identifier) == "appcred-id"


def test_from_yaml_unknown_cloud_is_422_without_asking_keystone(client):
    with patch(VALIDATE) as validate:
        response = client.post(
            "/me/openstack-credentials/from-yaml", json={"clouds_yaml": _CLOUDS_YAML, "cloud_name": "nope"}
        )
    assert response.status_code == 422
    validate.assert_not_called()


# ----------------------------------------------------------------
# test / delete, and other people's credentials
# ----------------------------------------------------------------
def test_retest_records_the_outcome(client, db, mock_user):
    row = add_credential(db, mock_user)

    with patch(VALIDATE, side_effect=CredentialRejected("invalid_credentials", 401)):
        failed = client.post(f"/me/openstack-credentials/{row.credentialId}/test").json()
    with _accepted("somewhere-else"):
        moved = client.post(f"/me/openstack-credentials/{row.credentialId}/test").json()
    with _accepted():
        ok = client.post(f"/me/openstack-credentials/{row.credentialId}/test").json()

    assert failed["last_validation_error"] == "invalid_credentials"
    assert moved["last_validation_error"] == "project_changed"
    assert ok["last_validation_error"] is None and ok["last_validated_at"] is not None


def test_other_peoples_credentials_do_not_exist_for_the_caller(client, db, mock_admin):
    theirs = add_credential(db, mock_admin)

    with patch(VALIDATE) as validate:
        assert client.post(f"/me/openstack-credentials/{theirs.credentialId}/test").status_code == 404
    assert client.delete(f"/me/openstack-credentials/{theirs.credentialId}").status_code == 404
    assert client.get(f"/me/openstack-credentials/{theirs.credentialId}/quota").status_code == 404
    assert client.get("/me/openstack-credentials").json() == []
    validate.assert_not_called()
    assert db.get(UserOpenStackCredential, theirs.credentialId) is not None


def _live_deployment(db, owner, project_id=TEST_PROJECT) -> Deployment:
    app = App(name="a", userId=owner.userId, git_link="https://github.com/example/app")
    db.add(app)
    db.flush()
    dep = Deployment(
        name="d",
        appId=app.appId,
        userId=owner.userId,
        commit_sha=TEST_SHA,
        course=TEST_COURSE,
        os_project_id=project_id,
        releaseTag="v1",
        userInputVar=json.dumps({"terraform": {}}),
    )
    db.add(dep)
    db.flush()
    db.add(Task(deploymentId=dep.deploymentId, type=TaskType.DEPLOY, status=TaskStatus.SUCCESS))
    db.commit()
    return dep


def test_delete_is_refused_while_own_deployments_live_in_the_project(client, db, mock_user):
    busy = add_credential(db, mock_user)
    idle = add_credential(db, mock_user, "project-2", identifier="other")
    _live_deployment(db, mock_user)

    locked = client.delete(f"/me/openstack-credentials/{busy.credentialId}")
    assert locked.status_code == 409
    assert locked.json()["detail"] == {"reason": "openstack_credentials_locked", "active_deployments": 1}
    assert client.delete(f"/me/openstack-credentials/{idle.credentialId}").status_code == 204
    assert [c["project_id"] for c in client.get("/me/openstack-credentials").json()] == [TEST_PROJECT]


# ----------------------------------------------------------------
# project peers (E2)
# ----------------------------------------------------------------
@pytest.fixture
def peer(db):
    from tests.roles import Role, make_user

    user = make_user(Role.DOZENT, email="peer@dhbw.de", username="peer")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def peer_client(peer):
    from appstore_api.main import app

    yield _make_client(peer)
    app.dependency_overrides.clear()


def test_a_project_peer_sees_and_runs_the_deployment_with_their_own_credential(db, mock_user, peer, peer_client):
    add_credential(db, mock_user, identifier="owner-cred")
    peer_credential = add_credential(db, peer, identifier="peer-cred")
    dep = _live_deployment(db, mock_user)

    assert [d["deploymentId"] for d in peer_client.get("/deployments/").json()] == [str(dep.deploymentId)]
    assert peer_client.get(f"/deployments/{dep.deploymentId}").status_code == 200
    response = peer_client.post(f"/deployments/{dep.deploymentId}/pause")

    assert response.status_code == 202, response.text
    _task, payload = queued_task(db, dep.deploymentId)
    envelope = payload["openstack_envelope"]
    assert crypto.decrypt(base64.b64decode(envelope["encrypted_identifier_b64"])) == "peer-cred"
    assert envelope["project_id"] == peer_credential.project_id


def test_a_credential_for_another_project_makes_no_peer(db, mock_user, peer, peer_client):
    add_credential(db, peer, "project-2", identifier="peer-cred")
    dep = _live_deployment(db, mock_user)

    assert peer_client.get("/deployments/").json() == []
    assert peer_client.get(f"/deployments/{dep.deploymentId}").status_code == 403
    assert peer_client.post(f"/deployments/{dep.deploymentId}/pause").status_code == 403


def test_the_owner_without_a_credential_for_the_project_cannot_act(client, db, mock_user):
    dep = _live_deployment(db, mock_user)

    response = client.post(f"/deployments/{dep.deploymentId}/pause")

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "reason": "openstack_credentials_missing_for_project",
        "project_id": TEST_PROJECT,
    }


def test_deploying_needs_one_of_ones_own_credentials(client, db, mock_user, mock_admin):
    theirs = add_credential(db, mock_admin)
    app = App(name="a", userId=mock_user.userId, git_link="https://github.com/example/app", is_private=True)
    db.add(app)
    db.commit()

    response = client.post(
        "/deployments/",
        json={
            "name": "d",
            "appId": str(app.appId),
            "releaseTag": "v1",
            "course": TEST_COURSE,
            "credentialId": str(theirs.credentialId),
            "teams": [],
        },
    )

    assert response.status_code == 412
    assert response.json()["detail"] == {"reason": "openstack_credentials_missing"}
    assert db.query(Deployment).count() == 0


# ----------------------------------------------------------------
# validator
# ----------------------------------------------------------------
def _upsert(**overrides):
    from appstore_api.schemas import OpenStackCredentialUpsert

    return OpenStackCredentialUpsert(**{**_APPCRED_PAYLOAD, **overrides})


def _connect_returning(access):
    from keystoneauth1.identity.base import BaseIdentityPlugin

    auth = MagicMock(spec=BaseIdentityPlugin)
    auth.get_access.return_value = access
    conn = MagicMock()
    conn.session.auth = auth
    return patch("appstore_api.services.openstack_validator.openstack.connect", return_value=conn)


def test_validator_takes_the_project_from_the_token():
    access = MagicMock(project_id="real-project", project_name="Real")
    with _connect_returning(access) as connect:
        scope = openstack_validator.validate(_upsert())

    assert scope == Scope(project_id="real-project", project_name="Real")
    kwargs = connect.call_args.kwargs
    assert kwargs["api_timeout"] == openstack_validator.TIMEOUT_SECONDS
    assert kwargs["application_credential_secret"] == "appcred-secret"


def test_validator_refuses_unscoped_tokens():
    with _connect_returning(MagicMock(project_id=None)), pytest.raises(CredentialRejected) as exc:
        openstack_validator.validate(_upsert())
    assert exc.value.reason == "not_project_scoped"


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        ("unauthorized", "invalid_credentials"),
        ("not_found", "project_not_found"),
        ("connect", "unreachable"),
        ("other", "error"),
    ],
)
def test_validator_reasons_never_carry_the_error_text(error, reason):
    from keystoneauth1 import exceptions as ks_exc

    raised = {
        "unauthorized": ks_exc.Unauthorized("secret appcred-secret"),
        "not_found": ks_exc.NotFound("x"),
        "connect": ks_exc.ConnectFailure("down"),
        "other": RuntimeError("body: appcred-secret"),
    }[error]
    with patch("appstore_api.services.openstack_validator.openstack.connect", side_effect=raised), pytest.raises(
        CredentialRejected
    ) as exc:
        openstack_validator.validate(_upsert())
    assert exc.value.reason == reason
    assert "appcred-secret" not in str(exc.value)


# ----------------------------------------------------------------
# development without a cloud (OPENSTACK_SIMULATE, plan AP7)
# ----------------------------------------------------------------
@pytest.fixture
def simulated(monkeypatch):
    from appstore_api.config import settings

    monkeypatch.setattr(settings, "OPENSTACK_SIMULATE", True)


def test_simulated_openstack_accepts_credentials_and_answers_the_picker(client, db, mock_user, simulated):
    from appstore_api.services import openstack_client

    with patch("appstore_api.services.openstack_client.openstack.connect") as connect:
        saved = client.post("/me/openstack-credentials", json={**_PASSWORD_PAYLOAD, "project_name": "Kurs-Projekt"})
        assert saved.status_code == 201, saved.text
        credential_id = saved.json()["credentialId"]
        openstack_client.invalidate(uuid.UUID(credential_id))

        networks = client.get(f"/me/openstack-credentials/{credential_id}/resources/networks").json()
        quota = client.get(f"/me/openstack-credentials/{credential_id}/quota").json()

    connect.assert_not_called()
    assert saved.json()["project_name"] == "Kurs-Projekt"
    assert saved.json()["project_id"].startswith("sim-")
    assert {n["name"] for n in networks} == {"internal", "public"}
    assert quota["compute"]["instances"]["limit"] == 10


def test_simulation_is_refused_outside_development():
    from pydantic import ValidationError

    from appstore_api.config import Settings

    with pytest.raises(ValidationError, match="OPENSTACK_SIMULATE"):
        Settings(
            DATABASE_URL="postgresql://x/y",
            OIDC_ISSUER_URL="https://idp.example",
            OIDC_CLIENT_ID="c",
            ROLE_PROVIDER="http",
            ROLE_PROVIDER_URL="http://rp",
            ROLE_PROVIDER_API_TOKEN="t",
            API_MODE="production",
            OPENSTACK_SIMULATE=True,
        )
