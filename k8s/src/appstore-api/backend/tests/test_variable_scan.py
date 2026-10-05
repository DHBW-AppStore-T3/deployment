"""The variable scan reads the commit under review or deployment, is cached
per commit, and refuses rather than skipping its checks when the repository
cannot be read."""

from __future__ import annotations

import git
import pytest

from appstore_api.services.git_service import git_service
from tests.conftest import TEST_SHA, create_app_in_db

pytestmark = pytest.mark.integration


@pytest.fixture
def clones(tmp_path, monkeypatch):
    """Record every clone; each returns an empty checkout."""
    calls: list[tuple[str, str]] = []

    def clone(_url, tag, sha):
        calls.append((tag, sha))
        path = tmp_path / f"c{len(calls)}"
        path.mkdir()
        return str(path)

    monkeypatch.setattr(git_service, "clone_release_vars", clone)
    monkeypatch.setattr(git_service, "cleanup_repository", lambda _p: None)
    return calls


def test_submit_scans_the_submitted_commit_and_caches_it(client, mock_user, db, clones):
    app = create_app_in_db(db, mock_user)

    assert client.get(f"/apps/{app.appId}/variables", params={"version": "v1.0"}).status_code == 200
    assert client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={}).status_code == 201

    # Same commit twice: cloned once, and the commit, not the tag, was read.
    assert clones == [("v1.0", TEST_SHA)]


def test_submit_is_refused_when_the_repository_cannot_be_read(client, mock_user, db, monkeypatch):
    app = create_app_in_db(db, mock_user)

    def unreadable(*_args):
        raise git.GitCommandError("fetch", 128, stderr="fatal: unable to access")

    monkeypatch.setattr(git_service, "clone_release_vars", unreadable)

    response = client.post(f"/apps/{app.appId}/versions/v1.0/submit", json={})

    assert response.status_code == 502
    assert response.json()["detail"]["reason"] == "git_unreachable"


def test_unknown_tag_is_404_not_500(client, mock_user, db, monkeypatch, clones):
    app = create_app_in_db(db, mock_user)
    monkeypatch.setattr(git_service, "resolve_tag", lambda _u, _t: None)

    response = client.get(f"/apps/{app.appId}/variables", params={"version": "v9"})

    assert response.status_code == 404
    assert clones == []
