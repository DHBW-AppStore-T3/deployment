"""Clone app repositories for a job.

Apps come from public repositories and are cloned anonymously over HTTPS
(plan D6): the worker holds no Git credentials at all, so a job cannot leak
one either. Only hosts in ``APP_GIT_ALLOWED_HOSTS`` are fetched from.

A job gets exactly the commit that was approved and deployed (its SHA), not
whatever the tag points to today: a moved tag must neither sneak unreviewed
code into a deploy nor make destroy run different code than the apply did.
"""

import logging
import shutil
from pathlib import Path

import git

from appstore_shared.git_urls import checked_https_url, parse_allowed_hosts

from ..config import settings

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 300


class GitService:
    """Service for anonymous Git clones."""

    def __init__(self) -> None:
        self.base_path = Path(settings.TEMP_REPO_BASE_PATH)

    def clone_release(self, git_url: str, tag: str, deployment_id: str, commit_sha: str) -> str:
        """Check out ``commit_sha`` of the repository into the job directory.

        Fetches the commit itself (GitHub, GitLab and Forgejo serve any
        reachable commit); a server that refuses gets the tag fetched instead,
        which then has to point at ``commit_sha``. Returns the path.
        """
        repo_path = self.base_path / f"deploy_{deployment_id}"
        if repo_path.exists():
            logger.info(f"Removing existing repo at {repo_path}")
            shutil.rmtree(repo_path)

        try:
            url = checked_https_url(git_url, parse_allowed_hosts(settings.APP_GIT_ALLOWED_HOSTS))
            logger.info(f"Fetching {url} at {tag} ({commit_sha[:8]})")
            repo = git.Repo.init(repo_path)
            origin = repo.create_remote("origin", url)
            try:
                origin.fetch(commit_sha, depth=1, kill_after_timeout=FETCH_TIMEOUT_SECONDS)
            except git.GitCommandError:
                logger.info("fetching the commit was refused; fetching tag %s instead", tag)
                origin.fetch(f"refs/tags/{tag}:refs/tags/{tag}", depth=1, kill_after_timeout=FETCH_TIMEOUT_SECONDS)
            try:
                repo.git.checkout("--detach", commit_sha)
            except git.GitCommandError as e:
                raise Exception(
                    f"Tag {tag} no longer points to the deployed commit {commit_sha[:8]}, "
                    "and the server does not serve that commit directly"
                ) from e
            if repo.head.commit.hexsha != commit_sha:
                raise Exception(f"checked out {repo.head.commit.hexsha[:8]} instead of {commit_sha[:8]}")
            return str(repo_path)

        except git.GitCommandError as e:
            error_msg = f"Git command failed: {e.stderr if hasattr(e, 'stderr') else str(e)}"
            logger.error(error_msg)
            if repo_path.exists():
                shutil.rmtree(repo_path)
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Failed to clone release {tag} from {git_url}: {str(e)}"
            logger.error(error_msg)
            if repo_path.exists():
                shutil.rmtree(repo_path)
            raise Exception(error_msg)

    def cleanup_repository(self, repo_path: str) -> None:
        """Delete the cloned repository."""
        path = Path(repo_path)
        if path.exists():
            logger.info(f"Cleaning up {repo_path}")
            shutil.rmtree(path)


# Singleton
git_service = GitService()
