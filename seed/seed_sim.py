"""Minimal seed for the simulation-mode dev stack (.github#6).

Creates users, courses and apps directly in the database.
No Keycloak required. Idempotent.

Usage (from inside the backend-sim container):
    python /seed/seed_sim.py
Or via make:
    make dev-sim
"""
from __future__ import annotations

import logging
import os
import sys

from sqlalchemy.orm import Session

# Make sure the app module is importable when run inside the backend container.
sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models import App, AppVersionApproval, AppVersionApprovalStatus, Course, CourseTeacher, User, UserRole

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("seed_sim")


# ----------------------------------------------------------------
# Data definitions
# ----------------------------------------------------------------
TEACHER_EMAIL = "prof@dhbw.de"
STUDENT_EMAIL = "student@dhbw.de"
ADMIN_EMAIL = "admin@dhbw.de"
COURSE_NAME = "WI SE B 23"

APPS = [
    {
        "name": "Online-IDE",
        "description": "Code-Server im Browser, eine VM pro Team",
        "git_link": "https://github.com/DHBW-AppStore/Online-IDE",
        "is_private": False,
    },
    {
        "name": "pgAdmin",
        "description": "PostgreSQL mit pgAdmin für Datenbank-Übungen",
        "git_link": "https://github.com/DHBW-AppStore/pgAdmin",
        "is_private": False,
    },
    {
        "name": "Web-LaTeX",
        "description": "LaTeX-Editor im Browser",
        "git_link": "https://github.com/DHBW-AppStore/Web-LaTeX",
        "is_private": False,
    },
]


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _get_or_create_user(db: Session, email: str, role: UserRole) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(email=email, username=email.split("@")[0], role=role)
    db.add(user)
    db.flush()
    logger.info("Created user %s (%s)", email, role.value)
    return user


def _get_or_create_course(db: Session, name: str) -> Course:
    course = db.query(Course).filter(Course.name == name).first()
    if course:
        return course
    course = Course(name=name)
    db.add(course)
    db.flush()
    logger.info("Created course %s", name)
    return course


def _link_teacher(db: Session, course: Course, teacher: User) -> None:
    exists = (
        db.query(CourseTeacher)
        .filter(CourseTeacher.courseId == course.courseId, CourseTeacher.userId == teacher.userId)
        .first()
    )
    if not exists:
        db.add(CourseTeacher(courseId=course.courseId, userId=teacher.userId))
        logger.info("Linked %s as teacher of %s", teacher.email, course.name)


def _get_or_create_app(db: Session, data: dict, owner: User) -> App:
    app = db.query(App).filter(App.name == data["name"]).first()
    if app:
        return app
    app = App(
        name=data["name"],
        description=data["description"],
        git_link=data["git_link"],
        is_private=data["is_private"],
        userId=owner.userId,
    )
    db.add(app)
    db.flush()
    logger.info("Created app %s", app.name)
    return app


def _approve_app(db: Session, app: App, approver: User) -> None:
    exists = (
        db.query(AppVersionApproval)
        .filter(
            AppVersionApproval.appId == app.appId,
            AppVersionApproval.status == AppVersionApprovalStatus.APPROVED,
        )
        .first()
    )
    if exists:
        return
    approval = AppVersionApproval(
        appId=app.appId,
        reviewed_by=approver.userId,
        status=AppVersionApprovalStatus.APPROVED,
        version_tag="sim-latest",
        commit_sha="0000000000000000000000000000000000000000",
    )
    db.add(approval)
    logger.info("Approved app %s", app.name)


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
def seed() -> None:
    with SessionLocal() as db:
        teacher = _get_or_create_user(db, TEACHER_EMAIL, UserRole.TEACHER)
        student = _get_or_create_user(db, STUDENT_EMAIL, UserRole.STUDENT)  # noqa: F841
        admin = _get_or_create_user(db, ADMIN_EMAIL, UserRole.ADMIN)  # noqa: F841

        course = _get_or_create_course(db, COURSE_NAME)
        _link_teacher(db, course, teacher)

        for app_data in APPS:
            app = _get_or_create_app(db, app_data, owner=teacher)
            _approve_app(db, app, approver=teacher)

        db.commit()

    logger.info(
        "Seed complete.\n"
        "  Teacher:  %s\n"
        "  Student:  %s\n"
        "  Admin:    %s\n"
        "  Course:   %s\n"
        "  Apps:     %s",
        TEACHER_EMAIL,
        STUDENT_EMAIL,
        ADMIN_EMAIL,
        COURSE_NAME,
        ", ".join(a["name"] for a in APPS),
    )


if __name__ == "__main__":
    seed()
