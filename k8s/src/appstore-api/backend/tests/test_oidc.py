"""OIDC bearer tokens and the role provider (plan AP3)."""

from __future__ import annotations

import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from jwt import PyJWKClient, PyJWKClientConnectionError
from pydantic import ValidationError
from starlette.requests import Request

from appstore_api import auth
from appstore_api.config import Settings, settings
from appstore_api.oidc import IdentityProviderUnavailable, InvalidToken, OidcVerifier
from appstore_api.services import role_provider
from appstore_api.services.role_provider import (
    HttpRoleProvider,
    MockRoleProvider,
    RoleProviderError,
)

ISSUER = "https://idp.example/realms/dhbw"
CLIENT = "self-service"
KID = "k1"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWK = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key())), "kid": KID, "use": "sig", "alg": "RS256"}


def _token(**overrides) -> str:
    claims = {
        "iss": ISSUER,
        "aud": CLIENT,
        "exp": int(time.time()) + 300,
        "email": "anna@dhbw.de",
        "preferred_username": "anna",
        "sub": "uuid-anna",
        **overrides,
    }
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, _KEY, algorithm="RS256", headers={"kid": KID})


@pytest.fixture
def idp(monkeypatch):
    """A reachable identity provider serving one key; ``idp.up = False`` takes it down."""

    class Idp:
        up = True

    def fetch(self):
        if not Idp.up:
            raise PyJWKClientConnectionError("connection refused")
        return {"keys": [_JWK]}

    monkeypatch.setattr(PyJWKClient, "fetch_data", fetch)
    return Idp


def _verifier() -> OidcVerifier:
    return OidcVerifier(ISSUER, CLIENT, jwks_url=f"{ISSUER}/protocol/openid-connect/certs")


def test_valid_token_names_the_caller(idp):
    assert _verifier().verify(_token()).identity() == "anna@dhbw.de"


def test_identity_falls_back_to_username_then_subject(idp):
    assert _verifier().verify(_token(email=None)).identity() == "anna"
    assert _verifier().verify(_token(email=None, preferred_username=None)).identity() == "uuid-anna"


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"exp": int(time.time()) - 10},
    ],
)
def test_tokens_for_someone_else_or_expired_are_invalid(idp, claims):
    with pytest.raises(InvalidToken):
        _verifier().verify(_token(**claims))


def test_unsigned_and_symmetric_tokens_are_invalid(idp):
    unsigned = jwt.encode({"iss": ISSUER, "aud": CLIENT, "exp": int(time.time()) + 60}, None, algorithm="none")
    hs = jwt.encode({"iss": ISSUER, "aud": CLIENT}, "k" * 32, algorithm="HS256", headers={"kid": KID})
    for token in (unsigned, hs, "not-a-jwt"):
        with pytest.raises(InvalidToken):
            _verifier().verify(token)


def test_provider_down_is_unavailable_not_invalid_and_recovers(idp):
    verifier = _verifier()
    idp.up = False

    with pytest.raises(IdentityProviderUnavailable):
        verifier.verify(_token())
    assert verifier.sign_in_available is False

    idp.up = True
    verifier.verify(_token())
    assert verifier.sign_in_available is True


def test_discovery_failure_is_unavailable(monkeypatch):
    def down(*_a, **_k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "get", down)
    with pytest.raises(IdentityProviderUnavailable):
        OidcVerifier(ISSUER, CLIENT).verify(_token())


# ----------------------------------------------------------------
# through the API
# ----------------------------------------------------------------
@pytest.fixture
def oidc_api(monkeypatch, idp):
    monkeypatch.setattr(settings, "API_DUMMY_AUTH", False)
    monkeypatch.setattr(settings, "OIDC_ISSUER_URL", ISSUER)
    monkeypatch.setattr(settings, "OIDC_CLIENT_ID", CLIENT)
    monkeypatch.setattr(settings, "OIDC_JWKS_URL", f"{ISSUER}/certs")
    monkeypatch.setattr(auth, "_verifier", None)
    return idp


def _request(headers: dict[str, str]) -> Request:
    return Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


def test_bearer_token_authenticates(oidc_api):
    assert auth.authenticate(_request({"Authorization": f"Bearer {_token(email='Anna@DHBW.de')}"})) == "anna@dhbw.de"


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer ", f"Bearer {_token(aud='x')}"])
def test_missing_or_bad_bearer_is_401(oidc_api, header):
    with pytest.raises(HTTPException) as exc:
        auth.authenticate(_request({"Authorization": header} if header else {}))
    assert exc.value.status_code == 401


def test_provider_down_is_503_and_config_says_so(oidc_api, unauth_client):
    oidc_api.up = False
    with pytest.raises(HTTPException) as exc:
        auth.authenticate(_request({"Authorization": f"Bearer {_token()}"}))
    assert exc.value.status_code == 503

    config = unauth_client.get("/config.json").json()
    assert config["auth"] == {
        "auth_provider": "oidc",
        "issuer_url": ISSUER,
        "client_id": CLIENT,
        "sign_in_available": False,
    }


# ----------------------------------------------------------------
# role provider
# ----------------------------------------------------------------
def _http_provider(handler) -> HttpRoleProvider:
    provider = HttpRoleProvider("http://rp:8085", "read-token", 1)
    provider._client = httpx.Client(base_url="http://rp:8085", transport=httpx.MockTransport(handler))
    return provider


def test_http_provider_speaks_the_role_provider_api():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.raw_path.decode(), request.url.params.get("relation")))
        if request.url.path.endswith("/tokens"):
            return httpx.Response(200, json=["user:a@dhbw.de", "group:wwi23seb#dozent"])
        if request.url.path.endswith("/members"):
            return httpx.Response(200, json=["user:S1@dhbw.de", "pattern:*@student.dhbw.de", "user:s2@dhbw.de"])
        return httpx.Response(200, json={"token": "group:wwi23seb", "display_name": "WWI23SEB", "description": "Kurs"})

    provider = _http_provider(handler)

    assert provider.get_user_tokens("a@dhbw.de") == ["user:a@dhbw.de", "group:wwi23seb#dozent"]
    assert provider.get_group("group:wwi23seb").display_name == "WWI23SEB"
    # Patterns cannot be enumerated; addresses are normalised.
    assert provider.get_member_emails("group:wwi23seb", "studierende") == ["s1@dhbw.de", "s2@dhbw.de"]
    assert seen == [
        ("/v1/users/a%40dhbw.de/tokens", None),
        ("/v1/groups/group%3Awwi23seb", None),
        ("/v1/groups/group%3Awwi23seb/members?relation=studierende&recursive=true", "studierende"),
    ]


def test_http_provider_errors_are_role_provider_errors():
    provider = _http_provider(lambda _r: httpx.Response(500))
    with pytest.raises(RoleProviderError):
        provider.get_user_tokens("a@dhbw.de")


def test_token_lookup_failure_leaves_only_the_user_token(monkeypatch):
    class Down:
        def get_user_tokens(self, email):
            raise RoleProviderError("down")

    monkeypatch.setattr(auth, "get_role_provider", lambda: Down())

    assert auth.resolve_tokens("a@dhbw.de") == frozenset({"user:a@dhbw.de"})


def test_mock_provider_knows_the_dev_course():
    mock = MockRoleProvider()
    assert "group:wwi23seb#dozent" in mock.get_user_tokens("faculty@cs.example")
    assert mock.get_member_emails("group:wwi23seb", "studierende") == ["cs-student@cs.com"]
    assert role_provider.MockRoleProvider().get_group("group:wwi23seb").display_name == "WWI23SEB"


# ----------------------------------------------------------------
# start-up checks
# ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"API_DUMMY_AUTH": False, "OIDC_ISSUER_URL": "", "OIDC_CLIENT_ID": ""}, "OIDC_ISSUER_URL"),
        ({"ROLE_PROVIDER": "ldap"}, "ROLE_PROVIDER must be"),
        ({"ROLE_PROVIDER": "mock", "API_MODE": "production"}, "only with API_MODE=development"),
        ({"ROLE_PROVIDER": "http", "ROLE_PROVIDER_URL": ""}, "ROLE_PROVIDER_URL"),
    ],
)
def test_misconfiguration_stops_the_start(overrides, message):
    base = {
        "DATABASE_URL": "postgresql://x/y",
        "OIDC_ISSUER_URL": ISSUER,
        "OIDC_CLIENT_ID": CLIENT,
        "API_MODE": "development",
        "ROLE_PROVIDER": "mock",
    }
    with pytest.raises(ValidationError, match=message):
        Settings(**{**base, **overrides})
