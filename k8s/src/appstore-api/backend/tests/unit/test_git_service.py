"""Unit tests for :mod:`appstore_api.services.git_service`.

DB-less Tests: GitPython wird vollständig gemockt; es passieren keine
Netzwerk- oder Dateisystem-Operationen jenseits eines tmp_path. Diese
Tests sichern ``clone_release_vars`` (Sparse-Clone genau des gepinnten
Commits, Fallback auf den Tag, Aufräumen) und das Lesen der Tags per
``git ls-remote``.

Wir patchen ``git.Repo.init`` direkt (statt der ``git_service``-Symbole),
weil der Service ``import git`` macht und ``git.Repo.init`` per
Attribut auflöst. ``autospec`` deaktivieren wir, da ``git.Repo``
dynamische Properties wie ``head.commit`` exponiert, die das echte
Spec-Modell nur umständlich nachbildet — die Tests kontrollieren die
Mock-Surface explizit über ``MagicMock``-Konfiguration.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import git
import pytest

from appstore_api.services.git_service import CommitNotServed, GitService

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _make_repo_mock() -> MagicMock:
    """Build a ``git.Repo``-shaped MagicMock with the surface the
    service touches: ``create_remote``, ``head.commit.hexsha`` and the
    ``git.checkout`` shortcut. Caller mutates ``origin.fetch`` to
    inject error scenarios."""
    repo = MagicMock(name="Repo")
    origin = MagicMock(name="Origin")
    repo.create_remote.return_value = origin
    repo.head.commit.hexsha = "deadbeefcafebabe"
    repo.git.checkout = MagicMock(name="checkout")
    return repo


def _service(tmp_path, monkeypatch) -> GitService:
    """Instantiate the service with a redirected temp base path.
    Avoids relying on the real ``settings`` singleton."""
    svc = GitService()
    monkeypatch.setattr(svc, "base_path", tmp_path)
    return svc


# ----------------------------------------------------------------
# Sparse clone of the pinned commit
# ----------------------------------------------------------------
SHA = "deadbeefcafebabe" + "0" * 24


def _git_error(msg: str) -> git.GitCommandError:
    return git.GitCommandError("fetch", 128, stderr=msg)


@patch("appstore_api.services.git_service.git.Repo")
def test_clone_fetches_the_pinned_commit_shallow(mock_repo_cls, tmp_path, monkeypatch):
    """The commit is fetched and checked out, not the tag: a moved tag must
    not change what is scanned."""
    repo = _make_repo_mock()
    repo.head.commit.hexsha = SHA
    mock_repo_cls.init.return_value = repo

    path = _service(tmp_path, monkeypatch).clone_release_vars(
        "https://github.com/acme/widgets.git", "v1.2.3", SHA
    )

    assert path.startswith(str(tmp_path))
    # Anonymous HTTPS: no credentials in the remote URL.
    repo.create_remote.assert_called_once_with("origin", "https://github.com/acme/widgets.git")
    origin = repo.create_remote.return_value
    origin.fetch.assert_called_once()
    assert origin.fetch.call_args.args == (SHA,)
    assert origin.fetch.call_args.kwargs["depth"] == 1
    repo.git.checkout.assert_called_once_with("--detach", SHA, force=True)


@patch("appstore_api.services.git_service.git.Repo")
def test_clone_falls_back_to_the_tag_and_refuses_a_moved_one(mock_repo_cls, tmp_path, monkeypatch):
    """A host that does not serve commits by SHA gets the tag fetched; if the
    tag points elsewhere now, the pinned commit is not there."""
    repo = _make_repo_mock()
    mock_repo_cls.init.return_value = repo
    origin = repo.create_remote.return_value
    origin.fetch.side_effect = [_git_error("server does not allow request for unadvertised object"), None]
    repo.git.checkout.side_effect = _git_error("reference is not a tree")

    with pytest.raises(CommitNotServed):
        _service(tmp_path, monkeypatch).clone_release_vars("https://github.com/acme/widgets.git", "v1.0.0", SHA)

    assert origin.fetch.call_args.kwargs["refspec"] == "refs/tags/v1.0.0:refs/tags/v1.0.0"
    assert list(tmp_path.iterdir()) == []


@patch("appstore_api.services.git_service.git.Repo")
def test_clone_of_an_unreadable_repository_raises_and_cleans_up(mock_repo_cls, tmp_path, monkeypatch):
    repo = _make_repo_mock()
    mock_repo_cls.init.return_value = repo
    repo.create_remote.return_value.fetch.side_effect = _git_error("fatal: could not read Username")

    with pytest.raises(git.GitCommandError):
        _service(tmp_path, monkeypatch).clone_release_vars("https://github.com/acme/private.git", "v1", SHA)

    assert list(tmp_path.iterdir()) == []


@patch("appstore_api.services.git_service.git.Repo")
def test_concurrent_clones_of_one_version_get_their_own_directory(mock_repo_cls, tmp_path, monkeypatch):
    repo = _make_repo_mock()
    repo.head.commit.hexsha = SHA
    mock_repo_cls.init.return_value = repo
    svc = _service(tmp_path, monkeypatch)

    first = svc.clone_release_vars("https://github.com/acme/widgets.git", "v1", SHA)
    second = svc.clone_release_vars("https://github.com/acme/widgets.git", "v1", SHA)

    assert first != second


# ----------------------------------------------------------------
# Anonymous access via ls-remote
# ----------------------------------------------------------------
LS_REMOTE = "\n".join([
    "1111111111111111111111111111111111111111\trefs/tags/v1.0.0",
    # Annotated tag: the tag object, then the commit it peels to.
    "2222222222222222222222222222222222222222\trefs/tags/v1.10.0",
    "3333333333333333333333333333333333333333\trefs/tags/v1.10.0^{}",
    "4444444444444444444444444444444444444444\trefs/tags/v1.2.0",
    "5555555555555555555555555555555555555555\trefs/tags/latest-draft",
])


@patch("appstore_api.services.git_service.git.cmd.Git")
def test_versions_come_from_ls_remote_newest_first(mock_git, tmp_path, monkeypatch):
    mock_git.return_value.ls_remote.return_value = LS_REMOTE
    svc = _service(tmp_path, monkeypatch)

    versions = svc.get_versions("git@github.com:acme/widgets.git")

    assert [v["version"] for v in versions] == ["v1.10.0", "v1.2.0", "v1.0.0", "latest-draft"]
    # The peeled commit, not the tag object, is what gets deployed.
    assert versions[0]["commit"] == "33333333"
    args = mock_git.return_value.ls_remote.call_args.args
    assert args == ("--tags", "https://github.com/acme/widgets.git")


@patch("appstore_api.services.git_service.git.cmd.Git")
def test_verify_accepts_a_readable_repository(mock_git, tmp_path, monkeypatch):
    mock_git.return_value.ls_remote.return_value = ""
    svc = _service(tmp_path, monkeypatch)

    assert svc.verify_repository_access("https://github.com/acme/public")["success"] is True


@patch("appstore_api.services.git_service.git.cmd.Git")
def test_verify_rejects_an_unreadable_repository(mock_git, tmp_path, monkeypatch):
    mock_git.return_value.ls_remote.side_effect = git.GitCommandError(
        "ls-remote", 128, stderr="fatal: could not read Username"
    )
    svc = _service(tmp_path, monkeypatch)

    result = svc.verify_repository_access("https://github.com/acme/private")

    assert result["success"] is False
    assert "public" in result["message"]
