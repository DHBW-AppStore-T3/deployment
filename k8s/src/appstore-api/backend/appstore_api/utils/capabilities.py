"""Who may do what: the one place for access rules (plan D3, E2, E6).

Rights come from the caller's tokens, set per request by ``auth.py``
(``user.is_admin`` from ``APPSTORE_ADMIN_GROUPS``, ``user.is_dozent`` from any
``group:<course>#dozent``). Routers call a ``require_*`` dependency or an
``ensure_*`` helper from here and never test tokens or owner ids themselves.

The rules:

- **Admin** reads everything and reviews app versions. Admin is not an
  operator: lifecycle actions run with the caller's own OpenStack credential,
  so they belong to the people working in the deployment's project.
- **Registering apps** takes at least one ``#dozent`` token (or admin).
- **Deploying** takes a ``#dozent`` token, and the deployment's course must be
  one the caller teaches (``group:<course>#dozent``). The credential a deploy
  may use is checked where the deploy is built.
- **Courses** a caller may pick are exactly those they teach; so is the
  student list of a course (plan AP4).
- **A deployment** is seen and run by its owner and by everyone holding an
  own credential for the same OpenStack project ("project peers", E2): the
  credential was scoped to the project by Keystone, which proves access to
  it. Actions always run with the caller's own credential. Team members see
  the deployment and their own team and access (member view). Nobody else,
  and in particular not every teacher: the original's "staff sees all" is
  gone.

Summary of who may do what (anything not listed is refused with 403):

====================================  =========================================
Action                                Allowed for
====================================  =========================================
register an app                       dozent (any course) or admin
see an app                            owner, admin; anyone if public and at
                                      least one version is approved
edit / delete / submit a version      app owner or admin
approve / reject / revoke a version   admin
start a deployment                    dozent of the chosen course
list a course's students              dozent of that course
deployment, owner view (tasks, logs,  deployment owner, project peer, admin
all teams, outputs)
deployment, member view               owner view + members of its teams
pause/resume/destroy/redeploy/teams   deployment owner, project peer (not admin)
resend an access mail                 to oneself: member view; to others:
                                      owner view
====================================  =========================================

Conventions: ``can_<verb>_<resource>(...) -> bool`` never raises;
``ensure_<verb>_<resource>(...)`` raises 403 with ``{"code": ..., "required": [...]}``
so the frontend can tell which right is missing.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.auth import DOZENT_SUFFIX, get_current_user
from appstore_api.crud import app_version_approvals as crud_approvals
from appstore_api.crud import openstack_credentials as crud_creds
from appstore_api.models import App, Deployment, Team, User, UserToDeployment, UserToTeam

# Names used in 403 payloads, so the frontend can say which right is missing.
ADMIN = "admin"
DOZENT = "dozent"


# ----------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------
def _is_admin(user: User) -> bool:
    """``user.is_admin`` as set by ``auth.get_current_user`` for this request."""
    return user.is_admin


def _is_owner(user: User, owner_id) -> bool:
    """Whether ``owner_id`` (UUID or string) is the caller's user id."""
    return str(owner_id) == str(user.userId)


def _forbidden(code: str, required: list[str] | None = None) -> HTTPException:
    """A 403 with ``{"code": code, "required": [...]}`` as detail."""
    detail: dict = {"code": code}
    if required is not None:
        detail["required"] = required
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ================================================================
# ROLE DEPENDENCIES
# ================================================================
def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency: the caller holds a token from ``APPSTORE_ADMIN_GROUPS``.

    Returns the user; raises 403 ``role_required`` / ``["admin"]`` otherwise.
    """
    if not user.is_admin:
        raise _forbidden("role_required", [ADMIN])
    return user


def require_dozent(user: User = Depends(get_current_user)) -> User:
    """Dependency: the caller teaches at least one course (any ``group:<course>#dozent`` token).

    Returns the user; raises 403 ``role_required`` / ``["dozent"]`` otherwise.
    """
    if not user.is_dozent:
        raise _forbidden("role_required", [DOZENT])
    return user


# ================================================================
# APPS
# ================================================================
def can_register_app(user: User) -> bool:
    """Register a new app: dozents of any course and admins (E6)."""
    return user.is_dozent or _is_admin(user)


def ensure_register_app(user: User) -> None:
    """Raise 403 ``role_required`` / ``["dozent", "admin"]`` unless :func:`can_register_app`."""
    if not can_register_app(user):
        raise _forbidden("role_required", [DOZENT, ADMIN])


def can_view_app(user: User, app: App, *, db: Session | None = None) -> bool:
    """Whether ``user`` may see ``app`` at all.

    Allowed when:
      - user owns the app, OR
      - user is admin, OR
      - app is public AND has at least one approved version.

    Soft-deleted apps are filtered out before this is called (crud). Without
    ``db`` the third case cannot be checked and yields False.
    """
    if _is_owner(user, app.userId):
        return True
    if _is_admin(user):
        return True
    if app.is_private:
        return False
    if db is None:
        # Without a DB handle we can't verify the approved-version
        # requirement; the safe default is "no".
        return False
    return crud_approvals.has_any_approved_version(db, app.appId)


def ensure_view_app(user: User, app: App, *, db: Session | None = None) -> None:
    """Raise 403 ``app_view_forbidden`` unless :func:`can_view_app`."""
    if not can_view_app(user, app, db=db):
        raise _forbidden("app_view_forbidden")


def can_see_unreviewed_versions(user: User, app: App) -> bool:
    """Whether ``user`` sees every tag of ``app``, not only approved ones. Owner or admin."""
    return _is_admin(user) or _is_owner(user, app.userId)


def can_publish_app(user: User, app: App) -> bool:
    """Whether ``user`` may make ``app`` public: an admin always, the owner
    only while no admin has deactivated it (``hidden_by_admin``)."""
    return _is_admin(user) or (_is_owner(user, app.userId) and not app.hidden_by_admin)


def ensure_publish_app(user: User, app: App) -> None:
    """Raise 403 ``app_hidden_by_admin`` unless :func:`can_publish_app`."""
    if not can_publish_app(user, app):
        raise _forbidden("app_hidden_by_admin")


def can_list_all_apps(user: User) -> bool:
    """Whether ``user`` may list every app (including private + unapproved).

    Admin only. Everyone else sees "my apps + public approved apps" —
    that is a query-shape concern (``crud.apps.get_visible_apps``), not a
    flat boolean.
    """
    return _is_admin(user)


def ensure_list_all_apps(user: User) -> None:
    """Raise 403 ``role_required`` / ``["admin"]`` unless :func:`can_list_all_apps`."""
    if not can_list_all_apps(user):
        raise _forbidden("role_required", [ADMIN])


def can_edit_app(user: User, app: App) -> bool:
    """Whether ``user`` may edit ``app``'s metadata. Owner or admin only."""
    return _is_admin(user) or _is_owner(user, app.userId)


def ensure_edit_app(user: User, app: App) -> None:
    """Raise 403 ``app_edit_forbidden`` unless :func:`can_edit_app`."""
    if not can_edit_app(user, app):
        raise _forbidden("app_edit_forbidden")


def can_delete_app(user: User, app: App) -> bool:
    """Whether ``user`` may (soft-)delete ``app``. Owner or admin only."""
    return _is_admin(user) or _is_owner(user, app.userId)


def ensure_delete_app(user: User, app: App) -> None:
    """Raise 403 ``app_delete_forbidden`` unless :func:`can_delete_app`."""
    if not can_delete_app(user, app):
        raise _forbidden("app_delete_forbidden")


def can_submit_app_version(user: User, app: App) -> bool:
    """Submit a version for approval review. Owner or admin only."""
    return _is_admin(user) or _is_owner(user, app.userId)


def ensure_submit_app_version(user: User, app: App) -> None:
    """Raise 403 ``app_submit_forbidden`` unless :func:`can_submit_app_version`."""
    if not can_submit_app_version(user, app):
        raise _forbidden("app_submit_forbidden")


def can_approve_app_version(user: User) -> bool:
    """Approve / reject / revoke a submitted version. Admin only."""
    return _is_admin(user)


def ensure_approve_app_version(user: User) -> None:
    """Raise 403 ``role_required`` / ``["admin"]`` unless :func:`can_approve_app_version`."""
    if not can_approve_app_version(user):
        raise _forbidden("role_required", [ADMIN])


# ================================================================
# DEPLOYMENTS
# ================================================================
def can_deploy(user: User) -> bool:
    """Start a deployment at all: the caller teaches at least one course.

    The chosen course is checked with :func:`ensure_teach_course`, the
    credential (must be the caller's own) where the deploy is built.
    """
    return user.is_dozent


def ensure_deploy(user: User) -> None:
    """Raise 403 ``role_required`` / ``["dozent"]`` unless :func:`can_deploy`."""
    if not can_deploy(user):
        raise _forbidden("role_required", [DOZENT])


def taught_courses(user: User) -> list[str]:
    """The courses ``user`` teaches, as sorted group tokens (``group:<id>``, relation stripped)."""
    return sorted(
        t.removesuffix(DOZENT_SUFFIX)
        for t in getattr(user, "tokens", frozenset())
        if t.startswith("group:") and t.endswith(DOZENT_SUFFIX)
    )


def can_teach_course(user: User, course: str) -> bool:
    """Deploy for, and list the students of, ``course``.

    ``course`` is a group token (``group:<id>``); the caller must hold exactly
    ``group:<id>#dozent``. Admin rights do not substitute.
    """
    return f"{course}{DOZENT_SUFFIX}" in getattr(user, "tokens", frozenset())


def ensure_teach_course(user: User, course: str) -> None:
    """Raise 403 ``course_not_taught`` / ``["group:<id>#dozent"]`` unless :func:`can_teach_course`."""
    if not can_teach_course(user, course):
        raise _forbidden("course_not_taught", [f"{course}{DOZENT_SUFFIX}"])


def is_team_member(user: User, dep: Deployment, db: Session) -> bool:
    """Whether ``user`` is in one of the deployment's teams.

    Also true for a direct ``UserToDeployment`` mapping of the user to the
    deployment.
    """
    in_team = (
        db.query(UserToTeam.userToTeamId)
        .join(Team, Team.teamId == UserToTeam.teamId)
        .filter(Team.deploymentId == dep.deploymentId, UserToTeam.userId == user.userId)
        .first()
    )
    if in_team:
        return True
    mapped = (
        db.query(UserToDeployment.userToDeploymentId)
        .filter(UserToDeployment.deploymentId == dep.deploymentId, UserToDeployment.userId == user.userId)
        .first()
    )
    return mapped is not None


def is_project_peer(user: User, dep: Deployment, db: Session) -> bool:
    """Whether ``user`` holds an own credential for the deployment's project (plan E2).

    False for a deployment without a recorded project.
    """
    project_id = getattr(dep, "os_project_id", None)
    if not project_id:
        return False
    return crud_creds.get_for_project(db, user.userId, project_id) is not None


def can_view_deployment_owner(user: User, dep: Deployment, db: Session) -> bool:
    """Owner view: tasks, logs, all teams, outputs (sensitive ones redacted).

    The owner, project peers, and admins reading.
    """
    return _is_owner(user, dep.userId) or _is_admin(user) or is_project_peer(user, dep, db)


def ensure_view_deployment_owner(user: User, dep: Deployment, db: Session) -> None:
    """Raise 403 ``deployment_owner_view_forbidden`` unless :func:`can_view_deployment_owner`."""
    if not can_view_deployment_owner(user, dep, db):
        raise _forbidden("deployment_owner_view_forbidden")


def can_view_deployment_member(user: User, dep: Deployment, db: Session) -> bool:
    """Member view: the deployment, the caller's own team and access.

    Everyone with the owner view, plus the members of its teams.
    """
    return can_view_deployment_owner(user, dep, db) or is_team_member(user, dep, db)


def ensure_view_deployment_member(user: User, dep: Deployment, db: Session) -> None:
    """Raise 403 ``deployment_view_forbidden`` unless :func:`can_view_deployment_member`."""
    if not can_view_deployment_member(user, dep, db):
        raise _forbidden("deployment_view_forbidden")


def can_operate_deployment(user: User, dep: Deployment, db: Session) -> bool:
    """Pause, resume, destroy, redeploy, change teams: the owner and project peers.

    Admins are not operators: they have no credential of their own there.
    """
    return _is_owner(user, dep.userId) or is_project_peer(user, dep, db)


def ensure_operate_deployment(user: User, dep: Deployment, db: Session) -> None:
    """Raise 403 ``deployment_operate_forbidden`` unless :func:`can_operate_deployment`."""
    if not can_operate_deployment(user, dep, db):
        raise _forbidden("deployment_operate_forbidden")


def can_resend_access(user: User, dep: Deployment, target_user_id: UUID | str, db: Session) -> bool:
    """Resend an access mail: to oneself as a member, to anyone with the owner view."""
    if str(target_user_id) == str(user.userId):
        return can_view_deployment_member(user, dep, db)
    return can_view_deployment_owner(user, dep, db)


def ensure_resend_access(user: User, dep: Deployment, target_user_id: UUID | str, db: Session) -> None:
    """Raise 403 ``deployment_resend_forbidden`` unless :func:`can_resend_access`."""
    if not can_resend_access(user, dep, target_user_id, db):
        raise _forbidden("deployment_resend_forbidden")


__all__ = [
    "ADMIN",
    "DOZENT",
    "require_admin",
    "require_dozent",
    # Courses
    "taught_courses",
    "can_teach_course",
    "ensure_teach_course",
    # Apps
    "can_register_app",
    "ensure_register_app",
    "can_view_app",
    "ensure_view_app",
    "can_see_unreviewed_versions",
    "can_publish_app",
    "ensure_publish_app",
    "can_list_all_apps",
    "ensure_list_all_apps",
    "can_edit_app",
    "ensure_edit_app",
    "can_delete_app",
    "ensure_delete_app",
    "can_submit_app_version",
    "ensure_submit_app_version",
    "can_approve_app_version",
    "ensure_approve_app_version",
    # Deployments
    "can_deploy",
    "ensure_deploy",
    "is_team_member",
    "is_project_peer",
    "can_view_deployment_member",
    "ensure_view_deployment_member",
    "can_view_deployment_owner",
    "ensure_view_deployment_owner",
    "can_operate_deployment",
    "ensure_operate_deployment",
    "can_resend_access",
    "ensure_resend_access",
]
