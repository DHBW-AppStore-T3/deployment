"""Who is calling, and which tokens they hold.

The AppStore keeps no accounts or roles of its own. A caller is an e-mail
address plus a set of tokens (``user:<email>``, ``group:<id>``,
``group:<id>#<relation>``) — the same vocabulary role-provider-service and
openstack-management-api use, so rules compare strings and nothing is mapped
between services. Two tokens matter here:

- any token in ``APPSTORE_ADMIN_GROUPS`` makes the caller an AppStore admin;
- any ``group:<id>#dozent`` token means the caller teaches that course.

The caller is authenticated by an OIDC bearer token (``oidc.py``), or in
development by the ``X-Dummy-Auth-User`` header; the tokens come from
role-provider-service on every request (``services/role_provider.py``). If
that lookup fails, the caller keeps only their own ``user:`` token: they lose
group rights for the request rather than the request failing.

The ``users`` row exists only so apps, deployments and teams have something to
point at. It is created on first sign-in (or when someone is put into a team)
and never carries rights.
"""

from __future__ import annotations

import logging

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from appstore_api.config import settings
from appstore_api.database import get_db
from appstore_api.models import User
from appstore_api.oidc import IdentityProviderUnavailable, InvalidToken, OidcVerifier
from appstore_api.services.role_provider import RoleProviderError, get_role_provider

logger = logging.getLogger(__name__)

DUMMY_AUTH_HEADER = "X-Dummy-Auth-User"
DOZENT_SUFFIX = "#dozent"


def _unauthorized(detail: str) -> HTTPException:
    """Build a 401 with the ``WWW-Authenticate: Bearer`` header RFC 6750 asks for."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


_verifier: OidcVerifier | None = None


def get_verifier() -> OidcVerifier | None:
    """The OIDC verifier, built on first use (no provider contact at start-up)."""
    global _verifier
    if _verifier is None and settings.OIDC_ISSUER_URL and settings.OIDC_CLIENT_ID:
        _verifier = OidcVerifier(settings.OIDC_ISSUER_URL, settings.OIDC_CLIENT_ID, settings.OIDC_JWKS_URL)
    return _verifier


def sign_in_available() -> bool:
    """Whether the UI can offer sign-in now, as reported by ``/config.json``.

    With OIDC: false only while the last key fetch from the provider failed.
    Without a verifier: true exactly when dummy auth is on.
    """
    verifier = get_verifier()
    return verifier.sign_in_available if verifier else settings.API_DUMMY_AUTH


def authenticate(request: Request) -> str:
    """Return the caller's e-mail address; 401 for a bad token, 503 without a provider."""
    if settings.API_DUMMY_AUTH:
        email = (request.headers.get(DUMMY_AUTH_HEADER) or "").strip().lower()
        if not email or "@" not in email:
            raise _unauthorized(f"{DUMMY_AUTH_HEADER} must carry an e-mail address")
        return email

    scheme, _, token = (request.headers.get("Authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("a bearer token is required")
    verifier = get_verifier()
    if verifier is None:  # excluded by the settings validation
        raise _unauthorized("sign-in is not configured")
    try:
        claims = verifier.verify(token.strip())
    except IdentityProviderUnavailable as e:
        logger.warning("cannot verify token: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "identity_provider_unavailable"},
        ) from e
    except InvalidToken as e:
        raise _unauthorized(f"invalid token: {e}") from e
    identity = claims.identity()
    if not identity:
        raise _unauthorized("the token names no user")
    return identity.strip().lower()


def resolve_tokens(email: str) -> frozenset[str]:
    """Tokens held by ``email``, from the role provider; at least ``user:<email>``."""
    own = f"user:{email}"
    try:
        tokens = get_role_provider().get_user_tokens(email)
    except RoleProviderError as e:
        logger.warning("token lookup for %s failed, continuing with the user token only: %s", email, e)
        return frozenset({own})
    return frozenset(tokens) | {own}


def is_dozent(tokens: frozenset[str]) -> bool:
    """True if any token is a ``group:<course>#dozent`` token, i.e. the caller teaches some course."""
    return any(t.startswith("group:") and t.endswith(DOZENT_SUFFIX) for t in tokens)


def _get_or_create_user(db: Session, email: str) -> User:
    """Return the ``users`` row for ``email``, creating (and committing) it on first sign-in."""
    user = db.query(User).filter(User.email == email).first()
    if user is not None:
        return user
    user = User(email=email, username=email.split("@", 1)[0])
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two first requests of the same person raced; the other one won.
        db.rollback()
        user = db.query(User).filter(User.email == email).one()
    else:
        db.refresh(user)
        logger.info("first sign-in, created user row for %s", email)
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI dependency: the calling user, with this request's rights attached.

    Sets the transient attributes ``tokens``, ``is_admin`` and ``is_dozent`` on
    the ``User`` row; they are recomputed on every request and never stored.
    Raises 401/503 as :func:`authenticate` does.
    """
    email = authenticate(request)
    user = _get_or_create_user(db, email)
    tokens = resolve_tokens(email)
    user.tokens = tokens
    user.is_admin = not tokens.isdisjoint(settings.admin_tokens)
    user.is_dozent = is_dozent(tokens)
    return user


__all__ = [
    "get_current_user",
    "authenticate",
    "resolve_tokens",
    "is_dozent",
    "sign_in_available",
    "DUMMY_AUTH_HEADER",
]
