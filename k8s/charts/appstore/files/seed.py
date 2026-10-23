"""Demo data of one AppStore environment (Demo/PoC), idempotent.

Run by the Job `seed` (templates/seed-job.yaml) with the backend image after
every sync, as the database owner. Users are not invented here: the users of the
Keycloak realm (the demo logins) are provisioned into the database the same way
their first login would (sync_user_from_keycloak, same Keycloak id), so a
later login finds the same row. Then:

  - the demo course; its teachers are the realm's teachers, its students the
    realm's students that have no course yet
  - the demo apps of /seed/seed.json (public, owned by the first admin);
    existing apps (by name) are left as they are

Nothing is deleted and nothing that exists is overwritten.
"""
import json
import logging
import os
import sys
import urllib.parse
import urllib.request

from app.database import SessionLocal
from app.models import App, Course, CourseTeacher, User, UserRole
from app.utils.keycloak_auth import sync_user_from_keycloak

logging.basicConfig(level=logging.INFO, format="seed: %(message)s")
log = logging.getLogger("seed")

KC = os.environ["KEYCLOAK_SERVER_URL"].rstrip("/")
REALM = os.environ["KEYCLOAK_REALM"]


def kc(path, data=None, token=None):
    req = urllib.request.Request(f"{KC}{path}", data=data)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def realm_users():
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["KEYCLOAK_CLIENT_ID"],
        "client_secret": os.environ["KEYCLOAK_CLIENT_SECRET"],
    }).encode()
    token = kc(f"/realms/{REALM}/protocol/openid-connect/token", body)["access_token"]
    for u in kc(f"/admin/realms/{REALM}/users?max=500", token=token):
        if u.get("username", "").startswith("service-account-") or not u.get("email") or not u.get("enabled", True):
            continue
        roles = kc(f"/admin/realms/{REALM}/users/{u['id']}/role-mappings/realm", token=token)
        u["roles"] = [r["name"] for r in roles]
        yield u


def main():
    cfg = json.load(open("/seed/seed.json"))
    db = SessionLocal()
    users = []
    for u in realm_users():
        try:
            users.append(sync_user_from_keycloak(db, u))
        except Exception as exc:  # e.g. the same e-mail under another Keycloak id: keep going
            db.rollback()
            log.warning("user %s not provisioned: %s", u.get("username"), exc)
    log.info("%d realm users provisioned", len(users))

    course = None
    if cfg.get("courseName") and users:
        course = db.query(Course).filter(Course.name == cfg["courseName"]).first()
        if course is None:
            course = Course(name=cfg["courseName"])
            db.add(course)
            db.flush()
            log.info("course %s created", course.name)
        linked = {t.userId for t in db.query(CourseTeacher).filter(CourseTeacher.courseId == course.courseId)}
        for u in users:
            if u.role == UserRole.TEACHER and u.userId not in linked:
                db.add(CourseTeacher(courseId=course.courseId, userId=u.userId))
                log.info("teacher %s -> %s", u.email, course.name)
            elif u.role == UserRole.STUDENT and u.courseId is None:
                u.courseId = course.courseId
                log.info("student %s -> %s", u.email, course.name)
        db.commit()

    owner = (
        db.query(User).filter(User.role == UserRole.ADMIN).order_by(User.created_at).first()
        if cfg.get("apps") else None
    )
    if cfg.get("apps") and owner is None:
        log.warning("no admin user: demo apps skipped")
    for a in cfg.get("apps", []) if owner else []:
        if db.query(App).filter(App.name == a["name"]).first():
            continue
        db.add(App(name=a["name"], description=a.get("description"), git_link=a.get("gitLink"),
                   is_private=False, userId=owner.userId))
        log.info("app %s created (owner %s)", a["name"], owner.email)
    db.commit()
    log.info("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail the job (visible in Argo CD and kubectl get jobs); the rollout itself is already done.
        log.error("failed: %s", exc)
        sys.exit(1)
