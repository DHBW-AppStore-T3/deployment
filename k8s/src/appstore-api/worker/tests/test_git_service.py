"""Tests for Git service."""

import importlib
from pathlib import Path
from unittest.mock import patch

import git
import pytest

from appstore_worker.services.git_service import GitService

# The package re-exports the singleton under the module's name.
git_service_mod = importlib.import_module("appstore_worker.services.git_service")


@pytest.fixture
def git_service(tmp_path):
    """Create GitService instance with temporary base path."""
    with patch("appstore_worker.services.git_service.settings") as mock_settings:
        mock_settings.TEMP_REPO_BASE_PATH = str(tmp_path)
        mock_settings.APP_GIT_ALLOWED_HOSTS = "github.com"
        service = GitService()
    # clone_release reads the allowlist at call time, from the real settings.
    return service


def _repo_with_moved_tag(path):
    """A repository whose tag v1 was moved: returns (url, first_sha, second_sha)."""
    repo = git.Repo.init(path)
    repo.config_writer().set_value("user", "email", "t@example.org").release()
    repo.config_writer().set_value("user", "name", "t").release()
    (path / "main.tf").write_text("# one\n")
    repo.index.add(["main.tf"])
    first = repo.index.commit("one").hexsha
    repo.create_tag("v1")
    (path / "main.tf").write_text("# two\n")
    repo.index.add(["main.tf"])
    second = repo.index.commit("two").hexsha
    repo.create_tag("v1", force=True)
    return f"file://{path}", first, second


@pytest.fixture
def local_remote(tmp_path, monkeypatch):
    """Serve a local repository as if it were an allowed HTTPS remote."""
    url, first, second = _repo_with_moved_tag(tmp_path / "remote")
    monkeypatch.setattr(git_service_mod, "checked_https_url", lambda *_: url)
    return first, second


class TestGitServiceCloning:
    """Jobs check out the deployed commit, not whatever the tag says today."""

    def test_checks_out_the_pinned_commit_although_the_tag_moved(self, git_service, local_remote):
        first, _ = local_remote

        path = git_service.clone_release("https://github.com/o/r", "v1", "dep-1", first)

        assert git.Repo(path).head.commit.hexsha == first
        assert (Path(path) / "main.tf").read_text() == "# one\n"

    def test_falls_back_to_the_tag_when_the_server_refuses_commits(self, git_service, local_remote, monkeypatch):
        _, second = local_remote
        real_fetch = git.Remote.fetch

        def refuse_shas(self, refspec=None, **kwargs):
            if refspec and not str(refspec).startswith("refs/"):
                raise git.GitCommandError("fetch", 128, stderr="not our ref")
            return real_fetch(self, refspec, **kwargs)

        monkeypatch.setattr(git.Remote, "fetch", refuse_shas)

        path = git_service.clone_release("https://github.com/o/r", "v1", "dep-2", second)

        assert git.Repo(path).head.commit.hexsha == second

    def test_a_moved_tag_without_commit_access_fails_and_cleans_up(self, git_service, local_remote, monkeypatch, tmp_path):
        first, _ = local_remote
        real_fetch = git.Remote.fetch

        def refuse_shas(self, refspec=None, **kwargs):
            if refspec and not str(refspec).startswith("refs/"):
                raise git.GitCommandError("fetch", 128, stderr="not our ref")
            return real_fetch(self, refspec, **kwargs)

        monkeypatch.setattr(git.Remote, "fetch", refuse_shas)

        with pytest.raises(Exception, match="no longer points to the deployed commit"):
            git_service.clone_release("https://github.com/o/r", "v1", "dep-3", first)
        assert not (tmp_path / "deploy_dep-3").exists()

    def test_hosts_outside_the_allowlist_are_not_fetched(self, git_service, tmp_path):
        with patch.object(git.Repo, "init") as init, pytest.raises(Exception, match="not allowed"):
            git_service.clone_release("https://evil.example/o/r", "v1", "dep-4", "c" * 40)
        init.assert_not_called()


class TestGitServiceCleanup:
    """Test repository cleanup functionality."""

    def test_cleanup_existing_directory(self, git_service, tmp_path):
        """Test cleanup of existing directory."""
        test_dir = tmp_path / "test_cleanup"
        test_dir.mkdir(parents=True)
        (test_dir / "test_file.txt").write_text("test content")

        assert test_dir.exists()

        git_service.cleanup_repository(str(test_dir))

        assert not test_dir.exists()

    def test_cleanup_nonexistent_directory(self, git_service, tmp_path):
        """Test cleanup handles nonexistent directory gracefully."""
        nonexistent = tmp_path / "does_not_exist"

        # Should not raise an exception
        git_service.cleanup_repository(str(nonexistent))

        assert not nonexistent.exists()


@pytest.mark.integration
class TestGitServiceIntegration:
    """Integration tests (require actual Git access)."""

    @pytest.mark.skip(reason="Requires actual Git repository access")
    def test_clone_real_repository(self, git_service):
        """Test cloning a real public repository."""
        # This test would require a real public repository
        # Skip by default to avoid external dependencies
        pass
