"""Approvals and deployments are bound to a commit, not to a tag name (plan AP2)."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

from appstore_api.crud import app_version_approvals as crud_approvals
from appstore_api.models import App
from appstore_api.services.git_service import git_service
from tests.conftest import TEST_COURSE, TEST_SHA, add_credential, approve_version, queued_task

pytestmark = pytest.mark.integration

MOVED_SHA = "f" * 40


def _credentials(db, user):
    return add_credential(db, user)


def _app(db, owner, *, is_private=False) -> App:
    app = App(name="a", userId=owner.userId, git_link="https://github.com/example/app", is_private=is_private)
    db.add(app)
    db.commit()
    return app


def _deploy(client, credential, app, tag="v1.0"):
    return client.post(
        "/deployments/",
        json={
            "name": "d",
            "appId": str(app.appId),
            "releaseTag": tag,
            "course": TEST_COURSE,
            "credentialId": str(credential.credentialId),
            "teams": [],
        },
    )


def test_public_app_needs_an_approval_for_the_current_commit(client, db, mock_user):
    cred = _credentials(db, mock_user)
    app = _app(db, mock_user)

    assert _deploy(client, cred, app).status_code == 403

    approve_version(db, app, "v1.0")
    response = _deploy(client, cred, app)

    assert response.status_code == 201, response.text
    task, payload = queued_task(db, uuid.UUID(response.json()["deploymentId"]))
    assert payload["commit_sha"] == TEST_SHA
    assert response.json()["commit_sha"] == TEST_SHA


def test_a_moved_tag_is_no_longer_approved(client, db, mock_user, monkeypatch):
    cred = _credentials(db, mock_user)
    app = _app(db, mock_user)
    approve_version(db, app, "v1.0")
    monkeypatch.setattr(git_service, "resolve_tag", lambda _u, _t: MOVED_SHA)

    response = _deploy(client, cred, app)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "version_not_approved"


def test_private_app_deploys_unapproved_tags_for_its_owner(client, db, mock_user, empty_app_checkout):
    cred = _credentials(db, mock_user)
    app = _app(db, mock_user, is_private=True)

    response = _deploy(client, cred, app, tag="v0.1-test")

    assert response.status_code == 201, response.text


def test_unknown_tag_is_404(client, db, mock_user, monkeypatch):
    cred = _credentials(db, mock_user)
    app = _app(db, mock_user, is_private=True)
    monkeypatch.setattr(git_service, "resolve_tag", lambda _u, _t: None)

    assert _deploy(client, cred, app).status_code == 404


def test_release_tag_is_required(client, db, mock_user):
    app = _app(db, mock_user, is_private=True)

    response = client.post("/deployments/", json={"name": "d", "appId": str(app.appId), "course": TEST_COURSE, "credentialId": str(uuid.uuid4()), "teams": []})

    assert response.status_code == 422


def test_lifecycle_jobs_check_out_the_deployed_commit(client, db, mock_user, monkeypatch, jobs, empty_app_checkout):
    cred = _credentials(db, mock_user)
    app = _app(db, mock_user, is_private=True)
    deployment_id = uuid.UUID(_deploy(client, cred, app).json()["deploymentId"])
    task, _ = queued_task(db, deployment_id)
    task.status = task.status.__class__.SUCCESS
    db.commit()
    # The tag moves after the deploy; destroy must still use the old commit.
    monkeypatch.setattr(git_service, "resolve_tag", lambda _u, _t: MOVED_SHA)

    response = client.delete(f"/deployments/{deployment_id}")

    assert response.status_code in (200, 202), response.text
    _, payload = queued_task(db, deployment_id)
    assert payload["commit_sha"] == TEST_SHA


def test_approval_is_refused_when_the_tag_moved_after_submission(admin_client, db, mock_user, monkeypatch):
    app = _app(db, mock_user)
    crud_approvals.submit_version(db, app.appId, "v1.0", commit_sha=TEST_SHA)
    monkeypatch.setattr(git_service, "resolve_tag", lambda _u, _t: MOVED_SHA)

    response = admin_client.post(f"/admin/apps/{app.appId}/versions/v1.0/approve")

    assert response.status_code == 409
    assert response.json()["detail"]["reason"] == "version_moved"


def test_resubmitting_a_moved_tag_replaces_the_old_approval(db, mock_user):
    app = _app(db, mock_user)
    approve_version(db, app, "v1.0")

    approval = crud_approvals.submit_version(db, app.appId, "v1.0", commit_sha=MOVED_SHA)

    assert approval.status.value == "pending"
    assert approval.commit_sha == MOVED_SHA


def test_version_list_marks_approval_per_commit(client, db, mock_user):
    app = _app(db, mock_user)
    approve_version(db, app, "v1.0")
    tags = [
        {"version": "v1.0", "commit": TEST_SHA[:8], "sha": TEST_SHA, "type": "tag"},
        {"version": "v2.0", "commit": "abcdef12", "sha": "abcdef12" * 5, "type": "tag"},
    ]
    with patch.object(git_service, "get_versions", return_value=tags):
        versions = client.get(f"/apps/{app.appId}").json()["versions"]

    assert {v["version"]: v["approved"] for v in versions} == {"v1.0": True, "v2.0": False}


def test_registering_an_app_from_another_host_is_refused(client):
    response = client.post(
        "/apps/", json={"name": "x", "git_link": "https://evil.example/o/r", "is_private": True}
    )

    assert response.status_code == 422
    assert response.json()["detail"]["reason"] == "git_host_not_allowed"
