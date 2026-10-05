"""OIDC bearer tokens, checked the way openstack-management-api does (its §6.1).

- The token is verified against ``OIDC_ISSUER_URL`` with ``OIDC_CLIENT_ID`` as
  audience; the caller is its ``email`` claim, else ``preferred_username``,
  else ``sub``.
- **The identity provider is not a startup dependency.** Keys are fetched when
  the first token arrives (from ``OIDC_JWKS_URL``, or from the issuer's
  discovery document). On 2026-09-25 a Keycloak outage kept every restarting
  pod of the platform down long after the cluster itself was fine; this
  service must not add to that.
- A token that cannot be judged because the provider does not answer gets a
  **503**, not a 401: a 401 would send the browser into a login loop against
  a provider that cannot answer. ``/config.json`` reports
  ``sign_in_available: false`` while the last key fetch failed.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKClient, PyJWKClientConnectionError, PyJWKClientError

logger = logging.getLogger(__name__)

# Asymmetric algorithms only: an HS256 token would be checked against a
# shared secret the service does not have, and "none" is never acceptable.
_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]
_FETCH_TIMEOUT_SECONDS = 10


class InvalidToken(Exception):
    """The token is malformed, expired, for someone else, or wrongly signed: 401."""


class IdentityProviderUnavailable(Exception):
    """The keys to judge the token could not be fetched: 503."""


@dataclass(frozen=True)
class Claims:
    """The identity claims of a verified token; nothing else of the payload is kept."""

    email: str | None
    preferred_username: str | None
    sub: str | None

    def identity(self) -> str | None:
        """The caller's name: ``email``, else ``preferred_username``, else ``sub``."""
        return self.email or self.preferred_username or self.sub


class OidcVerifier:
    """Verifies bearer tokens of one issuer and audience; keys are fetched lazily and cached.

    ``sign_in_available`` tracks whether the last key lookup reached the
    provider. One instance is shared by all requests (``auth.get_verifier``).
    """

    def __init__(self, issuer_url: str, client_id: str, jwks_url: str | None = None) -> None:
        self.issuer_url = issuer_url.rstrip("/")
        self.client_id = client_id
        self._jwks_url = jwks_url or None
        self._jwks: PyJWKClient | None = None
        self._lock = threading.Lock()
        # Until a fetch fails, assume the provider is there: a fresh pod has
        # not asked yet, and saying "no sign-in" before trying would be wrong.
        self.sign_in_available = True

    def _discover_jwks_url(self) -> str:
        """Read ``jwks_uri`` from the issuer's discovery document; IdentityProviderUnavailable on failure."""
        url = f"{self.issuer_url}/.well-known/openid-configuration"
        try:
            response = httpx.get(url, timeout=_FETCH_TIMEOUT_SECONDS)
            response.raise_for_status()
            return str(response.json()["jwks_uri"])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise IdentityProviderUnavailable(f"OIDC discovery at {url} failed: {e}") from e

    def _client(self) -> PyJWKClient:
        """The JWKS client, created on first use (keys cached for an hour); thread-safe."""
        with self._lock:
            if self._jwks is None:
                jwks_url = self._jwks_url or self._discover_jwks_url()
                self._jwks = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=_FETCH_TIMEOUT_SECONDS)
            return self._jwks

    def verify(self, token: str) -> Claims:
        """Check signature, ``exp``, issuer and audience of ``token`` and return its claims.

        Raises InvalidToken (-> 401) or IdentityProviderUnavailable (-> 503);
        updates ``sign_in_available`` according to whether the provider answered.
        """
        try:
            key = self._client().get_signing_key_from_jwt(token)
        except IdentityProviderUnavailable:
            self.sign_in_available = False
            raise
        except PyJWKClientConnectionError as e:
            self.sign_in_available = False
            raise IdentityProviderUnavailable(f"fetching the OIDC keys failed: {e}") from e
        except (PyJWKClientError, jwt.DecodeError) as e:
            # Unknown kid or not a JWT at all; the provider did answer.
            self.sign_in_available = True
            raise InvalidToken(str(e)) from e
        self.sign_in_available = True
        try:
            payload = jwt.decode(
                token,
                key.key,
                algorithms=_ALGORITHMS,
                audience=self.client_id,
                issuer=self.issuer_url,
                options={"require": ["exp", "iss"]},
            )
        except jwt.PyJWTError as e:
            raise InvalidToken(str(e)) from e
        return Claims(
            email=payload.get("email"),
            preferred_username=payload.get("preferred_username"),
            sub=payload.get("sub"),
        )
