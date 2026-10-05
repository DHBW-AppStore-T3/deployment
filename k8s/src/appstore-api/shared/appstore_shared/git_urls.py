"""Git URL handling shared by the API (listing versions) and the worker (cloning).

Apps are read anonymously from public repositories (plan D6), so both sides
must turn whatever the app author registered into the same credential-free
HTTPS URL, and both refuse hosts outside ``APP_GIT_ALLOWED_HOSTS``: the URL is
user input, and without the allowlist the API and the worker would fetch from
wherever it points, internal addresses included.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# owner/repo(.git), possibly nested groups (GitLab); no option-like or
# traversal segments, since the URL ends up as an argument to git.
_PATH_RE = re.compile(r"^[A-Za-z0-9_.~-]+(/[A-Za-z0-9_.~-]+)+/?$")
_HOST_RE = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?$")


class GitHostNotAllowed(ValueError):
    """The repository URL is malformed or points outside the allowlist."""


def to_https_url(git_url: str) -> str:
    """Normalise ``git@host:owner/repo`` and ``http(s)://…`` to plain ``https://``.

    Any credentials embedded in the URL are dropped: nothing is ever cloned
    with a token, so a user-supplied one must not be passed on either.
    """
    url = git_url.strip()
    if url.startswith("git@"):
        url = url[len("git@"):].replace(":", "/", 1)
    url = re.sub(r"^https?://", "", url)
    host_and_path = url.split("/", 1)
    if "@" in host_and_path[0]:
        host_and_path[0] = host_and_path[0].rsplit("@", 1)[1]
    return "https://" + "/".join(host_and_path)


def parse_allowed_hosts(value: str) -> frozenset[str]:
    """``APP_GIT_ALLOWED_HOSTS`` (comma-separated) as a set of lower-case hosts."""
    return frozenset(h.strip().lower() for h in value.split(",") if h.strip())


def checked_https_url(git_url: str, allowed_hosts: Iterable[str]) -> str:
    """:func:`to_https_url`, refusing anything but an allowed host and a plain path."""
    url = to_https_url(git_url)
    host, _, path = url[len("https://"):].partition("/")
    host = host.lower()
    if not _HOST_RE.match(host) or ".." in path or not _PATH_RE.match(path):
        raise GitHostNotAllowed(f"not a repository URL: {git_url!r}")
    if host not in set(allowed_hosts):
        raise GitHostNotAllowed(f"Git host {host!r} is not allowed")
    return f"https://{host}/{path}"


__all__ = ["GitHostNotAllowed", "to_https_url", "parse_allowed_hosts", "checked_https_url"]
