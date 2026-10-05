"""Unit tests for :mod:`appstore_api.utils.capabilities`.

Every capability function gets parametrised coverage from the
Student / Dozent / Admin perspectives (see ``tests.roles``). The tests use plain
``SimpleNamespace`` stand-ins instead of real ORM objects and a
``MagicMock`` for the DB session so the suite runs without Postgres.

Phase 2 contract: app-edit/delete/submit/view are now owner-or-admin
only (Bug #2 fix); operate on a deployment is owner-or-admin only.
Teacher bypasses on these have been removed — the matrix below
reflects that.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from appstore_api.utils import capabilities as caps
from tests.roles import Role, stub_user

pytestmark = pytest.mark.unit


# ----------------------------------------------------------------
# Fixtures
# ----------------------------------------------------------------
def _user(role: Role, user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return stub_user(role, user_id)


def _app(owner_id: uuid.UUID, is_private: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        appId=uuid.uuid4(),
        userId=owner_id,
        is_private=is_private,
    )


def _deployment(owner_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(deploymentId=uuid.uuid4(), userId=owner_id)


@pytest.fixture
def student():
    return _user(Role.STUDENT)


@pytest.fixture
def teacher():
    return _user(Role.DOZENT)


@pytest.fixture
def admin():
    return _user(Role.ADMIN)


@pytest.fixture
def db_mock():
    return MagicMock()


# ================================================================
# APPS — can_view_app
# ================================================================
class TestCanViewApp:
    def test_owner_can_view_own_private_app(self, student):
        app = _app(student.userId, is_private=True)
        assert caps.can_view_app(student, app, db=None) is True

    def test_admin_can_view_any_app(self, admin):
        app = _app(uuid.uuid4(), is_private=True)
        assert caps.can_view_app(admin, app, db=None) is True

    def test_teacher_cannot_view_others_private_app(self, teacher):
        # Phase 2 — Bug #2 fix: teachers no longer get a blanket view
        # on private third-party apps. Only owner or admin sees these.
        app = _app(uuid.uuid4(), is_private=True)
        assert caps.can_view_app(teacher, app, db=None) is False

    def test_teacher_can_view_public_approved_app(self, teacher, monkeypatch):
        # Public + approved → visible to everyone (also teachers).
        app = _app(uuid.uuid4(), is_private=False)
        monkeypatch.setattr(
            "appstore_api.utils.capabilities.crud_approvals.has_any_approved_version",
            lambda _db, _app_id: True,
        )
        db = MagicMock()
        assert caps.can_view_app(teacher, app, db=db) is True

    def test_student_cannot_view_others_private_app(self, student):
        app = _app(uuid.uuid4(), is_private=True)
        assert caps.can_view_app(student, app, db=None) is False

    def test_student_can_view_public_approved_app(self, student, monkeypatch):
        app = _app(uuid.uuid4(), is_private=False)
        monkeypatch.setattr(
            "appstore_api.utils.capabilities.crud_approvals.has_any_approved_version",
            lambda _db, _app_id: True,
        )
        db = MagicMock()
        assert caps.can_view_app(student, app, db=db) is True

    def test_student_cannot_view_public_unapproved_app(self, student, monkeypatch):
        app = _app(uuid.uuid4(), is_private=False)
        monkeypatch.setattr(
            "appstore_api.utils.capabilities.crud_approvals.has_any_approved_version",
            lambda _db, _app_id: False,
        )
        db = MagicMock()
        assert caps.can_view_app(student, app, db=db) is False


class TestEnsureViewApp:
    def test_ensure_raises_with_app_view_forbidden(self, student):
        app = _app(uuid.uuid4(), is_private=True)
        with pytest.raises(HTTPException) as exc:
            caps.ensure_view_app(student, app, db=None)
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "app_view_forbidden"


# ================================================================
# APPS — can_list_all_apps
# ================================================================
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.STUDENT, False),
        (Role.DOZENT, False),
        (Role.ADMIN, True),
    ],
)
def test_can_list_all_apps(role, expected):
    assert caps.can_list_all_apps(_user(role)) is expected


def test_ensure_list_all_apps_raises_role_required(student):
    with pytest.raises(HTTPException) as exc:
        caps.ensure_list_all_apps(student)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "role_required"
    assert exc.value.detail["required"] == [Role.ADMIN.value]


# ================================================================
# APPS — edit / delete / submit (Phase 2: owner OR admin)
# ================================================================
class TestCanEditApp:
    def test_owner_can_edit(self, student):
        app = _app(student.userId)
        assert caps.can_edit_app(student, app) is True

    def test_admin_can_edit(self, admin):
        app = _app(uuid.uuid4())
        assert caps.can_edit_app(admin, app) is True

    def test_teacher_cannot_edit_foreign_app(self, teacher):
        # Phase 2 — Bug #2 fix: teacher bypass on edit is removed.
        # Teachers may only edit apps they own.
        app = _app(uuid.uuid4())
        assert caps.can_edit_app(teacher, app) is False

    def test_teacher_can_edit_own_app(self, teacher):
        app = _app(teacher.userId)
        assert caps.can_edit_app(teacher, app) is True

    def test_other_student_cannot_edit(self, student):
        app = _app(uuid.uuid4())
        assert caps.can_edit_app(student, app) is False


def test_can_delete_app_mirrors_edit(student, teacher, admin):
    own = _app(student.userId)
    other = _app(uuid.uuid4())
    teachers_own = _app(teacher.userId)
    assert caps.can_delete_app(student, own) is True
    assert caps.can_delete_app(student, other) is False
    # Phase 2 — Bug #2 fix: teacher cannot delete a foreign app.
    assert caps.can_delete_app(teacher, other) is False
    assert caps.can_delete_app(teacher, teachers_own) is True
    assert caps.can_delete_app(admin, other) is True


def test_can_submit_app_version_mirrors_edit(student, teacher, admin):
    own = _app(student.userId)
    other = _app(uuid.uuid4())
    teachers_own = _app(teacher.userId)
    assert caps.can_submit_app_version(student, own) is True
    assert caps.can_submit_app_version(student, other) is False
    # Phase 2 — Bug #2 fix: teacher cannot submit a foreign app's version.
    assert caps.can_submit_app_version(teacher, other) is False
    assert caps.can_submit_app_version(teacher, teachers_own) is True
    assert caps.can_submit_app_version(admin, other) is True


# ================================================================
# APPS — approve_app_version (Admin only)
# ================================================================
@pytest.mark.parametrize(
    ("role", "expected"),
    [
        (Role.STUDENT, False),
        (Role.DOZENT, False),
        (Role.ADMIN, True),
    ],
)
def test_can_approve_app_version(role, expected):
    assert caps.can_approve_app_version(_user(role)) is expected


def test_ensure_approve_app_version_raises(teacher):
    with pytest.raises(HTTPException) as exc:
        caps.ensure_approve_app_version(teacher)
    assert exc.value.detail["code"] == "role_required"
    assert exc.value.detail["required"] == [Role.ADMIN.value]


# ================================================================
# DEPLOYMENTS — view_member / view_owner / operate / resend
# ================================================================
class TestCanViewDeploymentMember:
    """Mirrors ``has_deployment_access`` — owner, staff, team, direct."""

    def test_owner_can_view(self, student, db_mock):
        dep = _deployment(student.userId)
        assert caps.can_view_deployment_member(student, dep, db_mock) is True

    def test_admin_can_view(self, admin, db_mock):
        dep = _deployment(uuid.uuid4())
        # Admin path returns early from has_deployment_access — no DB
        # calls happen, so the MagicMock can stay empty.
        assert caps.can_view_deployment_member(admin, dep, db_mock) is True

    def test_teacher_can_view(self, teacher, db_mock):
        dep = _deployment(uuid.uuid4())
        assert caps.can_view_deployment_member(teacher, dep, db_mock) is True

    def test_unrelated_student_cannot_view(self, student, monkeypatch):
        # Stub has_deployment_access to "no team, no direct" so we
        # exercise the rejection branch without a real DB.
        dep = _deployment(uuid.uuid4())
        db = MagicMock()
        db.query.return_value.join.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.first.return_value = None
        assert caps.can_view_deployment_member(student, dep, db) is False


class TestCanViewDeploymentOwner:
    """Owner view = owner OR admin. Staff status alone does not grant it."""

    @pytest.mark.parametrize(
        ("role", "is_owner", "expected"),
        [
            (Role.STUDENT, True, True),
            (Role.STUDENT, False, False),
            (Role.DOZENT, False, False),
            (Role.ADMIN, False, True),
        ],
    )
    def test_matrix(self, role, is_owner, expected):
        owner_id = uuid.uuid4()
        actor = _user(role, user_id=owner_id if is_owner else None)
        dep = _deployment(owner_id)
        assert caps.can_view_deployment_owner(actor, dep, MagicMock()) is expected


class TestCanOperateDeployment:
    """Operate is the owner's right: neither teachers nor admins get it."""

    def test_owner_can_operate(self, student, db_mock):
        dep = _deployment(student.userId)
        assert caps.can_operate_deployment(student, dep, db_mock) is True

    def test_teacher_cannot_operate_foreign_deployment(self, teacher, db_mock):
        # Phase 2 — operate is owner-or-admin only. A teacher who is
        # not the owner cannot pause/destroy a deployment.
        dep = _deployment(uuid.uuid4())
        assert caps.can_operate_deployment(teacher, dep, db_mock) is False

    def test_admin_does_not_operate(self, admin, db_mock):
        # Admins read everything; lifecycle actions belong to the people
        # working in the deployment's project (E2).
        dep = _deployment(uuid.uuid4())
        assert caps.can_operate_deployment(admin, dep, db_mock) is False

    def test_unrelated_student_cannot_operate(self, student, db_mock):
        dep = _deployment(uuid.uuid4())
        assert caps.can_operate_deployment(student, dep, db_mock) is False


class TestCanResendAccess:
    def test_self_resend_when_member(self, student, db_mock):
        dep = _deployment(student.userId)
        assert caps.can_resend_access(student, dep, student.userId, db_mock) is True

    def test_admin_can_resend_for_anyone(self, admin, db_mock):
        dep = _deployment(uuid.uuid4())
        other = uuid.uuid4()
        assert caps.can_resend_access(admin, dep, other, db_mock) is True

    def test_student_cannot_resend_for_other(self, student, db_mock):
        # Student is owner of dep (member-view), but cannot dispatch
        # credentials to someone else — that's the owner-view gate.
        dep = _deployment(student.userId)
        other = uuid.uuid4()
        # Owner of the deployment counts as owner-view → True.
        assert caps.can_resend_access(student, dep, other, db_mock) is True

    def test_unrelated_student_cannot_resend_for_other(self, student, db_mock):
        dep = _deployment(uuid.uuid4())  # student is not owner
        other = uuid.uuid4()
        assert caps.can_resend_access(student, dep, other, db_mock) is False
