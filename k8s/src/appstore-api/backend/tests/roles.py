"""Test-only shorthand for the three kinds of caller the rules distinguish.

Production code has no role enum: rights come from tokens (see
``appstore_api.auth``). Tests still want to say "a student", "a dozent", "an
admin", so this maps each to the token-derived flags a signed-in user carries.
"""

from __future__ import annotations

import uuid
from enum import Enum
from types import SimpleNamespace

from appstore_api.models import User

# The course of the mock role provider (``ROLE_PROVIDER=mock``): a dozent here
# teaches it, and its ``#studierende`` are the people teams may be built from.
COURSE = "group:wwi23seb"


class Role(str, Enum):
    STUDENT = "student"
    DOZENT = "dozent"
    ADMIN = "admin"


def tokens_for(role: Role, email: str | None) -> frozenset[str]:
    tokens = {f"user:{email}"} if email else set()
    if role == Role.DOZENT:
        tokens |= {COURSE, f"{COURSE}#dozent"}
    if role == Role.ADMIN:
        tokens.add("group:appstore_admins")
    return frozenset(tokens)


def apply_role(user, role: Role):
    """Give ``user`` what ``auth.get_current_user`` would set for ``role``."""
    user.is_admin = role == Role.ADMIN
    user.is_dozent = role == Role.DOZENT
    user.tokens = tokens_for(role, getattr(user, "email", None))
    return user


def make_user(role: Role = Role.STUDENT, **fields) -> User:
    """An unsaved ``User`` row carrying the rights of ``role``."""
    return apply_role(User(**fields), role)


def stub_user(role: Role = Role.STUDENT, user_id=None) -> SimpleNamespace:
    """A DB-less stand-in for unit tests of the rules."""
    return SimpleNamespace(
        userId=user_id or uuid.uuid4(),
        is_admin=role == Role.ADMIN,
        is_dozent=role == Role.DOZENT,
        tokens=tokens_for(role, None),
    )
