"""Read app repositories: list their versions and fetch the files the wizard needs.

Apps come from public repositories only and are read anonymously over HTTPS
(plan D6). Everything goes through the git protocol rather than a hosting
provider's REST API: ``git ls-remote`` works the same on GitHub, GitLab and
Forgejo, needs no token, and is not subject to GitHub's 60-requests-per-hour
limit for anonymous API calls — which a catalogue page would hit quickly.

A version is a tag, and what gets approved and deployed is the commit the
tag points to (its SHA), never the tag name alone: tags can be moved, and an
approval must not silently carry over to code nobody reviewed. Release notes
that live only on the hosting provider are not shown; the README in the
repository is the description.

Every URL passes the host allowlist (``APP_GIT_ALLOWED_HOSTS``) first.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import git

from appstore_shared.git_urls import checked_https_url

from ..config import settings

logger = logging.getLogger(__name__)

# Bounded so a hanging remote cannot block a request worker indefinitely.
LS_REMOTE_TIMEOUT_SECONDS = 20
FETCH_TIMEOUT_SECONDS = 60


class CommitNotServed(Exception):
    """The pinned commit cannot be fetched: the server refuses fetching by SHA
    and ``tag`` no longer points to it."""

    def __init__(self, tag: str, commit_sha: str) -> None:
        super().__init__(f"tag {tag} no longer points to {commit_sha[:8]}, which the server does not serve directly")
        self.tag = tag
        self.commit_sha = commit_sha


def _url(git_url: str) -> str:
    """The HTTPS URL to fetch from. Raises GitHostNotAllowed."""
    return checked_https_url(git_url, settings.git_allowed_hosts)


def _version_sort_key(v: dict[str, Any]) -> tuple:
    """Newest first for ``vX.Y.Z`` tags; anything else sorts after, by name."""
    try:
        return (1, tuple(map(int, v["version"].lstrip("v").split("."))))
    except (ValueError, AttributeError):
        return (0, v["version"])


class GitService:
    """Git operations on app repositories: tag listing, tag resolution and
    sparse clones for the variable scan.

    Stateless apart from ``TEMP_REPO_BASE_PATH``, the directory sparse
    clones are written to; use the module-level ``git_service`` singleton.
    """

    # Sparse-checkout allowlist for the variable scan (non-cone mode,
    # ``.gitignore`` pathspecs). ``packer/`` matches the whole subtree so
    # both the flat layout (``packer/variables.pkr.hcl``) and per-template
    # layout (``packer/<key>/variables.pkr.hcl``) plus the
    # ``template.pkr.hcl`` files are fetched. ``terraform/variables.tf``
    # is a single file since only the variables file is needed.
    SPARSE_CHECKOUT_FILES = [
        'terraform/variables.tf',
        'packer/',
    ]

    def __init__(self) -> None:
        self.base_path = Path(settings.TEMP_REPO_BASE_PATH)

    def _ls_remote_tags(self, git_url: str) -> list[dict[str, Any]]:
        """List the repository's tags with the commit each one points to.

        Each entry is ``{"version": tag, "commit": short SHA, "sha": full
        SHA, "type": "tag"}``. Raises GitHostNotAllowed for a URL outside
        the allowlist and git.GitCommandError if the remote cannot be read.

        Annotated tags are listed twice by ls-remote: the tag object, and
        ``<tag>^{}`` for the commit it peels to. The peeled line wins, because
        the commit is what gets deployed.
        """
        out = str(
            git.cmd.Git().ls_remote(
                "--tags", _url(git_url), kill_after_timeout=LS_REMOTE_TIMEOUT_SECONDS
            )
        )
        commits: dict[str, str] = {}
        for line in out.splitlines():
            sha, _, ref = line.partition("\t")
            if not ref.startswith("refs/tags/"):
                continue
            name = ref[len("refs/tags/"):]
            if name.endswith("^{}"):
                commits[name[:-3]] = sha
            else:
                commits.setdefault(name, sha)
        return [
            {"version": name, "commit": sha[:8], "sha": sha, "type": "tag"}
            for name, sha in commits.items()
        ]

    def resolve_tag(self, git_url: str, tag: str) -> str | None:
        """Return the full SHA of the commit ``tag`` points to now, or None if there is no such tag."""
        for v in self._ls_remote_tags(git_url):
            if v["version"] == tag:
                return str(v["sha"])
        return None

    def verify_repository_access(self, git_url: str) -> dict[str, Any]:
        """Check that the repository can be read anonymously.

        Returns a dict with ``success`` and a ``message`` for the user; a
        git failure becomes ``success=False``. GitHostNotAllowed is not
        caught and propagates to the caller.
        """
        try:
            self._ls_remote_tags(git_url)
        except git.GitCommandError as e:
            logger.info("repository %s is not readable: %s", git_url, e.stderr.strip())
            return {
                'success': False,
                'message': (
                    f"Repository {_url(git_url)} cannot be read. Apps must be "
                    "in a public Git repository reachable over HTTPS."
                ),
            }
        return {'success': True, 'message': "Repository access verified successfully"}

    def clone_release_vars(self, git_url: str, tag: str, commit_sha: str) -> str:
        """Sparse-clone ``commit_sha`` (only ``SPARSE_CHECKOUT_FILES``) and return the local path.

        Reads the commit that is reviewed or deployed, not whatever ``tag``
        points to now. Like the worker, it fetches the commit itself (GitHub,
        GitLab and Forgejo serve any reachable commit); a server that
        refuses gets the tag fetched instead, which must then point at
        ``commit_sha`` (else ``CommitNotServed``). Each call clones into a
        fresh directory under ``TEMP_REPO_BASE_PATH``, so concurrent reads
        of the same version cannot delete each other's clone. The caller
        removes it with ``cleanup_repository``. ``git.GitCommandError``
        (repository unreadable) propagates; the partial clone is removed.
        """
        self.base_path.mkdir(parents=True, exist_ok=True)
        repo_path = Path(tempfile.mkdtemp(prefix="vars_", dir=self.base_path))
        try:
            logger.info("Fetching %s at %s (%s, sparse)", git_url, tag, commit_sha[:8])
            repo = git.Repo.init(repo_path)
            origin = repo.create_remote('origin', _url(git_url))

            git_dir = repo_path / '.git'
            sparse_file = git_dir / 'info' / 'sparse-checkout'
            sparse_file.parent.mkdir(parents=True, exist_ok=True)
            sparse_file.write_text('\n'.join(self.SPARSE_CHECKOUT_FILES) + '\n')
            with (git_dir / 'config').open('a') as f:
                f.write('[core]\n\tsparseCheckout = true\n')

            try:
                origin.fetch(commit_sha, depth=1, kill_after_timeout=FETCH_TIMEOUT_SECONDS)
            except git.GitCommandError:
                logger.info("fetching the commit was refused; fetching tag %s instead", tag)
                origin.fetch(
                    refspec=f'refs/tags/{tag}:refs/tags/{tag}', depth=1,
                    kill_after_timeout=FETCH_TIMEOUT_SECONDS,
                )
            try:
                repo.git.checkout('--detach', commit_sha, force=True)
            except git.GitCommandError as e:
                raise CommitNotServed(tag, commit_sha) from e
            if repo.head.commit.hexsha != commit_sha:
                raise CommitNotServed(tag, commit_sha)
            return str(repo_path)
        except BaseException:
            shutil.rmtree(repo_path, ignore_errors=True)
            raise

    def get_versions(self, git_url: str) -> list[dict[str, Any]]:
        """List all tags of the repository, newest ``vX.Y.Z`` first.

        Entries have the shape described in ``_ls_remote_tags``. Raises a
        plain Exception carrying git's stderr if the remote cannot be read.
        """
        try:
            versions = self._ls_remote_tags(git_url)
        except git.GitCommandError as e:
            logger.error("Failed to list tags of %s: %s", git_url, e.stderr.strip())
            raise Exception(f"Failed to fetch versions: {e.stderr.strip()}") from e
        versions.sort(key=_version_sort_key, reverse=True)
        logger.info(f"Found {len(versions)} versions")
        return versions

    def cleanup_repository(self, repo_path: str) -> None:
        """Delete a clone made by ``clone_release_vars``; no-op if it is gone."""
        path = Path(repo_path)
        if path.exists():
            logger.info(f"Cleaning up {repo_path}")
            shutil.rmtree(path)


# Singleton instance
git_service = GitService()
