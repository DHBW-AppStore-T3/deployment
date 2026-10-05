"""Courses and who is in them (plan AP4).

A course is a group in role-provider-service with the relations ``dozent``
and ``studierende``. The AppStore keeps no course table: the courses a caller
may pick are the ``group:<id>#dozent`` tokens they hold (see
``utils/capabilities.taught_courses``), and the people a team may be built
from are the course's ``studierende``, asked for when needed. Teams are
checked against that list on the server, so a hand-made request cannot put
an arbitrary address into a deployment and send mails to it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import HTTPException, status

from appstore_api.services.role_provider import RoleProviderError, get_role_provider

logger = logging.getLogger(__name__)

STUDENT_RELATION = "studierende"


@dataclass(frozen=True)
class Course:
    """A course token with the labels the UI shows for it."""

    course: str
    display_name: str
    description: str


def _unavailable(e: RoleProviderError) -> HTTPException:
    """Log the role-provider failure and build the 503 returned to the client."""
    logger.warning("role provider did not answer: %s", e)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "role_provider_unavailable"},
    )


def describe(courses: list[str]) -> list[Course]:
    """Display name and description for each course token.

    A course the role provider does not describe (or cannot, right now)
    is still listed, under its id: the caller holds the token, so they do
    teach it, and a missing label must not hide it.
    """
    provider = get_role_provider()
    described: list[Course] = []
    for course in courses:
        try:
            group = provider.get_group(course)
        except RoleProviderError as e:
            logger.warning("describing %s failed: %s", course, e)
            group = None
        fallback = course.removeprefix("group:")
        described.append(
            Course(
                course=course,
                display_name=(group.display_name if group else "") or fallback,
                description=group.description if group else "",
            )
        )
    return described


def students(course: str) -> list[str]:
    """Return the addresses holding ``studierende`` in ``course``.

    Raises HTTPException 503 if the role provider does not answer.
    """
    try:
        return get_role_provider().get_member_emails(course, STUDENT_RELATION)
    except RoleProviderError as e:
        raise _unavailable(e) from e


def normalise_email(value: str) -> str:
    """Canonical form (trimmed, lower-case) used to compare team member addresses."""
    return value.strip().lower()


def ensure_team_members(course: str, teams: list[tuple[str, list[str]]]) -> None:
    """Check that every member is a student of ``course`` and in at most one team.

    ``teams`` is ``[(team name, [normalised e-mail, ...]), ...]``. Team names
    must be unique too. Raises HTTPException 422 (codes
    ``duplicate_team_name``, ``member_in_several_teams``, ``not_in_course``)
    with the offending names/addresses, so the wizard can mark them; 503 if
    the role provider cannot list the students.
    """
    seen: dict[str, str] = {}
    duplicates: set[str] = set()
    names: set[str] = set()
    duplicate_names: set[str] = set()
    for name, emails in teams:
        if name in names:
            duplicate_names.add(name)
        names.add(name)
        for email in emails:
            if email in seen:
                duplicates.add(email)
            seen[email] = name
    if duplicate_names:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "duplicate_team_name", "teams": sorted(duplicate_names)},
        )
    if duplicates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "member_in_several_teams", "emails": sorted(duplicates)},
        )
    if not seen:
        return
    enrolled = set(students(course))
    outsiders = sorted(set(seen) - enrolled)
    if outsiders:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "not_in_course", "course": course, "emails": outsiders},
        )
