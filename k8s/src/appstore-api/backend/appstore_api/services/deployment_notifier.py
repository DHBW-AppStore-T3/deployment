"""Notification mails after a deploy (plan E5).

**No secrets in mails.** A mail is readable by anyone the address forwards
to, sits in mailboxes for years and is not revocable. So:

* every team member gets "Ihr Zugang ist bereit" with a link to "Meine
  Zugänge", where they see their own access data after signing in
  (``GET /deployments/{id}/my-access``);
* the owner gets a summary of the teams, member addresses and VM addresses,
  without passwords, keys or login links.

Both use the worker's OpenTofu outputs (``team_vms`` for the addresses; the
per-user ``user_accounts`` only for "Meine Zugänge") plus the deployment's
teams from the DB.

Failures are logged and never bubble up: sending mail is best-effort, the
deploy itself is already done. The finalizer calls this once per task (it
commits the task as finalized before sending), so a restart does not resend;
a crash mid-send loses mails instead, which the UI can resend.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from appstore_api.config import settings
from appstore_api.crud import deployments as crud_deployments
from appstore_api.models import App, Deployment, Team, User
from appstore_api.services import email_service

logger = logging.getLogger(__name__)


def my_access_url() -> str:
    """Where a member finds their access data; the route is the UI's (AP8)."""
    return f"{settings.APPSTORE_UI_URL.rstrip('/')}/appstore/my-access"


def deployment_url(deployment_id: UUID) -> str:
    """UI link to a deployment's detail page, used in the owner mail."""
    return f"{settings.APPSTORE_UI_URL.rstrip('/')}/appstore/deployments/{deployment_id}"


# ----------------------------------------------------------------------------
# Outputs parsing
# ----------------------------------------------------------------------------
#
# Worker tasks return ``terraform_outputs`` as the raw JSON object
# Terraform's ``output -json`` produces, i.e. each top-level key is an
# output name with ``{value, type, sensitive}`` underneath. We only care
# about the ``value`` of three well-known outputs from the Online-IDE
# template (and any template that follows the same conventions):
#
#   team_vms.value:
#     {
#       "Team-1": {
#         "code_server_url": "http://1.2.3.4:8080",
#         "floating_ip":     "1.2.3.4",
#         "fixed_ip":        "10.100.x.y",
#         "instance_id":     "uuid",
#         "instance_name":   "online-ide-Team-1"
#       },
#       ...
#     }
#
#   user_accounts.value:
#     {
#       "Team-1-luca": {
#         "auth":     "<password-or-key-or-login-url>",
#         "ip":       "1.2.3.4",
#         "port":     8080,
#         "type":     "password" | "ssh_key" | "oauth" | "none",
#         "username": "luca"
#       },
#       ...
#     }
#
#   ``type`` says what ``auth`` is: ``password``, ``ssh_key``, ``oauth``
#   (a login URL) or ``none``. The UI renders it on "Meine Zugänge"; mails
#   never carry it (plan E5).
#
#   teams_summary.value: {"Team-1": 1, ...}  — member counts; not used
#                                              directly but useful as a
#                                              sanity check.
#
# When a template doesn't expose one of these (e.g. an app without
# per-user credentials), the helpers return empty dicts and the mails
# and "Meine Zugänge" leave those parts out.


def _output_value(outputs: dict[str, Any] | None, key: str) -> Any:
    """Pluck ``outputs[key].value`` out, tolerating missing keys."""
    if not outputs:
        return None
    bag = outputs.get(key)
    if isinstance(bag, dict):
        return bag.get("value")
    return None


def _team_vms(outputs: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The ``team_vms`` output (team name -> VM info), or ``{}`` if absent/malformed."""
    val = _output_value(outputs, "team_vms")
    return val if isinstance(val, dict) else {}


def _user_accounts(outputs: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """The ``user_accounts`` output (account key -> entry), or ``{}`` if absent/malformed."""
    val = _output_value(outputs, "user_accounts")
    return val if isinstance(val, dict) else {}


def _normalise_account_key(value: str | None) -> str:
    """Normalise an account/username key for fuzzy matching.

    Worker templates derive Linux-friendly account names from emails
    by replacing every non-``[a-z0-9]`` character with a single ``-``.
    A user with email ``luca.baeck@gmail.com`` becomes ``luca-baeck``
    in the terraform output, while our DB has ``luca`` as the
    username and ``luca.baeck`` as the email's local-part. Comparing
    those literally misses every match where the template applied any
    transformation. We collapse ``.``/``-``/``_``/spaces to a single
    ``-`` and lowercase, so all four forms map to the same canonical
    string and the matcher succeeds without us having to know which
    transformation a given template applied.
    """
    if not value:
        return ""
    out = []
    for ch in value.strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in ".-_ ":
            out.append("-")
        # Other characters drop entirely.
    # Collapse runs of "-" into one so "a..b" and "a-b" both end up
    # as "a-b".
    canonical = "".join(out)
    while "--" in canonical:
        canonical = canonical.replace("--", "-")
    return canonical.strip("-")


def _find_account_for_user(
    outputs: dict[str, Any] | None,
    team_name: str,
    user: User,
) -> tuple[str, dict[str, Any]] | None:
    """Locate the user's raw account entry in the worker's outputs.

    Templates key per-user accounts as ``"<team>-<account-name>"``
    where ``<account-name>`` is some derivation of the user's email
    or username — the Online-IDE template, for example, takes the
    email's local-part and substitutes non-alphanumerics with ``-``.

    To find the right entry without coupling to one specific naming
    scheme we build a set of candidate identifiers from everything
    we know about the user (username, email local-part, full name)
    plus a normalised form of each, then walk every account in the
    output and check for any overlap. ``_normalise_account_key``
    makes ``luca.baeck``, ``luca-baeck`` and ``LUCA_BAECK`` all
    compare equal.

    Returns ``(key, raw_entry)`` on a match — the ORIGINAL output key
    alongside the untouched account dict — or ``None``. The
    ``/my-access`` response mirrors the terraform ``user_accounts`` shape,
    so it hands the raw entry on as it is.
    """
    accounts = _user_accounts(outputs)
    candidates_raw: set[str] = {
        user.username or "",
        (user.email or "").split("@")[0],
    }
    if user.firstName and user.lastName:
        candidates_raw.add(f"{user.firstName} {user.lastName}")
    candidates = {_normalise_account_key(c) for c in candidates_raw if c}
    candidates.discard("")

    for key, raw in accounts.items():
        if not isinstance(raw, dict):
            continue
        # Strip the team-name prefix when present so a key like
        # ``"Team-1-luca-baeck"`` becomes ``"luca-baeck"`` before
        # normalisation. The prefix itself is normalised the same
        # way so a team named ``"Team 1"`` (space) also matches.
        team_prefix = _normalise_account_key(team_name) + "-"
        normalised_key = _normalise_account_key(key)
        suffix = normalised_key[len(team_prefix):] if normalised_key.startswith(team_prefix) else normalised_key

        candidates_with_inner_username = candidates | {_normalise_account_key(raw.get("username"))}
        candidates_with_inner_username.discard("")

        if suffix in candidates_with_inner_username:
            return key, raw
    return None


def _vm_for_team(outputs: dict[str, Any] | None, team_name: str) -> dict[str, Any] | None:
    """The team's VM addresses, normalised to what the owner mail shows.

    Templates that emit ``url`` instead of ``code_server_url`` are
    tolerated; only addresses are picked, never anything credential-like.
    """
    raw = _team_vms(outputs).get(team_name)
    if not isinstance(raw, dict):
        return None
    return {
        "url": raw.get("code_server_url") or raw.get("url"),
        "floating_ip": raw.get("floating_ip"),
        "fixed_ip": raw.get("fixed_ip"),
        "instance_name": raw.get("instance_name"),
    }


# ----------------------------------------------------------------------------
# Senders
# ----------------------------------------------------------------------------


def _deployment_context(deployment: Deployment, app: App) -> dict[str, Any]:
    """Template variables describing the deployment (``deployment.*`` in both mails)."""
    return {
        "name": deployment.name,
        "git_url": app.git_link,
        "release_tag": deployment.releaseTag,
        "app_name": app.name,
    }


def _send_member_mail(*, member: User, teammates: list[User], team_name: str, deployment: Deployment, app: App) -> bool:
    """Send the "Ihr Zugang ist bereit" mail to ``member``.

    ``teammates`` is the whole team; the member is filtered out of the list
    shown in the mail. Returns whether SMTP accepted the mail.
    """
    ctx = {
        "teammates": [m.email for m in teammates if m.userId != member.userId],
        "team_name": team_name,
        "deployment": _deployment_context(deployment, app),
        "my_access_url": my_access_url(),
    }
    return email_service.send_email(
        to=member.email,
        subject=f"[{deployment.name}] Ihr Zugang ist bereit",
        html_body=email_service.render("user_invite.html", **ctx),
        text_body=email_service.render("user_invite.txt", **ctx),
    )


def _send_owner_mail(*, owner: User, deployment: Deployment, app: App, teams: list[dict[str, Any]]) -> bool:
    """Send the deployment summary to the owner.

    ``teams`` is ``[{"name", "vm" (see ``_vm_for_team``), "members": [e-mail]}]``.
    Returns whether SMTP accepted the mail.
    """
    ctx = {
        "deployment": _deployment_context(deployment, app),
        "teams": teams,
        "detail_url": deployment_url(deployment.deploymentId),
    }
    return email_service.send_email(
        to=owner.email,
        subject=f"[{deployment.name}] Deployment ist bereit",
        html_body=email_service.render("owner_summary.html", **ctx),
        text_body=email_service.render("owner_summary.txt", **ctx),
    )


def notify_deployment_succeeded(
    db: Session,
    deployment_id: UUID,
    terraform_outputs: dict[str, Any] | None,
) -> None:
    """Send the post-deploy mails; called by the task finalizer after a successful DEPLOY task.

    One mail per team member and one summary to the owner. Members get
    their mail whether or not the outputs carry an account for them: the
    link to "Meine Zugänge" is useful either way, and a template without
    per-user accounts is still a ready environment. Never raises: a missing
    deployment/app/owner or a failing mail is logged and skipped.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        logger.warning("notify: deployment %s not found", deployment_id)
        return

    app = deployment.app
    owner = deployment.user
    if not app or not owner:
        logger.warning("notify: deployment %s missing app or owner relation", deployment_id)
        return

    teams_payload: list[dict[str, Any]] = []
    for team in deployment.teams or []:
        members = crud_deployments.get_team_members(db, team.teamId)
        for member in members:
            try:
                _send_member_mail(member=member, teammates=members, team_name=team.name, deployment=deployment, app=app)
            except Exception as e:
                logger.warning("notify: member mail to %s for deployment %s failed: %s", member.email, deployment_id, e)
        teams_payload.append({
            "name": team.name,
            "vm": _vm_for_team(terraform_outputs, team.name),
            "members": [m.email for m in members],
        })

    try:
        _send_owner_mail(owner=owner, deployment=deployment, app=app, teams=teams_payload)
    except Exception as e:
        logger.warning("notify: owner mail for deployment %s failed: %s", deployment_id, e)


# ----------------------------------------------------------------------------
# Single-member resend
# ----------------------------------------------------------------------------


class ResendError(Exception):
    """Resend prerequisites weren't met (no successful deploy, user not in team)."""


def resend_user_access(db: Session, deployment_id: UUID, team_id: UUID, user_id: UUID) -> bool:
    """Send the "Ihr Zugang ist bereit" mail again, to one member.

    Raises ``ResendError`` when the deployment, team or member does not
    exist here, or no deploy has succeeded yet (there is nothing ready to
    point at). Returns whether SMTP accepted the mail.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        raise ResendError("deployment_not_found")
    app = deployment.app
    if not app:
        raise ResendError("deployment_app_missing")

    team: Team | None = next((t for t in (deployment.teams or []) if t.teamId == team_id), None)
    if team is None:
        raise ResendError("team_not_in_deployment")

    members = crud_deployments.get_team_members(db, team.teamId)
    user: User | None = next((m for m in members if m.userId == user_id), None)
    if user is None:
        raise ResendError("user_not_in_team")

    if crud_deployments.get_latest_successful_deploy_outputs(db, deployment_id) is None:
        raise ResendError("no_successful_deploy")

    try:
        return _send_member_mail(member=user, teammates=members, team_name=team.name, deployment=deployment, app=app)
    except Exception as e:
        logger.warning("resend: member mail to %s for deployment %s failed: %s", user.email, deployment_id, e)
        return False


# ----------------------------------------------------------------------------
# Per-member self-access lookup (read-only)
# ----------------------------------------------------------------------------


def get_user_access(
    db: Session,
    deployment_id: UUID,
    user_id: UUID,
) -> dict[str, Any] | None:
    """Return the terraform output slices a single member is allowed to see.

    Powers the ``GET /deployments/{id}/my-access`` endpoint: a team member
    (typically a student) may retrieve THEIR OWN access credentials without
    the owner-view that gates the full ``outputs`` payload. Only the caller's
    own account entry is ever returned — teammates' credentials are never
    included.

    The result mirrors the raw terraform ``user_accounts`` / ``team_vms``
    output shape (one key each: the member's account and their team's VM)
    so the frontend's existing account-matching pipeline consumes it
    unchanged:

        {"user_accounts": {"<key>": {...}}, "team_vms": {"<team>": {...}}}

    Returns ``None`` when the deployment is missing, the user isn't part of
    any of its teams, there's no successful deploy yet, or the deploy issued
    no per-user credential for this user. The router maps ``None`` onto an
    empty-map 200 response so the UI can render a clean "no credentials yet"
    state instead of an error.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        return None

    # Find which team of this deployment the user belongs to. We need the
    # Team (for its name, the account-key prefix) and the User object (its
    # identifiers drive the fuzzy account match). Mirrors the team/user
    # resolution in ``resend_user_access``.
    matched_team: Team | None = None
    matched_user: User | None = None
    for team in deployment.teams or []:
        members = crud_deployments.get_team_members(db, team.teamId)
        member = next((m for m in members if m.userId == user_id), None)
        if member is not None:
            matched_team = team
            matched_user = member
            break
    if matched_team is None or matched_user is None:
        return None

    outputs = crud_deployments.get_latest_successful_deploy_outputs(
        db, deployment_id
    )
    if outputs is None:
        return None

    match = _find_account_for_user(outputs, matched_team.name, matched_user)
    if match is None:
        return None

    key, raw = match
    # Return the RAW account entry keyed by its ORIGINAL output key so the
    # frontend's ``enrichedTeams`` matching (which derives the same key
    # from team + email) resolves it exactly as it does for the owner-view
    # ``user_accounts`` map. Include only the caller's own team VM block.
    result: dict[str, Any] = {"user_accounts": {key: raw}, "team_vms": {}}
    team_vm = _team_vms(outputs).get(matched_team.name)
    if isinstance(team_vm, dict):
        result["team_vms"][matched_team.name] = team_vm
    return result
