"""Who is in which group: role-provider-service (plan D3, AP3/AP4).

The AppStore keeps no groups of its own. It asks role-provider-service for

- a caller's **tokens**, fresh on every request (``user:<email>``,
  ``group:<id>``, ``group:<id>#<relation>``), which is where admin rights
  (``APPSTORE_ADMIN_GROUPS``) and courses (``#dozent``) come from;
- a **course**: its display name, and the members holding a relation
  (``studierende``) for building teams.

Talking to it is the server's job only; the browser never reaches the role
provider (it answers questions about people and has no ingress).

``ROLE_PROVIDER=http`` is the real thing. ``mock`` answers from the same
example identities role-provider-service seeds in development (course
``wwi23seb`` with a ``dozent`` and a ``studierende``) and is refused outside
``API_MODE=development``: it hands out fake group memberships.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol
from urllib.parse import quote

import httpx

from appstore_api.config import settings

logger = logging.getLogger(__name__)


class RoleProviderError(Exception):
    """The role provider could not answer."""


@dataclass(frozen=True)
class Group:
    """A role-provider group (e.g. a course) with its UI labels."""

    token: str
    display_name: str
    description: str


class RoleProvider(Protocol):
    """What the AppStore asks the role provider; implemented by the HTTP client and the mock.

    Every method raises ``RoleProviderError`` when the provider cannot answer.
    """

    def get_user_tokens(self, email: str) -> list[str]:
        """All tokens ``email`` holds (``user:``, ``group:<id>``, ``group:<id>#<relation>``)."""
        ...

    def get_group(self, group_token: str) -> Group | None:
        """The group behind ``group_token``, or None if it does not exist."""
        ...

    def get_member_emails(self, group_token: str, relation: str) -> list[str]:
        """Addresses holding ``relation`` in the group, resolved through nested groups.

        Members that are only covered by a pattern (``*@student.example``)
        cannot be enumerated and are not part of the answer.
        """
        ...


class HttpRoleProvider:
    """Client for role-provider-service's ``/v1`` API, authenticated with a static bearer token.

    One pooled ``httpx.Client`` per process (see ``get_role_provider``).
    Non-200 answers other than the documented 404s raise ``RoleProviderError``.
    """

    def __init__(self, base_url: str, api_token: str, timeout: float) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=timeout,
        )

    def _get(self, path: str, params: dict[str, str] | None = None) -> httpx.Response:
        """GET ``path``; transport errors become ``RoleProviderError``, status codes are left to the caller."""
        try:
            return self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise RoleProviderError(f"role provider unreachable: {e}") from e

    def get_user_tokens(self, email: str) -> list[str]:
        response = self._get(f"/v1/users/{quote(email, safe='')}/tokens")
        if response.status_code != 200:
            raise RoleProviderError(f"token lookup answered {response.status_code}")
        return [str(t) for t in response.json()]

    def get_group(self, group_token: str) -> Group | None:
        response = self._get(f"/v1/groups/{quote(group_token, safe='')}")
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise RoleProviderError(f"group lookup answered {response.status_code}")
        body = response.json()
        return Group(
            token=str(body.get("token") or group_token),
            display_name=str(body.get("display_name") or ""),
            description=str(body.get("description") or ""),
        )

    def get_member_emails(self, group_token: str, relation: str) -> list[str]:
        response = self._get(
            f"/v1/groups/{quote(group_token, safe='')}/members",
            params={"relation": relation, "recursive": "true"},
        )
        # Unknown group: no members. The answer mixes user and group tokens;
        # only ``user:<email>`` entries are addresses, lower-cased to match
        # ``courses.normalise_email``.
        if response.status_code == 404:
            return []
        if response.status_code != 200:
            raise RoleProviderError(f"member lookup answered {response.status_code}")
        return sorted({t[len("user:"):].lower() for t in response.json() if str(t).startswith("user:")})


# The identities role-provider-service seeds with DB_ADD_MOCK_DATA=true, plus
# the relations of its mock course, so the dev setup of the platform and this
# service agree on who is who.
_MOCK_GROUPS = {
    "group:root_uni": Group("group:root_uni", "University Root", "Top-level university group"),
    "group:dept_cs_faculty": Group("group:dept_cs_faculty", "CS Faculty Pool", "CS faculty members"),
    "group:cs-student": Group("group:cs-student", "CS Students", "Computer science students"),
    "group:wwi23seb": Group("group:wwi23seb", "WWI23SEB", "Course with roles (dozent, studierende)"),
}
_MOCK_MEMBERSHIPS: dict[str, list[tuple[str, str]]] = {
    # email -> [(group id, relation)]
    "root.admin@uni.example": [("root_uni", "member")],
    "faculty@cs.example": [("dept_cs_faculty", "member"), ("wwi23seb", "dozent")],
    "cs-student@cs.com": [("cs-student", "member"), ("wwi23seb", "studierende")],
}


class MockRoleProvider:
    """Answers from ``_MOCK_GROUPS``/``_MOCK_MEMBERSHIPS`` (``ROLE_PROVIDER=mock``, development only).

    Unlike the real service it does not resolve nested groups.
    """

    def get_user_tokens(self, email: str) -> list[str]:
        tokens = [f"user:{email}"]
        for group, relation in _MOCK_MEMBERSHIPS.get(email, []):
            tokens.append(f"group:{group}")
            if relation != "member":
                tokens.append(f"group:{group}#{relation}")
        return tokens

    def get_group(self, group_token: str) -> Group | None:
        return _MOCK_GROUPS.get(group_token)

    def get_member_emails(self, group_token: str, relation: str) -> list[str]:
        group = group_token.removeprefix("group:")
        return sorted(
            email
            for email, memberships in _MOCK_MEMBERSHIPS.items()
            if (group, relation) in memberships or (relation == "member" and any(g == group for g, _ in memberships))
        )


@lru_cache(maxsize=1)
def get_role_provider() -> RoleProvider:
    """Return the process-wide provider selected by ``ROLE_PROVIDER`` (created once, cached)."""
    if settings.ROLE_PROVIDER == "mock":
        logger.warning("ROLE_PROVIDER=mock: group memberships are example data")
        return MockRoleProvider()
    return HttpRoleProvider(
        settings.ROLE_PROVIDER_URL, settings.ROLE_PROVIDER_API_TOKEN, settings.ROLE_PROVIDER_TIMEOUT_SECONDS
    )
