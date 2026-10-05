"""Unit tests for ``appstore_api.services.email_service``, without SMTP I/O.

* ``is_smtp_enabled()`` decides between 503 (delivery off) and 502 (relay
  refused) at the resend endpoint, so its truth table is pinned here.
* ``send_email()`` must not touch ``smtplib`` while delivery is off, must
  work against a relay without login (the DHBW relay), and must not let a
  line break in the subject start a header of its own.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from appstore_api.config import settings
from appstore_api.services import email_service


@pytest.fixture
def smtp_settings(monkeypatch):
    def apply(**values):
        base = {
            "SMTP_ENABLED": True,
            "SMTP_HOST": "relay.example",
            "SMTP_PORT": 25,
            "SMTP_STARTTLS": True,
            "SMTP_USER": "",
            "SMTP_PASSWORD": "",
            "SMTP_FROM_EMAIL": "appstore@example.org",
            "SMTP_FROM_NAME": "DHBW AppStore",
        }
        for key, value in {**base, **values}.items():
            monkeypatch.setattr(settings, key, value, raising=False)

    return apply


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        # A relay without login is complete.
        ({}, True),
        ({"SMTP_USER": "u@example.org", "SMTP_PASSWORD": "secret"}, True),
        # The operator's switch wins.
        ({"SMTP_ENABLED": False}, False),
        ({"SMTP_HOST": ""}, False),
        # No sender: neither SMTP_FROM_EMAIL nor a login to fall back to.
        ({"SMTP_FROM_EMAIL": ""}, False),
        ({"SMTP_FROM_EMAIL": "", "SMTP_USER": "u@example.org"}, True),
    ],
)
def test_is_smtp_enabled_truth_table(smtp_settings, values, expected):
    smtp_settings(**values)
    assert email_service.is_smtp_enabled() is expected


def _send(subject: str = "hi") -> bool:
    return email_service.send_email(
        to="recipient@example.org", subject=subject, html_body="<p>hi</p>", text_body="hi"
    )


@pytest.mark.parametrize("values", [{"SMTP_ENABLED": False}, {"SMTP_HOST": ""}])
def test_send_email_does_not_connect_when_off(smtp_settings, values):
    smtp_settings(SMTP_USER="u@example.org", SMTP_PASSWORD="secret", **values)
    with patch("smtplib.SMTP_SSL") as ssl_cls, patch("smtplib.SMTP") as plain_cls:
        assert _send() is False
    ssl_cls.assert_not_called()
    plain_cls.assert_not_called()


def test_relay_without_login(smtp_settings):
    smtp_settings()
    with patch("smtplib.SMTP") as plain_cls:
        smtp = plain_cls.return_value
        assert _send() is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_not_called()
    smtp.sendmail.assert_called_once()
    assert smtp.sendmail.call_args.args[0] == "appstore@example.org"


def test_relay_without_tls_and_with_login(smtp_settings):
    smtp_settings(SMTP_STARTTLS=False, SMTP_USER="u@example.org", SMTP_PASSWORD="secret")
    with patch("smtplib.SMTP") as plain_cls:
        smtp = plain_cls.return_value
        assert _send() is True
    smtp.starttls.assert_not_called()
    smtp.login.assert_called_once_with("u@example.org", "secret")


def test_port_465_is_implicit_tls(smtp_settings):
    smtp_settings(SMTP_PORT=465)
    with patch("smtplib.SMTP_SSL") as ssl_cls, patch("smtplib.SMTP") as plain_cls:
        smtp = ssl_cls.return_value
        assert _send() is True
    plain_cls.assert_not_called()
    smtp.starttls.assert_not_called()


def test_line_breaks_in_the_subject_do_not_become_headers(smtp_settings):
    smtp_settings()
    with patch("smtplib.SMTP") as plain_cls:
        smtp = plain_cls.return_value
        assert _send("[x]\r\nBcc: victim@example.org") is True
    raw = smtp.sendmail.call_args.args[2]
    assert "\nBcc:" not in raw
    assert smtp.sendmail.call_args.args[1] == ["recipient@example.org"]


def test_refusing_relay_is_false_not_an_exception(smtp_settings):
    smtp_settings()
    with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
        assert _send() is False
