"""Identity: who is calling, which rights their tokens give, and the start-up guard."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from appstore_api import auth
from appstore_api.config import Settings, settings
from appstore_api.models import User


def _request(headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "headers": raw})


@pytest.fixture
def dummy_auth(monkeypatch):
    monkeypatch.setattr(settings, "API_DUMMY_AUTH", True)


# ----------------------------------------------------------------
# authenticate
# ----------------------------------------------------------------
@pytest.mark.unit
def test_without_dummy_auth_the_header_is_not_enough(monkeypatch):
    monkeypatch.setattr(settings, "API_DUMMY_AUTH", False)
    with pytest.raises(HTTPException) as exc:
        auth.authenticate(_request({auth.DUMMY_AUTH_HEADER: "a@dhbw.de"}))
    assert exc.value.status_code == 401


@pytest.mark.unit
def test_dummy_auth_takes_the_email_from_the_header(dummy_auth):
    assert auth.authenticate(_request({auth.DUMMY_AUTH_HEADER: " Alice@DHBW.de "})) == "alice@dhbw.de"


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "not-an-email"])
def test_dummy_auth_needs_an_email(dummy_auth, value):
    headers = {} if value is None else {auth.DUMMY_AUTH_HEADER: value}
    with pytest.raises(HTTPException) as exc:
        auth.authenticate(_request(headers))
    assert exc.value.status_code == 401


# ----------------------------------------------------------------
# tokens → rights
# ----------------------------------------------------------------
@pytest.mark.unit
@pytest.mark.parametrize(
    ("tokens", "expected"),
    [
        ({"user:a@dhbw.de"}, False),
        ({"group:wwi23seb"}, False),
        ({"group:wwi23seb#studierende"}, False),
        ({"group:wwi23seb#dozent"}, True),
        # A user token that happens to end in "#dozent" is not a role.
        ({"user:x#dozent"}, False),
    ],
)
def test_is_dozent(tokens, expected):
    assert auth.is_dozent(frozenset(tokens)) is expected


# ----------------------------------------------------------------
# get_current_user
# ----------------------------------------------------------------
@pytest.mark.integration
def test_first_request_creates_the_user_row(db, dummy_auth):
    user = auth.get_current_user(_request({auth.DUMMY_AUTH_HEADER: "new@dhbw.de"}), db)

    assert user.email == "new@dhbw.de"
    assert user.username == "new"
    assert db.query(User).filter(User.email == "new@dhbw.de").count() == 1


@pytest.mark.integration
def test_later_requests_reuse_the_row(db, dummy_auth):
    first = auth.get_current_user(_request({auth.DUMMY_AUTH_HEADER: "same@dhbw.de"}), db)
    second = auth.get_current_user(_request({auth.DUMMY_AUTH_HEADER: "same@dhbw.de"}), db)

    assert first.userId == second.userId
    assert db.query(User).filter(User.email == "same@dhbw.de").count() == 1


@pytest.mark.integration
def test_rights_come_from_tokens(db, dummy_auth, monkeypatch):
    monkeypatch.setattr(settings, "APPSTORE_ADMIN_GROUPS", "group:appstore_admins, group:ops")
    monkeypatch.setattr(
        auth,
        "resolve_tokens",
        lambda email: frozenset({f"user:{email}", "group:ops", "group:wwi23seb#dozent"}),
    )

    user = auth.get_current_user(_request({auth.DUMMY_AUTH_HEADER: "boss@dhbw.de"}), db)

    assert user.is_admin is True
    assert user.is_dozent is True
    assert "group:wwi23seb#dozent" in user.tokens


@pytest.mark.integration
def test_plain_user_has_no_rights(db, dummy_auth, monkeypatch):
    monkeypatch.setattr(settings, "APPSTORE_ADMIN_GROUPS", "group:appstore_admins")

    user = auth.get_current_user(_request({auth.DUMMY_AUTH_HEADER: "s@dhbw.de"}), db)

    assert (user.is_admin, user.is_dozent) == (False, False)


# ----------------------------------------------------------------
# start-up guard
# ----------------------------------------------------------------
@pytest.mark.unit
def test_dummy_auth_outside_development_refuses_to_start():
    with pytest.raises(ValidationError, match="refusing to start"):
        Settings(DATABASE_URL="postgresql://x/y", API_DUMMY_AUTH=True, API_MODE="production")


@pytest.mark.unit
def test_dummy_auth_in_development_is_allowed():
    s = Settings(DATABASE_URL="postgresql://x/y", API_DUMMY_AUTH=True, API_MODE="development")
    assert s.API_DUMMY_AUTH is True


@pytest.mark.unit
def test_admin_tokens_are_parsed_from_a_comma_list():
    s = Settings(DATABASE_URL="postgresql://x/y", APPSTORE_ADMIN_GROUPS=" group:a , ,group:b")
    assert s.admin_tokens == frozenset({"group:a", "group:b"})
