"""Courses of the caller, their students, and the caller's own access (plan AP4, E5).

- ``GET /me``: who is calling and what the UI should offer them.
- ``GET /me/courses``: the courses the caller teaches, for the deploy wizard.
- ``GET /courses/{course}/students``: who teams of that course may contain;
  only for those who teach it. The browser never talks to role-provider-service
  itself.
- ``GET /me/access``: "Meine Zugänge", every deployment the caller is a team
  member of with their own access. This is where the access data lives that
  the mails leave out.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from appstore_api.auth import get_current_user
from appstore_api.crud import deployments as crud_deployments
from appstore_api.database import get_db
from appstore_api.models import User
from appstore_api.schemas import CourseResponse, CourseToken, MeResponse, MyAccessEntry
from appstore_api.services import courses, deployment_notifier
from appstore_api.utils.capabilities import (
    can_deploy,
    can_register_app,
    ensure_teach_course,
    taught_courses,
)

router = APIRouter()


@router.get("/me", response_model=MeResponse, tags=["Courses"])
def get_me(current_user: User = Depends(get_current_user)):
    """Return who is calling and which kinds of action the UI should offer them.

    Any signed-in user. ``is_admin``/``is_dozent`` and the ``can_*`` flags
    are derived from the caller's tokens on this request; they only steer
    the UI, every endpoint checks rights again.
    """
    return MeResponse(
        userId=current_user.userId,
        email=current_user.email,
        is_admin=current_user.is_admin,
        is_dozent=current_user.is_dozent,
        can_register_apps=can_register_app(current_user),
        can_deploy=can_deploy(current_user),
    )


@router.get("/me/courses", response_model=list[CourseResponse], tags=["Courses"])
def list_my_courses(current_user: User = Depends(get_current_user)):
    """List the courses the caller teaches (``group:<id>#dozent``), with display names.

    Any signed-in user; empty for callers who teach nothing. Used by the
    deploy wizard to pick a course.
    """
    return courses.describe(taught_courses(current_user))


@router.get("/courses/{course}/students", response_model=list[str], tags=["Courses"])
def list_course_students(course: CourseToken, current_user: User = Depends(get_current_user)):
    """List the addresses of the course's ``studierende``, for building teams.

    Only for callers who teach the course (403 ``course_not_taught``
    otherwise). 503 if the role provider cannot be reached.
    """
    ensure_teach_course(current_user, course)
    return courses.students(course)


@router.get("/me/access", response_model=list[MyAccessEntry], tags=["Courses"])
def list_my_access(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """List every deployment the caller is a team member of, with their own access.

    Only the caller's own account and their team's VM are included; the
    maps are empty until a deploy has succeeded or when the app issues no
    per-user account.
    """
    entries: list[MyAccessEntry] = []
    for deployment, team in crud_deployments.get_memberships(db, current_user.userId):
        access = deployment_notifier.get_user_access(db, deployment.deploymentId, current_user.userId) or {}
        entries.append(
            MyAccessEntry(
                deploymentId=deployment.deploymentId,
                name=deployment.name,
                app_name=deployment.app.name,
                course=deployment.course,
                team_name=team.name,
                status=crud_deployments.get_deployment_status(db, deployment.deploymentId),
                user_accounts=access.get("user_accounts", {}),
                team_vms=access.get("team_vms", {}),
            )
        )
    return entries
