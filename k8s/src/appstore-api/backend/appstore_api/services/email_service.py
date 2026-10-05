"""SMTP sender and Jinja2 renderer for the notification mails (plan E5).

* Delivery is on when ``SMTP_ENABLED`` is set and ``SMTP_HOST`` names a
  relay. Login is optional: the DHBW relay accepts mail from the cluster
  without one, so ``SMTP_USER``/``SMTP_PASSWORD`` are only used when set.
* Port 465 opens an implicit-TLS connection; any other port speaks plain
  SMTP and upgrades with STARTTLS unless ``SMTP_STARTTLS=false`` (a relay
  inside the cluster network that cannot do TLS).
* ``multipart/alternative`` with an HTML and a plain-text body. Templates
  live in ``templates/email/``.
* One connection per mail; the volume is one mail per member per deploy.

Failures are logged at ``warning`` and swallowed: a failed mail must never
roll back a successful deployment.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from appstore_api.config import settings

logger = logging.getLogger(__name__)


_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "email"

# HTML templates: autoescape, trim/lstrip blocks for clean indentation.
_jinja_html = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

# Plain-text templates: no autoescape (``&`` in a URL must stay ``&``), and no block stripping — Jinja's whitespace
# control removes critical newlines around ``{% if %}`` / ``{% for %}``
# blocks in plain text. Authors use ``{%- ... -%}`` explicitly when
# they want trimming.
_jinja_text = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=False,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def render(template_name: str, **context: Any) -> str:
    """Render a Jinja2 template with the given context.

    Picks the HTML or text environment based on the template's
    extension so plain-text templates aren't HTML-escaped and
    HTML templates still get tidy whitespace.
    """
    env = _jinja_text if template_name.endswith(".txt") else _jinja_html
    return env.get_template(template_name).render(**context)


def _from_address() -> str:
    """Envelope/From address: ``SMTP_FROM_EMAIL``, else the login user."""
    return settings.SMTP_FROM_EMAIL or settings.SMTP_USER


def is_smtp_enabled() -> bool:
    """Whether delivery is attempted at all; the predicate every caller uses.

    ``SMTP_ENABLED`` is the operator's switch; a relay host and a sender
    address must be configured as well. Without them delivery is skipped
    rather than failing on every mail. The resend endpoint checks this
    first so it can answer 503 ("we chose not to send") instead of 502.
    """
    return bool(settings.SMTP_ENABLED and settings.SMTP_HOST and _from_address())


def send_email(
    *,
    to: str | list[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> bool:
    """Send a multipart HTML+text mail over a fresh SMTP connection.

    ``to`` may be one address or several (one mail, all in ``To:``).
    Returns ``True`` on success, ``False`` if delivery is off, there are no
    recipients, or sending raised. Never raises.
    """
    if not is_smtp_enabled():
        logger.info("mail delivery is off (SMTP_ENABLED/SMTP_HOST/sender), skipping mail to %s", to)
        return False

    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        return False

    from_email = _from_address()

    msg = MIMEMultipart("alternative")
    # The subject carries the deployment name, which the caller chose; a
    # line break in it must not start a header of its own.
    msg["Subject"] = " ".join(subject.split())
    msg["From"] = formataddr((settings.SMTP_FROM_NAME, from_email))
    msg["To"] = ", ".join(recipients)
    # Plain part first: clients pick the *last* alternative they can render.
    msg.attach(MIMEText(text_body, "plain", _charset="utf-8"))
    msg.attach(MIMEText(html_body, "html", _charset="utf-8"))

    try:
        smtp: smtplib.SMTP
        if settings.SMTP_PORT == 465:
            smtp = smtplib.SMTP_SSL(
                settings.SMTP_HOST, settings.SMTP_PORT, timeout=30, context=ssl.create_default_context()
            )
        else:
            smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        with smtp:
            if settings.SMTP_PORT != 465 and settings.SMTP_STARTTLS:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.sendmail(from_email, recipients, msg.as_string())
        logger.info("sent mail to %s, subject=%r", recipients, subject)
        return True
    except Exception as e:
        # The whole message, so auth failure, timeout and a refused
        # recipient can be told apart without re-running the mail.
        logger.warning("failed to send mail to %s: %s", recipients, e)
        return False
