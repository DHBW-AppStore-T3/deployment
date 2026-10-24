"""Idempotent seed for the local simulation-mode dev stack (.github#6).

1. Provisions all users from the local Keycloak ``dhbw`` realm into Postgres
   via ``app.cli`` (``dozent.demo``, ``admin.demo``, ``student1..4.demo``,
   ``test-teacher``) with their real Keycloak subject IDs.
2. Also ensures the three ``X-Dev-User`` header convenience accounts exist
   (``prof@dhbw.de``, ``student@dhbw.de``, ``admin@dhbw.de``).
3. Creates the demo course ``WI SE B 23`` and links all teachers and students.
4. Registers, submits and approves the Pod catalog apps via ``app.cli.seed_apps``
   (real git commit SHA, ``runtime="kubernetes"``, ``spec_sha256``).

Usage (from inside the backend-sim container):
    python /tmp/seed_sim.py
Or via make:
    make seed-dev
"""
from __future__ import annotations

import logging
import sys

from sqlalchemy.orm import Session

# Make sure the app module is importable when run inside the backend container.
sys.path.insert(0, "/app")

from app.cli import realm_users, seed_apps, seed_course, seed_users
from app.crud import courses as crud_courses
from app.database import SessionLocal
from app.models import Course, CourseTeacher, User, UserRole

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
        "description": "Browserbasierte IDE (code-server) mit Aufgaben fuer Studierende, ein Pod pro Person.",
        "gitLink": "https://github.com/DHBW-AppStore-T3/Online-IDE",
        "versions": ["v2.0.1"],
    },
    {
        "name": "Web-LaTeX",
        "description": "LaTeX-Editor im Browser mit PDF-Vorschau, ein Pod pro Person.",
        "gitLink": "https://github.com/DHBW-AppStore-T3/Web-LaTeX",
        "versions": ["v2.0.2"],
    },
    {
        "name": "Jupyter-Notebook",
        "description": "JupyterLab fuer Datenanalyse und Lehre, ein Pod pro Person.",
        "gitLink": "https://github.com/DHBW-AppStore-T3/Jupyter-Notebook",
        "versions": ["v2.0.0"],
    },
    {
        "name": "pgAdmin",
        "description": "pgAdmin mit PostgreSQL und Pagila-Beispieldatenbank, ein Pod pro Team.",
        "gitLink": "https://github.com/DHBW-AppStore-T3/pgAdmin",
        "versions": ["v2.0.1"],
    },
    {
        "name": "template-app",
        "description": "Vorlage fuer neue AppStore-Apps (nginx-Pod).",
        "gitLink": "https://github.com/DHBW-AppStore-T3/template-app",
        "versions": ["v2.0.1"],
    },
]


def _get_or_create_dev_user(db: Session, email: str, role: UserRole) -> User:
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(email=email, username=email.split("@")[0], role=role)
    db.add(user)
    db.flush()
    logger.info("Created X-Dev-User %s (%s)", email, role.value)
    return user


def _link_teacher(db: Session, course: Course, teacher: User) -> None:
    exists = (
        db.query(CourseTeacher)
        .filter(CourseTeacher.courseId == course.courseId, CourseTeacher.userId == teacher.userId)
        .first()
    )
    if not exists:
        db.add(CourseTeacher(courseId=course.courseId, userId=teacher.userId))
        logger.info("Linked %s as teacher of %s", teacher.email, course.name)


def seed() -> None:
    try:
        kc_realm_users = list(realm_users())
    except Exception as exc:
        logger.warning("Could not fetch Keycloak realm users (%s) — continuing with local DB users", exc)
        kc_realm_users = []

    with SessionLocal() as db:
        provisioned = seed_users(db, kc_realm_users) if kc_realm_users else []

        # Ensure convenience accounts for X-Dev-User header testing exist as well
        teacher = _get_or_create_dev_user(db, TEACHER_EMAIL, UserRole.TEACHER)
        student = _get_or_create_dev_user(db, STUDENT_EMAIL, UserRole.STUDENT)
        admin = _get_or_create_dev_user(db, ADMIN_EMAIL, UserRole.ADMIN)
        db.commit()

        all_users = provisioned + [teacher, student, admin]
        course = seed_course(db, COURSE_NAME, all_users)
        _link_teacher(db, course, teacher)
        if student.courseId is None:
            crud_courses.add_users_to_course(db, course.courseId, [student.userId])
        db.commit()

        owner = (
            db.query(User).filter(User.role == UserRole.ADMIN).order_by(User.created_at).first()
            or admin
        )
        seed_apps(db, owner, APPS)
        db.commit()

    logger.info(
        "Seed complete.\n"
        "  Keycloak users provisioned: %d\n"
        "  X-Dev-User accounts:        %s, %s, %s\n"
        "  Course:                     %s\n"
        "  Apps:                       %s",
        len(provisioned),
        TEACHER_EMAIL,
        STUDENT_EMAIL,
        ADMIN_EMAIL,
        COURSE_NAME,
        ", ".join(a["name"] for a in APPS),
    )


if __name__ == "__main__":
    seed()
