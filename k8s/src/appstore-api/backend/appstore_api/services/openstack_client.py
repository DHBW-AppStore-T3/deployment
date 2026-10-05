"""Shared OpenStack client layer for FastAPI endpoints.

Three responsibilities:

1. Build auth kwargs from a decrypted credential (single source of truth,
   also for the validator).
2. Open one connection per request with *the caller's own* credential —
   for a chosen credential, or for the project of a deployment (plan E2:
   another person's credential is never used). Exposed as context managers
   so endpoints can close it cleanly.
3. A process-local TTL cache for list responses: the wizard fires
   several GETs in quick succession, and a 60s cache avoids a Keystone
   token refresh per click. A frontend refresh button triggers
   ``invalidate``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from typing import Any
from uuid import UUID

import openstack
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.config import settings
from appstore_api.crud import openstack_credentials as crud_creds
from appstore_api.models import User, UserOpenStackCredential
from appstore_api.services.openstack_simulation import SimulatedConnection

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Building connections
# ----------------------------------------------------------------
API_TIMEOUT_SECONDS = 30


def connect_kwargs(creds: dict) -> dict:
    """Build the kwargs dict for ``openstack.connect`` from decrypted
    user credentials. Supports password and application-credential
    (v3applicationcredential) auth.
    """
    base = {
        "auth_url": creds["auth_url"],
        "region_name": creds.get("region_name"),
        "interface": creds.get("interface") or "public",
        "identity_api_version": creds.get("identity_api_version") or "3",
    }
    if creds["auth_type"] == "v3applicationcredential":
        base.update(
            {
                "auth_type": "v3applicationcredential",
                "application_credential_id": creds["identifier"],
                "application_credential_secret": creds["secret"],
            }
        )
    else:
        base.update(
            {
                "auth_type": "password",
                "username": creds["identifier"],
                "password": creds["secret"],
                "project_id": creds.get("project_id"),
                "project_name": creds.get("project_name"),
                "user_domain_name": creds.get("user_domain_name"),
                "project_domain_name": creds.get("project_domain_name")
                or creds.get("user_domain_name"),
            }
        )
    return base


@contextmanager
def _connection(creds: dict, owner: str) -> Iterator[Any]:
    """Open a connection (or a ``SimulatedConnection`` with ``OPENSTACK_SIMULATE``) and close it afterwards.

    Any non-HTTPException raised while connecting *or* inside the ``with``
    body becomes HTTPException 502 ``openstack_unavailable`` (500s are
    reserved for bugs). ``owner`` only labels the log line.
    """
    conn: Any = None
    try:
        if settings.OPENSTACK_SIMULATE:
            conn = SimulatedConnection()
        else:
            conn = openstack.connect(api_timeout=API_TIMEOUT_SECONDS, **connect_kwargs(creds))
        yield conn
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — SDK raises many types
        logger.warning("OpenStack call failed for %s: %s", owner, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"reason": "openstack_unavailable"},
        ) from None
    finally:
        # Close politely; the SDK tolerates leaving it to GC. Ignore errors.
        if conn is not None:
            with suppress(Exception):
                conn.close()


def owned_credential(db: Session, user: User, credential_id: UUID) -> UserOpenStackCredential:
    """Return the caller's credential ``credential_id``.

    Raises HTTPException 404 if it does not exist or belongs to someone else.
    """
    row = crud_creds.get_owned(db, user.userId, credential_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "openstack_credential_not_found"},
        )
    return row


def project_credential(db: Session, user: User, project_id: str) -> UserOpenStackCredential:
    """Return the caller's own credential for ``project_id``.

    Raises HTTPException 403 ``openstack_credentials_missing_for_project``
    if the caller has none: a project peer's credential is never used (E2).
    """
    row = crud_creds.get_for_project(db, user.userId, project_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"reason": "openstack_credentials_missing_for_project", "project_id": project_id},
        )
    return row


@contextmanager
def credential_connection(row: UserOpenStackCredential) -> Iterator[Any]:
    """Yield a connection with the given credential; the caller checked it is theirs.

    Errors map to 502 as in ``_connection``.
    """
    with _connection(crud_creds.decrypted(row), f"credential {row.credentialId}") as conn:
        yield conn


@contextmanager
def project_connection(db: Session, user: User, project_id: str) -> Iterator[Any]:
    """Yield a connection with the caller's own credential for ``project_id``.

    Raises HTTPException 403 without such a credential, 502 on OpenStack errors.
    """
    with credential_connection(project_credential(db, user, project_id)) as conn:
        yield conn


# ----------------------------------------------------------------
# TTL cache for resource lists
# ----------------------------------------------------------------
# Key = (credential_id, resource_kind, frozenset of filter items)
# Value = (expiry_epoch, data)
_CacheKey = tuple[str, str, frozenset]
_cache: dict[_CacheKey, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()
_TTL_SECONDS = 60.0


def _make_key(credential_id: UUID, kind: str, filters: dict | None) -> _CacheKey:
    """Build the cache key; ``filters`` values must be hashable."""
    items: frozenset = frozenset((filters or {}).items())
    return (str(credential_id), kind, items)


def cached_list(
    credential_id: UUID,
    kind: str,
    filters: dict | None,
    fetch: Callable[[], list[dict]],
) -> list[dict]:
    """TTL-cache wrapper. ``fetch`` is called only when no valid entry
    exists. The cache is process-local and in-memory; multiple backend
    instances run independent caches, which is fine since the data is
    allowed to be up to 60s stale.
    """
    key = _make_key(credential_id, kind, filters)
    now = time.monotonic()

    with _cache_lock:
        cached = _cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    # Two concurrent requests may both fetch here; inefficient but not
    # incorrect, and simpler than a per-key lock map.
    data = fetch()

    with _cache_lock:
        _cache[key] = (now + _TTL_SECONDS, data)

    return data


def invalidate(credential_id: UUID, kind: str | None = None) -> int:
    """Invalidate the cache for one credential (the frontend's refresh
    button, or the credential changed). Without ``kind`` all resource
    types are removed; ``kind`` also matches kinds cached per variant
    (``availability_zones`` removes ``availability_zones_compute`` …).
    Returns the number of removed entries.
    """
    cred_str = str(credential_id)
    removed = 0
    with _cache_lock:
        for key in list(_cache.keys()):
            if key[0] != cred_str:
                continue
            if kind is not None and key[1] != kind and not key[1].startswith(kind + "_"):
                continue
            del _cache[key]
            removed += 1
    return removed
