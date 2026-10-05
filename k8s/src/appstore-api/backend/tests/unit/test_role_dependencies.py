"""The role dependencies in utils/capabilities."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from appstore_api.utils.capabilities import require_admin, require_dozent
from tests.roles import Role, stub_user


def test_require_admin_allows_admin():
    admin = stub_user(Role.ADMIN)
    assert require_admin(user=admin) is admin


@pytest.mark.parametrize("role", [Role.STUDENT, Role.DOZENT])
def test_require_admin_denies_everyone_else(role):
    with pytest.raises(HTTPException) as exc:
        require_admin(user=stub_user(role))
    assert exc.value.status_code == 403
    assert exc.value.detail == {"code": "role_required", "required": ["admin"]}


def test_require_dozent_allows_teachers():
    dozent = stub_user(Role.DOZENT)
    assert require_dozent(user=dozent) is dozent


@pytest.mark.parametrize("role", [Role.STUDENT, Role.ADMIN])
def test_require_dozent_denies_everyone_else(role):
    # Admin rights are about reviewing and reading, not teaching a course.
    with pytest.raises(HTTPException) as exc:
        require_dozent(user=stub_user(role))
    assert exc.value.detail == {"code": "role_required", "required": ["dozent"]}
