"""Demo data of one AppStore environment (Demo/PoC), idempotent.

Run by the Job `seed` (templates/seed-job.yaml) with the backend image after
every sync, as the database owner. Users are not invented here: the users of the
Keycloak realm (the demo logins) are provisioned into the database the same way
their first login would (sync_user_from_keycloak, same Keycloak id), so a
later login finds the same row. Then:

  - the demo course; its teachers are the realm's teachers, its students the
    realm's students that have no course yet
  - the demo apps of /seed/seed.json: registered (public, owned by the first
    admin), their versions submitted and approved; existing apps are not edited

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


def publish_apps(db, owner, apps):
    """Register, submit and approve the demo apps through the backend's own API
    handlers, acting as the first admin: the same checks as a manual call (public
    repository on an allowed host, appstore.yaml of the tag, spec hash), but
    without a login. A Keycloak service-account token would not do: the API
    accepts only the UIs' clients and users with an e-mail and a role."""
    from fastapi.testclient import TestClient

    from app.main import app as api
    from app.models import AppVersionApproval, AppVersionApprovalStatus
    from app.utils.keycloak_auth import get_current_user_keycloak

    api.dependency_overrides[get_current_user_keycloak] = lambda: owner
    client = TestClient(api)
    try:
        for a in apps:
            row = db.query(App).filter(App.name == a["name"]).first()
            if row is None:
                r = client.post("/apps/", json={"name": a["name"], "description": a.get("description"),
                                                "git_link": a.get("gitLink"), "is_private": False})
                if r.status_code != 201:
                    log.warning("app %s not created: %s %s", a["name"], r.status_code, r.text[:300])
                    continue
                app_id = r.json()["appId"]
                log.info("app %s created (owner %s)", a["name"], owner.email)
            else:
                app_id = str(row.appId)
            for tag in a.get("versions", []):
                db.expire_all()
                ap = db.query(AppVersionApproval).filter(
                    AppVersionApproval.appId == app_id, AppVersionApproval.version_tag == tag).first()
                if ap is not None and ap.status == AppVersionApprovalStatus.APPROVED:
                    continue
                if ap is None or ap.status == AppVersionApprovalStatus.REJECTED:
                    r = client.post(f"/apps/{app_id}/versions/{tag}/submit", json={"notes": "Demo-Seed"})
                    if r.status_code not in (201, 409):
                        log.warning("%s %s not submitted: %s %s", a["name"], tag, r.status_code, r.text[:300])
                        continue
                r = client.post(f"/admin/apps/{app_id}/versions/{tag}/approve")
                if r.status_code == 200:
                    log.info("%s %s approved", a["name"], tag)
                else:
                    log.warning("%s %s not approved: %s %s", a["name"], tag, r.status_code, r.text[:300])
    finally:
        api.dependency_overrides.pop(get_current_user_keycloak, None)


def main():
    cfg = json.load(open(os.environ.get("SEED_JSON", "/seed/seed.json")))
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

    apps = cfg.get("apps", [])
    owner = db.query(User).filter(User.role == UserRole.ADMIN).order_by(User.created_at).first() if apps else None
    if apps and owner is None:
        log.warning("no admin user: demo apps skipped")
        apps = []
    if apps:
        publish_apps(db, owner, apps)
    log.info("done")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Fail the job (visible in Argo CD and kubectl get jobs); the rollout itself is already done.
        log.error("failed: %s", exc)
        sys.exit(1)
