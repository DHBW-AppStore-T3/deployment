"""Example data for local development (``make dev``, plan AP7).

Fills an empty development database with what the role-provider mock's
identities need to click through the whole flow without a cloud:

- ``faculty@cs.example`` (teaches ``wwi23seb``) owns three public example
  apps, each with its newest tag approved, and a simulated OpenStack
  credential;
- ``cs-student@cs.com`` (studies in ``wwi23seb``) can be put into teams;
- ``root.admin@uni.example`` is admin when ``APPSTORE_ADMIN_GROUPS`` names
  ``group:root_uni`` (``make dev`` does).

Idempotent, and refused outside ``API_MODE=development``. The apps are the
students' original repositories until the new ones have a home (plan AP0);
their tags are resolved once with ``git ls-remote`` and left unapproved when
that fails (offline).
"""

from __future__ import annotations

import logging
import sys

from appstore_api.config import settings
from appstore_api.crud import openstack_credentials as crud_creds
from appstore_api.crud import users as crud_users
from appstore_api.database import SessionLocal
from appstore_api.models import App, AppVersionApproval, AppVersionApprovalStatus, OpenStackAuthType
from appstore_api.schemas import OpenStackCredentialUpsert
from appstore_api.services.git_service import git_service

logger = logging.getLogger("dev_seed")

DOZENT = "faculty@cs.example"
STUDENT = "cs-student@cs.com"
ADMIN = "root.admin@uni.example"

APPS = [
    ("Online-IDE", "Code-Server im Browser, eine VM pro Team", "https://github.com/DHBW-AppStore/Online-IDE"),
    ("pgAdmin", "PostgreSQL mit pgAdmin für Datenbank-Übungen", "https://github.com/DHBW-AppStore/pgAdmin"),
    ("Web-LaTeX", "LaTeX-Editor im Browser", "https://github.com/DHBW-AppStore/Web-LaTeX"),
]


def _newest_tag(git_url: str) -> tuple[str, str] | None:
    """Return (tag, commit sha) of the highest version tag, or None if offline or untagged.

    ``get_versions`` already lists the newest ``vX.Y.Z`` first (other tag
    names after them), so the first tag is the one to approve.
    """
    try:
        versions = git_service.get_versions(git_url)
    except Exception as e:  # noqa: BLE001 — offline is fine, the app stays unapproved
        logger.warning("could not read the tags of %s: %s", git_url, e)
        return None
    tags = [v for v in versions if v.get("type") == "tag" and v.get("sha")]
    if not tags:
        return None
    return tags[0]["version"], tags[0]["sha"]


def seed() -> None:
    """Create the example users, apps (with approvals) and credential; skips what exists.

    Commits to the database; raises SystemExit unless ``API_MODE=development``.
    """
    if settings.API_MODE != "development":
        raise SystemExit("dev_seed only runs with API_MODE=development")
    with SessionLocal() as db:
        users = crud_users.ensure_users(db, [DOZENT, STUDENT, ADMIN])
        db.commit()
        owner = users[DOZENT]

        for name, description, git_link in APPS:
            if db.query(App).filter(App.git_link == git_link).first():
                continue
            app = App(name=name, description=description, git_link=git_link, is_private=False, userId=owner.userId)
            db.add(app)
            db.flush()
            newest = _newest_tag(git_link)
            if newest:
                tag, sha = newest
                db.add(
                    AppVersionApproval(
                        appId=app.appId,
                        version_tag=tag,
                        commit_sha=sha,
                        status=AppVersionApprovalStatus.APPROVED,
                        notes="Beispieldaten (make dev)",
                    )
                )
            logger.info("app %s%s", name, f" with {newest[0]} approved" if newest else "")
        db.commit()

        if not crud_creds.list_for_user(db, owner.userId):
            if not settings.OPENSTACK_SIMULATE:
                logger.warning("OPENSTACK_SIMULATE is off: no example credential (it would need a real project)")
            else:
                crud_creds.save(
                    db,
                    owner.userId,
                    OpenStackCredentialUpsert(
                        auth_type=OpenStackAuthType.APPLICATION_CREDENTIAL,
                        auth_url="https://keystone.invalid/v3",
                        identifier="simulated-application-credential",
                        secret="simulated-secret",
                    ),
                    "sim-wwi23seb",
                    "WWI23SEB Übungen (simuliert)",
                )
                logger.info("simulated credential for %s", DOZENT)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s", stream=sys.stdout)
    seed()
