"""CRUD for users' OpenStack credentials, one per project (plan AP5).

Two ways out of the table, because the dispatch path and the backend's own
OpenStack calls have different needs:

* ``dispatch_envelope`` — JSON-safe dict with **base64 ciphertext** for the
  worker's job payload. The backend never decrypts here.
* ``decrypted`` — plaintext dict for the backend's own OpenStack calls
  (resource picker, quota, live resources). Plaintext lives only in this
  process's memory for the duration of the request.

The plaintext dict MUST NOT be put into a job payload.
"""

from __future__ import annotations

import base64
from uuid import UUID

from sqlalchemy.orm import Session

from appstore_api.models import UserOpenStackCredential
from appstore_api.schemas import OpenStackCredentialUpsert
from appstore_api.utils import crypto
from appstore_api.utils.time import utcnow


def list_for_user(db: Session, user_id: UUID) -> list[UserOpenStackCredential]:
    """The caller's credentials, ordered by project name."""
    return (
        db.query(UserOpenStackCredential)
        .filter(UserOpenStackCredential.userId == user_id)
        .order_by(UserOpenStackCredential.project_name, UserOpenStackCredential.project_id)
        .all()
    )


def get_owned(db: Session, user_id: UUID, credential_id: UUID) -> UserOpenStackCredential | None:
    """The credential ``credential_id`` if it belongs to ``user_id``, else None (never someone else's)."""
    return (
        db.query(UserOpenStackCredential)
        .filter(UserOpenStackCredential.credentialId == credential_id, UserOpenStackCredential.userId == user_id)
        .first()
    )


def get_for_project(db: Session, user_id: UUID, project_id: str) -> UserOpenStackCredential | None:
    """The user's credential for ``project_id`` (at most one per user and project), or None."""
    return (
        db.query(UserOpenStackCredential)
        .filter(UserOpenStackCredential.userId == user_id, UserOpenStackCredential.project_id == project_id)
        .first()
    )


def project_ids_of(db: Session, user_id: UUID) -> list[str]:
    """The projects ``user_id`` holds a credential for."""
    return [
        row[0]
        for row in db.query(UserOpenStackCredential.project_id).filter(UserOpenStackCredential.userId == user_id)
    ]


def save(
    db: Session,
    user_id: UUID,
    payload: OpenStackCredentialUpsert,
    project_id: str,
    project_name: str | None,
) -> tuple[UserOpenStackCredential, bool]:
    """Store a credential Keystone accepted; replace the one for the same project.

    ``project_id``/``project_name`` are the token's (``openstack_validator``).
    Replacing is how a secret is rotated. Identifier and secret are
    Fernet-encrypted; commits. Returns ``(row, created)``.
    """
    row = get_for_project(db, user_id, project_id)
    created = row is None
    if row is None:
        row = UserOpenStackCredential(userId=user_id, project_id=project_id)
        db.add(row)
    row.auth_type = payload.auth_type
    row.auth_url = payload.auth_url
    row.region_name = payload.region_name
    row.interface = payload.interface or "public"
    row.identity_api_version = payload.identity_api_version or "3"
    row.project_name = project_name or payload.project_name
    row.user_domain_name = payload.user_domain_name
    row.project_domain_name = payload.project_domain_name
    row.encrypted_identifier = crypto.encrypt(payload.identifier)
    row.encrypted_secret = crypto.encrypt(payload.secret)
    row.last_validated_at = utcnow()
    row.last_validation_error = None
    db.commit()
    db.refresh(row)
    return row, created


def stamp_validation(db: Session, row: UserOpenStackCredential, error: str | None) -> UserOpenStackCredential:
    """Record the outcome of a re-check (``/test``) without touching the secret; commits.

    A failed check keeps ``last_validated_at`` at the last success.
    """
    if error is None:
        row.last_validated_at = utcnow()
        row.last_validation_error = None
    else:
        row.last_validation_error = error
    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, row: UserOpenStackCredential) -> None:
    """Delete the credential and commit; the router refuses while deployments use it."""
    db.delete(row)
    db.commit()


def _common_metadata(row: UserOpenStackCredential) -> dict:
    """The non-secret ``clouds.yaml``-style fields shared by both output shapes."""
    return {
        "auth_type": row.auth_type.value if hasattr(row.auth_type, "value") else row.auth_type,
        "auth_url": row.auth_url,
        "region_name": row.region_name,
        "interface": row.interface or "public",
        "identity_api_version": row.identity_api_version or "3",
        "project_id": row.project_id,
        "project_name": row.project_name,
        "user_domain_name": row.user_domain_name,
        "project_domain_name": row.project_domain_name,
    }


def dispatch_envelope(row: UserOpenStackCredential) -> dict:
    """The JSON-safe envelope shipped to the worker in the job payload.

    Ciphertext is base64-encoded straight from Postgres — no decryption
    hop in the backend. The worker decrypts in-process.
    """
    envelope = _common_metadata(row)
    envelope["encrypted_identifier_b64"] = base64.b64encode(row.encrypted_identifier).decode("ascii")
    envelope["encrypted_secret_b64"] = base64.b64encode(row.encrypted_secret).decode("ascii")
    return envelope


def decrypted(row: UserOpenStackCredential) -> dict:
    """Plaintext dict for backend-only OpenStack calls.

    NEVER put this into a job payload. Use ``dispatch_envelope`` for that path.
    """
    out = _common_metadata(row)
    out["identifier"] = crypto.decrypt(row.encrypted_identifier)
    out["secret"] = crypto.decrypt(row.encrypted_secret)
    return out
