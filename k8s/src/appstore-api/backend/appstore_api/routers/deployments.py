"""Deployments: create, read, lifecycle actions, resources, access and live stream.

Mounted under ``/deployments``. Creating a deployment or a lifecycle action
(destroy, pause, resume, per-VM redeploy) inserts a PENDING row into the task
queue (``services/task_service``) that the worker picks up; progress comes
back through ``task_events`` and is served here as SSE. Who may do what is
decided in ``utils/capabilities`` (owner view, member view, operate).
"""
import asyncio
import base64
import binascii
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from appstore_api.auth import get_current_user
from appstore_api.crud import app_version_approvals as crud_approvals
from appstore_api.crud import apps as crud_apps
from appstore_api.crud import deployments as crud_deployments
from appstore_api.crud import locks as crud_locks
from appstore_api.crud import openstack_credentials as crud_openstack_credentials
from appstore_api.crud import teams as crud_teams
from appstore_api.crud import users as crud_users
from appstore_api.database import SessionLocal, get_db
from appstore_api.models import Task as TaskModel  # for ad-hoc state queries
from appstore_api.models import TaskEvent, TaskStatus, TaskType, User
from appstore_api.schemas import (
    DeploymentCreate,
    DeploymentDetail,
    DeploymentOutputs,
    DeploymentPermissions,
    DeploymentResourceListResponse,
    DeploymentResourceSchema,
    DeploymentResponse,
    DeploymentTeamMember,
    DeploymentTeamResponse,
    LifecycleActionResponse,
    MyAccessResponse,
    PodWorkloadSchema,
    TaskSummary,
    UserResponse,
)
from appstore_api.services import (
    app_spec,
    courses,
    deployment_notifier,
    email_service,
    k8s_status,
    openstack_client,
    tf_state_store,
)
from appstore_api.services import lifecycle as lifecycle_service
from appstore_api.services import task_service as task_service_module
from appstore_api.services.deployment_status import (
    build_resource_detail,
    build_resource_views,
)
from appstore_api.services.tf_state_parser import parse_tf_state
from appstore_api.utils.capabilities import (
    can_operate_deployment,
    can_view_deployment_owner,
    ensure_deploy,
    ensure_operate_deployment,
    ensure_resend_access,
    ensure_teach_course,
    ensure_view_app,
    ensure_view_deployment_member,
    ensure_view_deployment_owner,
)
from appstore_api.utils.filenames import content_disposition, safe_filename
from appstore_shared.jobs import TERMINAL_EVENTS, JobPayload, redact_sensitive_outputs

logger = logging.getLogger(__name__)
router = APIRouter()


# ----------------------------------------------------------------
# GET ALL DEPLOYMENTS
# ----------------------------------------------------------------
@router.get("/", response_model=list[DeploymentResponse])
def list_deployments(
    skip: int = 0,
    limit: int = 100,
    app_id: UUID | None = None,
    status_filter: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List the deployments the caller owns, is a team member of, or shares a project with.

    Paged with ``skip``/``limit``, optionally filtered by ``app_id`` and
    derived status (``status_filter``). Uploaded file contents are stripped
    from ``userInputVar``; only their metadata is returned.
    The same for everyone: teachers see another teacher's deployments only
    in projects they have a credential for themselves (plan E2), and admins
    open other people's by link rather than getting the whole platform in
    one list.
    """
    deployments = crud_deployments.get_deployments(
        db,
        skip=skip,
        limit=limit,
        member_user_id=current_user.userId,
        peer_project_ids=crud_openstack_credentials.project_ids_of(db, current_user.userId),
        app_id=app_id,
        status=status_filter,
    )

    # Enrich with status and created_at from tasks. The summary is
    # bulk-fetched in two queries (latest + first task per deployment via
    # window functions) so the list endpoint stays at a constant query
    # count regardless of page size.
    task_summary = crud_deployments.bulk_get_task_summary(
        db, [d.deploymentId for d in deployments]
    )

    result = []
    for deployment in deployments:
        # Pull the latest-task ``(status, type)`` and the first-task
        # timestamp out of the bulk map. Deployments without any task
        # yet (new row, dispatch in flight) map to ``(None, None, None)``
        # — ``derive_status`` returns None for that, which the schema
        # accepts (``status: str | None``).
        latest_status, latest_type, first_created_at = task_summary.get(
            deployment.deploymentId, (None, None, None)
        )
        status_value = crud_deployments.derive_status(latest_status, latest_type)

        # Parse userInputVar JSON string back to dict if it exists.
        # File uploads are stripped down to metadata here so the list
        # view doesn't ship megabytes of base64 to the browser; the
        # detail endpoint follows the same rule, and the dedicated
        # download route is the only path that returns raw bytes.
        user_input_var_parsed = _parse_and_strip_user_input(deployment.userInputVar)

        result.append(DeploymentResponse(
            deploymentId=deployment.deploymentId,
            name=deployment.name,
            appId=deployment.appId,
            userId=deployment.userId,
            releaseTag=deployment.releaseTag,
            commit_sha=deployment.commit_sha,
            course=deployment.course,
            os_project_id=deployment.os_project_id,
            userInputVar=user_input_var_parsed,
            status=status_value,
            created_at=first_created_at,
        ))

    return result


# ----------------------------------------------------------------
# GET DEPLOYMENT BY ID (Full Details)
# ----------------------------------------------------------------
@router.get("/{deployment_id}", response_model=DeploymentDetail)
def get_deployment(
    deployment_id: UUID,
    include_logs: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get one deployment with owner, app, teams, latest task and outputs.

    Callers with the member view (team members) get only their own team(s)
    and no outputs or logs. Callers with the owner view (owner, project
    peers, admins) get every team, the non-sensitive OpenTofu outputs and,
    with ``include_logs=true``, the latest task's logs; students' own
    credentials come from ``/my-access`` instead. ``permissions`` tells the
    UI which view applies and whether the caller may operate it.
    404 when the deployment does not exist, 403 without the member view.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found"
        )

    # Check access permission
    ensure_view_deployment_member(current_user, deployment, db)

    # Get latest task
    latest_task = crud_deployments.get_latest_task(db, deployment_id)
    task_summary = None
    logs = None

    if latest_task:
        task_summary = TaskSummary(
            taskId=latest_task.taskId,
            type=latest_task.type,
            status=latest_task.status,
            started_at=latest_task.started_at,
            finished_at=latest_task.finished_at,
            created_at=latest_task.created_at,
            current_phase=getattr(latest_task, "current_phase", None),
            progress_pct=getattr(latest_task, "progress_pct", None),
        )
        if include_logs:
            logs = latest_task.logs

    # Get teams with members. The owner view sees every team and
    # every member. The member view only sees their own team(s) so
    # they can't browse who else has access to the deployment.
    is_owner_view = can_view_deployment_owner(current_user, deployment, db)
    teams_data = crud_deployments.get_deployment_teams_with_members(db, deployment_id)
    if not is_owner_view:
        teams_data = [
            t for t in teams_data
            if any(str(m["userId"]) == str(current_user.userId) for m in t["members"])
        ]
    teams = [
        DeploymentTeamResponse(
            teamId=team["teamId"],
            name=team["name"],
            members=[
                DeploymentTeamMember(
                    userId=member["userId"],
                    email=member["email"],
                    username=member["username"]
                )
                for member in team["members"]
            ]
        )
        for team in teams_data
    ]

    # Outputs / state / logs are owner-only — members don't get to
    # browse the credentials of teammates or the raw infrastructure
    # state. They have their own resend-access action for their own
    # credentials.
    if is_owner_view:
        # Sensitive outputs (the students' credentials) are left out: each
        # student sees their own through /my-access (plan E5).
        outputs_data = redact_sensitive_outputs(crud_deployments.get_deployment_outputs(db, deployment_id))
        outputs = DeploymentOutputs(raw=outputs_data) if outputs_data else None
    else:
        outputs = None
        logs = None

    # Get status and created_at from tasks
    status_value = crud_deployments.get_deployment_status(db, deployment_id)
    created_at = crud_deployments.get_deployment_created_at(db, deployment_id)

    # Parse userInputVar JSON string back to dict if it exists. Same
    # strip-file-bytes treatment as the list endpoint — base64
    # payloads are surfaced via the download route, not the JSON view.
    user_input_var_parsed = _parse_and_strip_user_input(deployment.userInputVar)

    # ``deployment.app`` is the raw ORM relation whose ``image`` column
    # carries bytes. Pydantic's ``DeploymentDetail`` declares
    # ``app.image: Optional[str]`` (the wire shape is a ``data:image/...``
    # URL), so handing it the bytes verbatim throws ``string_unicode``.
    # Run it through ``_serialize_app`` — the same helper the
    # ``/apps``-endpoints already use — to swap the bytes for the
    # data-URL string in place. Apps without an uploaded image are
    # unaffected (``getattr`` returns ``None`` and the helper no-ops).
    from appstore_api.routers.apps import _serialize_app  # local: avoid import cycle
    serialised_app = _serialize_app(deployment.app)

    return DeploymentDetail(
        permissions=DeploymentPermissions(
            owner_view=is_owner_view,
            operate=can_operate_deployment(current_user, deployment, db),
        ),
        deploymentId=deployment.deploymentId,
        name=deployment.name,
        appId=deployment.appId,
        userId=deployment.userId,
        releaseTag=deployment.releaseTag,
        commit_sha=deployment.commit_sha,
        course=deployment.course,
        os_project_id=deployment.os_project_id,
        userInputVar=user_input_var_parsed,
        status=status_value,
        created_at=created_at,
        user=UserResponse.model_validate(deployment.user),
        app=serialised_app,
        teams=teams,
        latest_task=task_summary,
        outputs=outputs,
        logs=logs,
    )


# ----------------------------------------------------------------
# CREATE DEPLOYMENT
# ----------------------------------------------------------------

# Defense-in-depth limits for inline file uploads. The UX-side warning
# is mirrored on the wizard, but a hand-crafted POST could still try
# to push GBs of payload through ``userInputVar``. We refuse before
# the row hits the DB.
#
# Per-file cap matches the existing app-image cap so users don't have
# to learn a second number; deployment-wide cap is 5× that, leaving
# headroom for (e.g.) one big assignment plus several small starter
# files. Both are enforced post-base64-decode so a malicious base64
# blob of right-shape but wrong-size still fails fast.
_MAX_FILE_BYTES_PER_FILE = 2 * 1024 * 1024
_MAX_FILE_BYTES_PER_DEPLOYMENT = 10 * 1024 * 1024


def _attach_files_to_user_input(
    user_input_var: dict | None,
    files: dict | None,
    variable_definitions: list[dict] | None = None,
) -> dict:
    """Validate and merge wizard-uploaded files into ``userInputVar``.

    The wizard ships files in a parallel ``files`` field instead of
    nesting them straight into ``userInputVar.terraform`` so the
    request payload's shape is obvious to a reader and so we can
    apply size / encoding validation in one place. Result is a fresh
    dict with the files folded into ``terraform[var_name]`` — the
    worker doesn't need to know they originally came from a separate
    field.

    Validation:
      * each top-level key in ``files`` becomes one terraform variable
      * each inner-map entry is one ``DeploymentFileUpload`` record
      * ``content_b64`` decodes cleanly (RFC 4648, padding optional)
      * decoded size matches the declared ``size`` (within rounding —
        client may have set it before encoding so we accept ±1)
      * per-file cap and total deployment cap
      * if ``variable_definitions`` are provided and a file variable
        declares ``fileExtensions``, each uploaded filename's suffix
        (lowercased, after the last dot) must be in the allowed list.
        Defense-in-depth: the wizard's ``accept`` attribute already
        filters in the picker, but a hand-crafted POST could bypass it.

    Raises ``HTTPException(413)`` for size violations and
    ``HTTPException(422)`` for malformed payload — Pydantic already
    rejected the obvious cases (missing fields, wrong types) before
    we get here, so we only catch what gets past it.
    """
    base = dict(user_input_var or {})
    base.setdefault("terraform", {})
    base.setdefault("packer", {})

    if not files:
        return base

    # Build an index var_name → allowed_extensions for the extension
    # check below. Variables without ``fileExtensions`` skip the
    # filter — keeps backward compatibility for any caller that doesn't
    # supply ``variable_definitions``.
    allowed_exts_by_var: dict[str, list[str]] = {}
    scoped_file_vars: set[str] = set()
    if variable_definitions:
        for vdef in variable_definitions:
            exts = vdef.get("fileExtensions")
            if exts:
                allowed_exts_by_var[vdef["name"]] = [e.lower() for e in exts]
            if vdef.get("varScope") in ("team", "user"):
                scoped_file_vars.add(vdef["name"])

    total_bytes = 0
    terraform_block = dict(base.get("terraform") or {})

    for var_name, slot_map in files.items():
        if var_name in terraform_block:
            # Wizard already routed something into this variable — a
            # collision means the frontend filled both the variables
            # picker AND the file uploader for the same name. That's an
            # unrecoverable contract violation; surface it clearly.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "reason": "file_var_collision",
                    "variable": var_name,
                },
            )
        if not isinstance(slot_map, dict) or not slot_map:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "file_var_empty", "variable": var_name},
            )

        encoded_slots: dict[str, dict] = {}
        for slot_key, upload in slot_map.items():
            # ``upload`` arrives here as a Pydantic model instance
            # already (FastAPI deserialised the request body into
            # ``DeploymentCreate``) — pull fields off attributes.
            content_b64 = upload.content_b64

            # Extension-filter check — only when the app author declared
            # an ``@openstack:file:<scope>:<exts>`` filter. We compare
            # the filename suffix (after the last dot, lowercased) to
            # the allowed list. Missing dot or unknown suffix → 422.
            # Stored and passed on sanitised: apps use it as a path on the
            # VM, the download route in a header (utils/filenames).
            upload_name = safe_filename(upload.name)
            allowed_exts = allowed_exts_by_var.get(var_name)
            if allowed_exts is not None:
                name = upload_name
                dot = name.rfind(".")
                suffix = name[dot + 1 :].lower() if dot >= 0 else ""
                if suffix not in allowed_exts:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "reason": "file_extension_rejected",
                            "variable": var_name,
                            "slot": slot_key,
                            "filename": upload.name,
                            "allowed": allowed_exts,
                        },
                    )
            try:
                # ``validate=True`` would reject any non-base64
                # whitespace; the wizard sends compact base64 so this
                # is fine.
                decoded = base64.b64decode(content_b64, validate=True)
            except (binascii.Error, ValueError) as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason": "file_b64_invalid",
                        "variable": var_name,
                        "slot": slot_key,
                        "error": str(e),
                    },
                )

            if abs(len(decoded) - upload.size) > 1:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason": "file_size_mismatch",
                        "variable": var_name,
                        "slot": slot_key,
                        "declared": upload.size,
                        "actual": len(decoded),
                    },
                )

            if len(decoded) > _MAX_FILE_BYTES_PER_FILE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={
                        "reason": "file_too_large",
                        "variable": var_name,
                        "slot": slot_key,
                        "limit_bytes": _MAX_FILE_BYTES_PER_FILE,
                        "actual_bytes": len(decoded),
                    },
                )
            total_bytes += len(decoded)
            if total_bytes > _MAX_FILE_BYTES_PER_DEPLOYMENT:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail={
                        "reason": "deployment_files_too_large",
                        "limit_bytes": _MAX_FILE_BYTES_PER_DEPLOYMENT,
                    },
                )

            encoded_slots[slot_key] = {
                "name": upload_name,
                "content_b64": content_b64,
                "size": upload.size,
                "content_type": upload.content_type or "application/octet-stream",
            }
        # scope=team|user: HCL type is map(map(object({...}))) —
        # outer key is the team/user slot, inner key is the upload slot.
        # scope=all: HCL type is map(object({...})) — flat map.
        if var_name in scoped_file_vars:
            terraform_block[var_name] = {
                slot_key: {"uploaded": file_obj}
                for slot_key, file_obj in encoded_slots.items()
            }
        else:
            terraform_block[var_name] = encoded_slots

    base["terraform"] = terraform_block
    return base


def _validate_scoped_user_input(
    user_input_var: dict | None,
    variable_definitions: list[dict],
    teams_payload: list,
) -> None:
    """Enforce that variables marked with ``varScope = team|user``
    arrive as a map whose keys match the deployment's team / user roster.

    Reasoning: the wizard packs scoped variables as a Map
    (``{slot_key: value, ...}``) and ships them via ``userInputVar``.
    A hand-crafted POST could ship arbitrary keys; we want unknown
    Scope-Targets to fail fast and loud before they hit Terraform,
    where the error would be a confusing "module: invalid for_each
    key" deep in the worker log.

    File variables are NOT skipped here — they share the same scoped
    map shape (``{slot_key: file_obj}``) and a hand-crafted POST could
    just as easily smuggle an unknown team name into a file-scope
    variable. We validate slot identity against the same roster; the
    per-file size / base64 / extension validation stays in
    :func:`_attach_files_to_user_input` because that's the layer that
    actually decodes the bytes.

    Raises ``HTTPException(422)`` with ``reason="unknown_scope_target"``,
    ``reason="scoped_var_not_map"``, or ``reason="required_slot_empty"``
    for shape/identity/completeness problems.
    """
    if not user_input_var:
        return

    # Compose the universe of valid slot keys per scope. ``team``
    # accepts any team name; ``user`` accepts ``TeamName-Username``
    # composites — mirror of ``userSlotKey`` in the wizard.
    team_names: set[str] = set()
    for team in teams_payload or []:
        team_name = getattr(team, "name", None) or (team.get("name") if isinstance(team, dict) else None)
        if not team_name:
            continue
        team_names.add(team_name)
        # User-scoped slots are ``f"{team_name}-{username}"`` with the
        # username derived by the wizard. We accept any non-empty
        # composite key prefix-matching ``f"{team_name}-"``; that is
        # enough to catch typos and cross-team key smuggling.

    # Longest-prefix-match helper for user-scope composite keys:
    # ``TeamName-Username``. A naive ``slot_key.find('-')`` would
    # truncate a team named ``Team-A`` to just ``Team``, so any team
    # name containing a dash would be misclassified as unknown. We
    # iterate the known team names from longest to shortest and pick
    # the first one that either equals ``slot_key`` (empty username,
    # rejected below) or prefixes it as ``f"{team}-"``.
    teams_by_length = sorted(team_names, key=len, reverse=True)

    def _user_slot_team_prefix(slot_key: str) -> str | None:
        """The team a user-scope slot key belongs to (longest match), or None."""
        for team in teams_by_length:
            if slot_key == team:
                # No trailing ``-Username`` — caller treats this as a
                # missing-user-segment and surfaces ``unknown_scope_target``.
                return team
            if slot_key.startswith(team + "-"):
                return team
        return None

    def _is_empty_slot_value(val) -> bool:
        """Treat None, empty string, empty list, and empty dict as
        "slot not filled". The wizard would otherwise let a required
        team/user-scoped var slip through with one team left blank,
        which Terraform would catch with a much less actionable
        ``Inappropriate value for attribute`` deep in the worker log.
        """
        if val is None:
            return True
        if isinstance(val, str) and val == "":
            return True
        return isinstance(val, (list, dict)) and len(val) == 0

    for source_key in ("terraform", "packer"):
        block = user_input_var.get(source_key)
        if not isinstance(block, dict):
            continue
        for vdef in variable_definitions:
            if vdef.get("source") != source_key:
                continue
            scope = vdef.get("varScope")
            if scope not in ("team", "user"):
                continue
            var_name = vdef["name"]
            value = block.get(var_name)
            is_file = vdef.get("osType") == "file"
            required = bool(vdef.get("required"))
            if value is None:
                # File-scope vars MUST be present — the wizard always
                # ships at least an empty map for them, so a None here
                # is a hand-crafted-POST shape. For non-file required
                # scoped vars, raise on the slot-completeness check
                # below by treating the absent value as an empty map.
                if required:
                    value = {}
                else:
                    continue  # variable left at HCL default — allowed
            if not isinstance(value, dict):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "reason": "scoped_var_not_map",
                        "variable": var_name,
                        "scope": scope,
                    },
                )
            for slot_key in value:
                if scope == "team":
                    if slot_key not in team_names:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={
                                "reason": "unknown_scope_target",
                                "variable": var_name,
                                "scope": scope,
                                "slot": slot_key,
                                "allowed": sorted(team_names),
                            },
                        )
                else:  # user scope
                    # Longest-prefix-match against known team names so
                    # a team named ``Team-A`` parses to prefix
                    # ``Team-A`` and rest ``Username`` instead of
                    # prefix ``Team`` (which wouldn't be a known team).
                    prefix = _user_slot_team_prefix(slot_key)
                    if prefix is None or slot_key == prefix:
                        raise HTTPException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail={
                                "reason": "unknown_scope_target",
                                "variable": var_name,
                                "scope": scope,
                                "slot": slot_key,
                                "hint": "expected ``TeamName-Username``",
                            },
                        )

            # Required slot-completeness check: for required team /
            # user scoped variables every expected slot key must carry
            # a non-empty value. Without this an empty map (or one
            # team left blank) would silently pass here and only fail
            # downstream with an opaque Terraform error.
            #
            # File vars are skipped from the completeness sweep — the
            # per-file size/decode validation in
            # :func:`_attach_files_to_user_input` raises a more specific
            # error (file_var_empty / file_b64_invalid) for them. We
            # only checked slot identity above; the bytes themselves
            # are validated at that layer.
            if required and not is_file:
                expected_slots: set[str] = set()
                if scope == "team":
                    expected_slots = set(team_names)
                # For ``user`` scope we don't have the per-team member
                # roster here (would need a DB round-trip we already
                # avoid above), so we only enforce that each slot the
                # caller did ship carries a non-empty value. The
                # wizard's frontend check is the primary guard; this
                # is defense-in-depth against hand-crafted POSTs that
                # ship one half-filled team. A POST that omits a team
                # entirely for a required user-scope var is caught by
                # the team-scope branch via team_names because the
                # wizard always emits at least one slot per team.

                missing: list[str] = []
                for slot in expected_slots:
                    if _is_empty_slot_value(value.get(slot)):
                        missing.append(slot)
                # Also flag empty values among slots the caller did
                # provide — covers user-scope and any partial-fill case.
                for slot, val in value.items():
                    if _is_empty_slot_value(val) and slot not in missing:
                        missing.append(slot)
                if missing:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail={
                            "reason": "required_slot_empty",
                            "variable": var_name,
                            "scope": scope,
                            "missing_slots": sorted(missing),
                        },
                    )


def _strip_file_vars_from_user_input(user_input_var: dict | None) -> dict | None:
    """Strip per-file ``content_b64`` payloads from a userInputVar dict.

    Used by the deployment detail responses so the JSON the frontend
    receives only carries metadata (name/size/content_type) — the
    decoded bytes can be many MBs each and shipping them on every
    page render is wasteful. Owners who actually want the file fetch
    it via the dedicated download endpoint.

    Heuristic-based: a variable is a file slot when its value is a
    mapping whose entries each carry a ``content_b64`` field — the
    same shape ``_attach_files_to_user_input`` writes. We match on
    that key because no other user-input kind uses it.
    """
    if not isinstance(user_input_var, dict):
        return user_input_var

    out = {k: v for k, v in user_input_var.items() if k != "terraform"}
    tf_block = user_input_var.get("terraform")
    if not isinstance(tf_block, dict):
        if "terraform" in user_input_var:
            out["terraform"] = tf_block
        return out

    stripped_tf: dict = {}
    for var_name, value in tf_block.items():
        if _looks_like_file_var(value):
            stripped_tf[var_name] = _file_var_metadata_only(value)
        else:
            stripped_tf[var_name] = value
    out["terraform"] = stripped_tf
    return out


def _parse_and_strip_user_input(raw: str | None) -> dict | None:
    """Parse a stored ``userInputVar`` JSON string and strip file bytes.

    Wraps the ``json.loads`` → :func:`_strip_file_vars_from_user_input`
    chain (with a malformed-JSON guard) shared by the list, detail, and
    create responses so all three surface the same file-stripped shape.
    Returns ``None`` for an empty or unparseable value.
    """
    if not raw:
        return None
    try:
        return _strip_file_vars_from_user_input(json.loads(raw))
    except json.JSONDecodeError:
        return None


def _looks_like_file_var(value) -> bool:
    """True if ``value`` matches the file-upload shape produced by
    :func:`_attach_files_to_user_input`: a non-empty mapping whose
    values are objects carrying ``content_b64`` plus the metadata
    triplet. Used at response-shaping time to identify file-typed
    variables without consulting the app's variable schema, AND at
    lifecycle-dispatch time (destroy/pause/resume/redeploy) to drop
    file vars from the worker's var-set so Terraform's schema
    validation doesn't trip on a payload it doesn't need.

    Shape examples it matches (and only these):

    * ``scope=all``   → ``{"all": {name, content_b64, size, content_type}}``
    * ``scope=team``  → ``{"Team-1": {...}, "Team-2": {...}}``
    * ``scope=user``  → ``{"Team-1-luca": {...}, ...}``

    Strict signature: each slot must carry ``content_b64``. Rows
    that survived an earlier response-side-strip-then-persisted
    accident (metadata triplet only, no bytes) are NOT auto-
    detected — clean them up by hand (delete the deployment row +
    its ``terraform_states`` row). The strictness is intentional:
    a lenient detector would silently swallow legitimate non-file
    map variables that coincidentally share the metadata key names.
    """
    if not isinstance(value, dict) or not value:
        return False
    for slot in value.values():
        if not isinstance(slot, dict):
            return False
        if "content_b64" not in slot:
            return False
    return True


def _file_var_metadata_only(value: dict) -> dict:
    """Return a copy of a file-shape variable with the ``content_b64``
    payload stripped. Metadata fields (name, size, content_type)
    survive so the UI can list "what was uploaded" without shipping
    base64 megabytes on every detail-view render.
    """
    out: dict = {}
    for slot_key, slot in value.items():
        out[slot_key] = {k: v for k, v in slot.items() if k != "content_b64"}
    return out


# ----------------------------------------------------------------
# CREATE DEPLOYMENT
# ----------------------------------------------------------------
@router.post("/", response_model=DeploymentResponse, status_code=status.HTTP_201_CREATED)
def create_deployment(
    deployment: DeploymentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a deployment of an app version for a course and queue its deploy job (201).

    Only a dozent of ``course`` may call it, with one of their own
    credentials (``credentialId``); the deployment lives in that
    credential's project. A public app deploys only approved versions; a
    private app only by its owner. Team members are given by e-mail and
    must be students of the course. Uploaded files (``files``) are
    validated and folded into ``userInputVar.terraform``.

    Notable errors: 403 (not a dozent of the course, app not visible,
    ``version_not_approved``), 404 ``app_not_found_or_deleted``, 412
    ``openstack_credentials_missing``, 413 file too large, 422 invalid
    uploads or scoped variables, 409 when a task is already active, 502
    when the app repository cannot be read to check the variables.

    Atomicity: a per-user advisory lock serializes credential mutation
    with deployment dispatch. The deployment row, teams, user mappings,
    and the initial PENDING task row are all inserted in a single
    transaction, so the user can never end up with a deployment row
    that has no matching task — and committing the task row is what
    queues it for the worker.
    """
    # Per-user lock — serializes against POST/DELETE /me/openstack-credentials
    # and any other concurrent POST /deployments from this user. Held
    # until the next COMMIT/ROLLBACK on this connection.
    crud_locks.acquire_user_xact_lock(db, current_user.userId)

    ensure_deploy(current_user)
    ensure_teach_course(current_user, deployment.course)

    # VM apps live in the project of the credential the caller picked; it
    # must be theirs. Read inside the locked TX, so a concurrent change of
    # the credential is serialized behind us. Pod apps need none (checked
    # below, once the version is known).
    credential = (
        crud_openstack_credentials.get_owned(db, current_user.userId, deployment.credentialId)
        if deployment.credentialId is not None
        else None
    )
    if deployment.credentialId is not None and credential is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"reason": "openstack_credentials_missing"},
        )

    # Refuse the create if the target app is soft-deleted.
    target_app = crud_apps.get_app(db, deployment.appId)
    if target_app is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "app_not_found_or_deleted"},
        )

    # Gate the create on the same visibility rule the list/detail
    # endpoints use. A student cannot deploy a private app they don't
    # own, and a non-owner cannot deploy an app without an approved
    # version. The owner / admin path stays open.
    # ``ensure_view_app`` raises 403 with the structured payload, so
    # the frontend receives the same shape it sees on the detail
    # endpoint when visibility is denied.
    ensure_view_app(current_user, target_app, db=db)

    # Pin the commit. A public app deploys only versions an admin approved
    # for exactly this commit; a private app is its owner's test bench and
    # deploys any tag (plan E6). ensure_view_app already keeps others out
    # of private apps.
    from appstore_api.routers.apps import load_version_spec, resolve_version_commit

    commit_sha = resolve_version_commit(target_app, deployment.releaseTag)
    if not target_app.is_private and not crud_approvals.has_approved_version(
        db, target_app.appId, deployment.releaseTag, commit_sha
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "version_not_approved", "version": deployment.releaseTag},
        )

    # Pod apps (appstore.yaml at the pinned commit) skip the OpenStack steps.
    # A public app's runtime is on its approval, so VM apps cost no extra
    # clone; a private app has no approval and is looked at directly.
    approval = crud_approvals.get_approval(db, target_app.appId, deployment.releaseTag)
    if target_app.is_private or (approval is not None and approval.runtime == app_spec.RUNTIME_K8S):
        loaded_spec = load_version_spec(target_app, deployment.releaseTag, commit_sha)
    else:
        loaded_spec = None
    is_k8s = loaded_spec is not None and loaded_spec.runtime == app_spec.RUNTIME_K8S
    if is_k8s:
        credential = None  # pods never use an OpenStack credential, even a supplied one
        # Approval = commit + spec hash + image digests: the spec read just
        # now must be the reviewed one.
        if not target_app.is_private and (
            approval is None or approval.spec_sha256 != loaded_spec.sha256
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "version_not_approved", "version": deployment.releaseTag},
            )
    elif credential is None:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail={"reason": "openstack_credentials_missing"},
        )

    # Load the app author's variable declarations so we can enforce
    # per-variable contracts (``varScope``, ``fileExtensions``) below.
    # We only do this when the request actually carries variables /
    # files — for a no-input deploy the round-trip into Git would be
    # waste. Same parser as ``GET /apps/{id}/variables`` so client and
    # server agree on which variable is scoped/file/free-text.
    variable_definitions: list[dict] = []
    if deployment.userInputVar or deployment.files:
        from appstore_api.routers.apps import load_variable_definitions
        # Exactly the pinned commit; an unreadable repository refuses the
        # deploy (502) instead of skipping the per-variable checks — the
        # worker could not clone it either.
        variable_definitions = load_variable_definitions(
            target_app, deployment.releaseTag, commit_sha
        )

    # Fold the wizard's parallel ``files`` upload into
    # ``userInputVar.terraform`` before the row gets persisted, so the
    # rest of this handler — and the worker downstream — sees one
    # uniform dict. The helper validates base64 / size / per-file and
    # per-deployment caps; any failure short-circuits with a 4xx and
    # the row never enters the DB. When variable definitions are
    # available, the helper also enforces the app author's declared
    # ``fileExtensions`` filter on each upload name.
    deployment.userInputVar = _attach_files_to_user_input(
        deployment.userInputVar, deployment.files, variable_definitions or None,
    )

    # Enforce ``varScope = team|user`` contracts: each value must be a
    # map whose keys match the deployment's team / user roster. This
    # is defense-in-depth — the wizard already only renders slots the
    # user can fill, but a hand-crafted POST could ship unknown keys.
    if variable_definitions:
        _validate_scoped_user_input(
            deployment.userInputVar,
            variable_definitions,
            deployment.teams or [],
        )

    # Members by address, all students of the course and each in one team
    # (plan AP4). Checked before anything is written; the role provider is
    # asked once per deploy.
    course_teams = [(team.name, team.emails) for team in deployment.teams]
    courses.ensure_team_members(deployment.course, course_teams)

    db_deployment = crud_deployments.create_deployment(
        db,
        deployment,
        current_user.userId,
        commit_sha,
        credential.project_id if credential is not None else app_spec.K8S_PROJECT,
        runtime=app_spec.RUNTIME_K8S if is_k8s else app_spec.RUNTIME_VM,
    )

    users_by_email = crud_users.ensure_users(
        db, sorted({email for _name, emails in course_teams for email in emails})
    )
    if deployment.teams:
        crud_teams.create_teams_for_deployment(
            db=db,
            deployment_id=db_deployment.deploymentId,
            teams_data=[
                {"name": name, "userIds": [users_by_email[e].userId for e in emails]}
                for name, emails in course_teams
            ],
        )
    if users_by_email:
        crud_deployments.create_user_to_deployments(
            db=db,
            deployment_id=db_deployment.deploymentId,
            user_ids={u.userId for u in users_by_email.values()},
        )

    # Parse user input variables
    try:
        user_vars = (
            json.loads(db_deployment.userInputVar) if db_deployment.userInputVar else {}
        )
    except Exception:
        user_vars = {}

    # Teams for OpenTofu: team name -> [{"email": ...}]
    teams_dict = {name: [{"email": e} for e in emails] for name, emails in course_teams}

    # The envelope carries ciphertext only — the worker decrypts in-process.
    # Pod deployments have no OpenStack credential.
    openstack_envelope = crud_openstack_credentials.dispatch_envelope(credential) if credential is not None else {}
    job_payload: JobPayload = {
        "app_id": str(db_deployment.appId),
        "app_git_link": db_deployment.app.git_link or "",
        "release": db_deployment.releaseTag or "",
        "commit_sha": db_deployment.commit_sha,
        "user_vars": user_vars,
        "teams": teams_dict,
        "openstack_envelope": openstack_envelope,
    }
    if is_k8s:
        job_payload["runtime"] = app_spec.RUNTIME_K8S
        job_payload["spec"] = loaded_spec.spec.model_dump(mode="json", by_alias=True, exclude_none=True)
        job_payload["course"] = db_deployment.course
        job_payload["owner"] = current_user.email

    # Insert the PENDING task row in the SAME transaction as the
    # deployment and commit everything at once (deployment + teams +
    # user_to_deployments + task). The commit is the hand-over: a worker
    # picks the task up from the table.
    _commit_task(
        db,
        deployment_id=db_deployment.deploymentId,
        task_type=TaskType.DEPLOY,
        payload=job_payload,
        rollback_on_conflict=True,
    )

    db.refresh(db_deployment)

    status_value = crud_deployments.get_deployment_status(db, db_deployment.deploymentId)
    created_at = crud_deployments.get_deployment_created_at(db, db_deployment.deploymentId)

    # Same file-strip rule as the list/detail endpoints: the POST
    # response shape mirrors the read shape so the frontend can reuse
    # the same parsing code-path.
    user_input_var_parsed = _parse_and_strip_user_input(db_deployment.userInputVar)

    return DeploymentResponse(
        deploymentId=db_deployment.deploymentId,
        name=db_deployment.name,
        appId=db_deployment.appId,
        userId=db_deployment.userId,
        releaseTag=db_deployment.releaseTag,
        commit_sha=db_deployment.commit_sha,
        course=db_deployment.course,
        os_project_id=db_deployment.os_project_id,
        userInputVar=user_input_var_parsed,
        status=status_value,
        created_at=created_at,
    )


# ----------------------------------------------------------------
# DELETE DEPLOYMENT
# ----------------------------------------------------------------
#
# One endpoint, two outcomes — the backend picks the right one from
# the deployment's status:
#
#   * ``success`` / ``failed`` / ``paused`` → dispatch a Destroy task
#     (terraform destroy + auto-soft-delete on success). ``paused`` is
#     in the destroy set because SHUTOFF instances + volumes/networks
#     are still OpenStack resources that need to be reclaimed.
#     Returns 202 + task_id; the frontend keeps the live stream open
#     and routes back to the list when the task finishes.
#   * ``cancelled``             → soft-delete immediately. Returns 204.
#   * any other status (running / pending / destroying / pausing / resuming)
#                               → 409, the user has to wait.
#
# Frontend doesn't have to know the difference — it just calls DELETE
# and switches into the live-stream view when the response is 202.
@router.delete(
    "/{deployment_id}",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LifecycleActionResponse,
    responses={204: {"description": "A cancelled deployment, removed at once"}},
)
def delete_deployment(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a deployment, destroying its OpenStack resources first if needed.

    Takes the operate right (owner or project peer, with their own
    credential). Members can read the deployment but never tear it down.
    202 with ``{task_id, status: "destroying"}`` when a destroy job was
    queued (the row is soft-deleted once it succeeds); 204 when there was
    nothing to destroy; 409 while another task is active; 403
    ``openstack_credentials_missing_for_project`` without an own credential
    for the deployment's project.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )

    # Destructive operation — uses the operate gate (owner or project peer).
    ensure_operate_deployment(current_user, deployment, db)

    # Per-deployment advisory lock — serialises against any concurrent
    # POST /pause, /resume or DELETE on the same deployment so the
    # ``current_status`` read below and the eventual
    # ``prepare_task_in_tx`` insert see a consistent picture. Without
    # this, two concurrent destroys could both pass the in-flight check
    # and one would crash on the partial unique index.
    crud_locks.acquire_deployment_xact_lock(db, deployment_id)

    current_status = crud_deployments.get_deployment_status(db, deployment_id)

    # Active task in flight — neither path is safe.
    if current_status in lifecycle_service.IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot delete a deployment in status '{current_status}'. "
                "Wait for the active task to finish."
            ),
        )

    # Resources may exist — destroy them first; the listener will
    # auto-soft-delete the row when the destroy task succeeds. ``paused``
    # also lands here: SHUTOFF instances + volumes/networks are still
    # OpenStack resources that need to be torn down before the row can
    # be hidden. ``pause_failed`` / ``resume_failed`` likewise still
    # have running OpenStack resources behind them — the deployment
    # itself didn't break, only the lifecycle pass.
    if current_status in ("success", "failed", "paused", "pause_failed", "resume_failed", "redeploy_failed"):
        return _dispatch_destroy(db, deployment, current_user)

    # No resources to clean up (cancelled, or anything else terminal):
    # straight soft-delete.
    success = crud_deployments.soft_delete_deployment(db, deployment_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _fetch_dispatch_envelope(db: Session, user: User, deployment) -> dict:
    """The caller's own credential envelope for the deployment's project.

    Lifecycle actions run with the credential of whoever triggers them,
    never with the owner's (plan E2); without one for the project the
    action is refused with 403 ``openstack_credentials_missing_for_project``.
    """
    row = openstack_client.project_credential(db, user, deployment.os_project_id)
    return crud_openstack_credentials.dispatch_envelope(row)


def _commit_task(
    db: Session,
    *,
    deployment_id,
    task_type: TaskType,
    payload: JobPayload,
    rollback_on_conflict: bool,
):
    """Insert the PENDING task in-TX and commit, which queues it.

    Shared tail of the create and lifecycle paths:
    ``prepare_task_in_tx`` → ``HTTPException(409)`` on an active task
    (the create path additionally rolls back its pending insert).

    Returns the committed ``Task``.
    """
    try:
        task = task_service_module.prepare_task_in_tx(
            db,
            deployment_id=deployment_id,
            task_type=task_type,
            payload=payload,
        )
    except task_service_module.ActiveTaskExistsError:
        if rollback_on_conflict:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deployment already has an active task",
        )

    db.commit()
    db.refresh(task)
    return task


def _dispatch_destroy(db: Session, deployment, current_user: User):
    """Enqueue the destroy worker task for a deployment (202 ``destroying``).

    Thin wrapper around :func:`_dispatch_lifecycle_task` that keeps the
    DELETE handler short.
    """
    return _dispatch_lifecycle_task(
        db,
        deployment,
        current_user,
        task_type=TaskType.DESTROY,
        response_status="destroying",
    )


def _dispatch_lifecycle_task(
    db: Session,
    deployment,
    current_user: User,
    task_type: TaskType,
    response_status: str,
    resource_address: str | None = None,
):
    """Enqueue any post-deploy lifecycle worker task for a deployment.

    Used by destroy, pause, resume, and per-VM redeploy — all four
    follow the same pattern: load user inputs, gather team membership,
    fetch the encrypted OpenStack envelope, then insert and commit a
    PENDING task row carrying all of it for the worker.

    Args:
        task_type:           the ``TaskType`` enum value that drives both
                             the task row's ``type`` column and the
                             status the partial-unique index prevents
                             from coexisting.
        response_status:     synthetic deployment status returned to the
                             frontend in the 202 body — frontend uses
                             this to immediately switch the UI into the
                             live-stream view without re-fetching.
        resource_address:    REDEPLOY only — the state address of the
                             instance to replace.
    """
    try:
        user_vars = json.loads(deployment.userInputVar) if deployment.userInputVar else {}
    except Exception:
        user_vars = {}

    # Belt + braces: for lifecycle tasks that do NOT recreate the VM
    # (destroy, pause, resume), strip any ``@openstack:file:*`` payloads
    # from the user-vars BEFORE they reach the worker. Files are only
    # consumed at apply-time by cloud-init's write_files; everything
    # else just hands the same var-set to Terraform which then
    # validates the entire variable surface against the HCL schema.
    # A row whose ``content_b64`` was stripped by a response-side
    # ``_strip_file_vars_from_user_input`` pass (e.g. after a manual
    # DB edit, an in-place row shrink, or any future code path that
    # rewrites the persisted JSON) would otherwise crash destroy with
    # ``element "all": attributes "content_b64", "content_type",
    # "name", and "size" are required`` because the surviving slot
    # violates the variable's object type. Dropping the var
    # altogether lets Terraform fall back on the HCL default.
    #
    # REDEPLOY is the special case: ``terraform apply -replace`` destroys
    # and recreates the VM, so cloud-init runs fresh and MUST receive the
    # original ``write_files`` payload — otherwise the replaced VM ends
    # up empty even though the user/group/password config is preserved.
    # We therefore keep the file vars on REDEPLOY and let the persisted
    # base64 payload flow through to the worker, mirroring the initial
    # deploy path.
    #
    # DEPLOY/UPDATE legitimately need the file bytes too — they don't
    # enter the worker via this helper.
    if task_type in (TaskType.DESTROY, TaskType.PAUSE, TaskType.RESUME):
        terraform_block = user_vars.get("terraform")
        if isinstance(terraform_block, dict):
            user_vars = {
                **user_vars,
                "terraform": {
                    k: v
                    for k, v in terraform_block.items()
                    if not _looks_like_file_var(v)
                },
            }

    teams_dict: dict = {}
    if deployment.teams:
        # Persisted Team rows expose membership via the ``user_to_teams``
        # association, not a flat ``userIds`` field — that lives on the
        # request-side Pydantic schema in the create endpoint, not on
        # the ORM. ``get_team_members`` does the join for us.
        for team in deployment.teams:
            members = crud_deployments.get_team_members(db, team.teamId)
            teams_dict[team.name] = [{"email": m.email} for m in members]

    is_k8s = deployment.runtime == app_spec.RUNTIME_K8S
    openstack_envelope = {} if is_k8s else _fetch_dispatch_envelope(db, current_user, deployment)

    payload: JobPayload = {
        "app_id": str(deployment.appId),
        "app_git_link": deployment.app.git_link or "",
        "release": deployment.releaseTag or "",
        "commit_sha": deployment.commit_sha,
        "user_vars": user_vars,
        "teams": teams_dict,
        "openstack_envelope": openstack_envelope,
    }
    if is_k8s:
        payload["runtime"] = app_spec.RUNTIME_K8S
    if resource_address is not None:
        payload["resource_address"] = resource_address
    task = _commit_task(
        db,
        deployment_id=deployment.deploymentId,
        task_type=task_type,
        payload=payload,
        rollback_on_conflict=False,
    )

    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"task_id": str(task.taskId), "status": response_status},
    )


# ----------------------------------------------------------------
# INFRASTRUCTURE RESOURCES (per-deployment status + per-VM redeploy)
# ----------------------------------------------------------------
#
# Three sibling endpoints power the Infrastructure tab on the
# deployment detail page:
#
#   * GET /{deployment_id}/resources?refresh=…
#       Stage-1 listing — parses the cached TF state and (default)
#       overlays live OpenStack lifecycle/hardware/addresses per VM.
#       Returns a flat list spanning compute, network, subnet, SG,
#       FIP, and port categories.
#
#   * GET /{deployment_id}/resources/{address}
#       Stage-2 detail — same shape, plus ports/SG-summary/volumes/
#       metadata for ONE compute instance, identified by its TF state
#       address (e.g. ``openstack_compute_instance_v2.team_ide["Team-A"]``).
#       Frontend loads this lazily when the user opens a card's drawer.
#
#   * POST /{deployment_id}/resources/{address}/redeploy
#       Per-VM redeploy — issues ``terraform apply -replace=<addr>
#       -target=<addr>`` in a dedicated worker job. Strictly
#       address-whitelisted against the cached TF state and the
#       compute-instance category, so a hand-crafted POST can't smuggle
#       a network-resource target (which would tear down all team VMs).
#
# All three are owner-only — the data exposed (live OpenStack status,
# the ability to bounce a VM) is not something a teammate should be
# able to access through the deployment detail page.


# We accept the same Terraform address vocabulary the user would type
# on ``terraform apply -target=``: ``type.name`` with optional
# ``[<int>]`` or ``["<string>"]`` suffix. Multiple address segments
# (modules, nested resources) aren't supported by the current apps,
# so we keep the regex strict to make smuggling impossible. The
# resource-existence whitelist below is the real defense; the regex
# is just a fast no-op rejection for obviously bad inputs (e.g.
# pipes, semicolons, spaces).
_TF_ADDRESS_RE = re.compile(
    r"""^
    [A-Za-z_][A-Za-z0-9_]*       # provider type (e.g. openstack_compute_instance_v2)
    \.[A-Za-z_][A-Za-z0-9_-]*    # resource name (e.g. team_ide)
    (?:
        \[(?:\d+|"[^"\\]+")\]    # optional index ([0] or ["Team-A"])
    )?
    $""",
    re.VERBOSE,
)


# A workload name, optionally prefixed ``reset:`` (also delete its volume).
_WORKLOAD_ADDRESS_RE = re.compile(r"^(reset:)?[a-z0-9][a-z0-9-]{0,62}$")


def _latest_tf_state_for(deployment_id: UUID, db: Session) -> str | None:
    """The deployment's OpenTofu state as JSON, or None before the first apply.

    Read from the state backend's own table (plan E3): it is what OpenTofu
    last wrote, not a copy some task took along the way.
    """
    return tf_state_store.read(db, deployment_id)


@router.get(
    "/{deployment_id}/resources",
    response_model=DeploymentResourceListResponse,
)
def list_deployment_resources(
    deployment_id: UUID,
    refresh: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the deployment's OpenStack resources for the Infrastructure tab.

    Parsed from the OpenTofu state; with ``refresh=true`` (default) compute
    instances are overlaid with live OpenStack status, fetched with the
    caller's own credential for the project (skipped without one).
    Requires the owner view (owner, project peers, admins); 404/403
    otherwise. ``refresh=false`` skips the live OpenStack join — use
    that when polling rapidly to avoid hammering Keystone, or when
    OpenStack is known unavailable and the cached state is good enough.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    # Inspect-only view (owner view); this endpoint is read-only.
    ensure_view_deployment_owner(current_user, deployment, db)

    if deployment.runtime == app_spec.RUNTIME_K8S:
        rows = k8s_status.workload_views(deployment_id, deployment.k8s_namespace or "")
        return DeploymentResourceListResponse(
            resources=[],
            runtime=app_spec.RUNTIME_K8S,
            workloads=[PodWorkloadSchema.model_validate(r) for r in rows or []],
            live=rows is not None,
        )

    state_json = _latest_tf_state_for(deployment_id, db)
    # Live data is fetched with the caller's own credential for the project
    # (E2). Without one (an admin reading), the cached state is shown.
    can_ask_openstack = (
        crud_openstack_credentials.get_for_project(db, current_user.userId, deployment.os_project_id) is not None
    )
    views = build_resource_views(
        db=db,
        user=current_user,
        project_id=deployment.os_project_id,
        tf_state_json=state_json,
        refresh=refresh and can_ask_openstack,
    )
    # Convert dataclasses → Pydantic models via dict-roundtrip. The
    # fields line up 1:1 by name, so ``model_validate`` works directly
    # on the dataclass dict.
    payload = [
        DeploymentResourceSchema.model_validate(_view_asdict(v))
        for v in views
    ]
    return DeploymentResourceListResponse(resources=payload, live=refresh and can_ask_openstack)


@router.get(
    "/{deployment_id}/resources/{address:path}",
    response_model=DeploymentResourceSchema,
)
def get_deployment_resource_detail(
    deployment_id: UUID,
    address: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the live detail (ports, security groups, volumes, metadata) of one compute instance.

    Requires the owner view. ``address`` is the OpenTofu state address, e.g.
    ``openstack_compute_instance_v2.team_ide["Team-A"]``; 422
    ``invalid_resource_address`` for a malformed one, 404
    ``resource_not_in_state`` when the state has no such instance.

    Uses a ``path``-converter on the address so the for_each-key
    quoting (``team_ide["Team-A"]``) survives URL routing without
    aggressive encoding gymnastics on the client side. The address
    MUST exist in the cached state and MUST be a compute instance.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    # Inspect-only view; the per-VM redeploy below is operate-gated.
    ensure_view_deployment_owner(current_user, deployment, db)

    if not _TF_ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "invalid_resource_address"},
        )

    state_json = _latest_tf_state_for(deployment_id, db)
    view = build_resource_detail(
        db=db,
        user=current_user,
        project_id=deployment.os_project_id,
        tf_state_json=state_json,
        address=address,
    )
    if view is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "resource_not_in_state", "address": address},
        )
    return DeploymentResourceSchema.model_validate(_view_asdict(view))


@router.post(
    "/{deployment_id}/resources/{address:path}/redeploy",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=LifecycleActionResponse,
)
def redeploy_deployment_resource(
    deployment_id: UUID,
    address: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Replace one compute instance via ``terraform apply -replace=…`` (202 ``redeploying``).

    Requires the operate right (owner or project peer) and an own
    credential for the project (403 otherwise). 404
    ``resource_not_in_state`` for an unknown address, 422 for a malformed
    one or a non-instance resource, 409 unless the deployment is
    ``success`` or ``redeploy_failed`` (``services/lifecycle``).

    Address-whitelisted: we re-parse the cached TF state and only
    accept addresses that resolve to a compute instance. Anything else
    fails with 422 — the redeploy of a network resource would tear
    down all the team VMs, which is not what a one-VM "fix it" action
    should do.

    Concurrency: like pause/resume, the per-deployment advisory lock is
    held across the status check and the task insert, so a parallel
    pause or destroy cannot slip in between.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    # Per-VM redeploy is a mutating operation — operate gate
    # (owner or project peer).
    ensure_operate_deployment(current_user, deployment, db)
    crud_locks.acquire_deployment_xact_lock(db, deployment_id)
    lifecycle_service.ensure_action_allowed(
        db, deployment, lifecycle_service.DeploymentAction.REDEPLOY,
    )

    if deployment.runtime == app_spec.RUNTIME_K8S:
        # Pods: the address is a workload name; ``reset:<name>`` also drops its volume.
        if not _WORKLOAD_ADDRESS_RE.match(address):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"reason": "invalid_resource_address"},
            )
        known = k8s_status.workload_views(deployment_id, deployment.k8s_namespace or "")
        if known is not None and address.removeprefix("reset:") not in {r["workload"] for r in known}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"reason": "resource_not_in_state", "address": address},
            )
        return _dispatch_lifecycle_task(
            db=db,
            deployment=deployment,
            current_user=current_user,
            task_type=TaskType.REDEPLOY,
            response_status="redeploying",
            resource_address=address,
        )

    if not _TF_ADDRESS_RE.match(address):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"reason": "invalid_resource_address"},
        )

    # Whitelist check: the address MUST point to a compute instance in
    # the current state. We re-parse here instead of trusting the
    # output of the list endpoint — a hand-crafted POST would skip
    # the list call entirely.
    state_json = _latest_tf_state_for(deployment_id, db)
    parsed = parse_tf_state(state_json)
    match = next((r for r in parsed if r.address == address), None)
    if match is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"reason": "resource_not_in_state", "address": address},
        )
    if match.category != "instance":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "reason": "non_redeployable_resource_type",
                "address": address,
                "category": match.category,
            },
        )

    return _dispatch_lifecycle_task(
        db=db,
        deployment=deployment,
        current_user=current_user,
        task_type=TaskType.REDEPLOY,
        response_status="redeploying",
        resource_address=address,
    )


def _view_asdict(view) -> dict:
    """Recursive dataclass → dict converter, used to bridge
    ``deployment_status.DeploymentResourceView`` to Pydantic.

    ``dataclasses.asdict`` already recurses into nested dataclasses,
    so we just delegate. Kept as a thin wrapper so the call sites
    above read symmetrically and we can swap in custom handling later
    if needed (e.g. enum serialisation).
    """
    return asdict(view)


# ----------------------------------------------------------------
# PAUSE DEPLOYMENT
# ----------------------------------------------------------------
#
# Halts the OpenStack compute instances of a deployment without
# tearing them down. The worker task pulls the terraform state, lists
# every ``openstack_compute_instance_v2`` resource, and runs
# ``openstack server stop`` against each. Volumes and networks stay,
# so RESUME restores the same instances byte-for-byte.
#
# Allowed on ``success`` (and after a failed pause/resume) — the
# lifecycle service is the single source of truth, the partial-unique index on active tasks is
# the DB-level backstop.
@router.post("/{deployment_id}/pause", status_code=status.HTTP_202_ACCEPTED, response_model=LifecycleActionResponse)
def pause_deployment(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Pause a running deployment by stopping its compute instances.

    Operate right (owner or project peer, with an own credential for the
    project) — same gate as Destroy; team members may not, because pausing
    a teammate's deployment is in practice a denial-of-service against the
    team. 409 unless the deployment is in ``success``, ``pause_failed`` or
    ``resume_failed`` (``services/lifecycle``).

    Returns ``202 + {task_id, status: "pausing"}`` on dispatch. The
    frontend reads ``status`` to switch to the live SSE view; the
    deployment's effective status is recomputed from the new task
    row by ``crud_deployments.get_deployment_status``.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )

    ensure_operate_deployment(current_user, deployment, db)
    # Hold the per-deployment advisory lock across the status check
    # AND the task insert so a parallel POST /pause can't sneak past
    # ``ensure_action_allowed`` between our read and the
    # ``prepare_task_in_tx`` flush.
    crud_locks.acquire_deployment_xact_lock(db, deployment_id)
    lifecycle_service.ensure_action_allowed(
        db, deployment, lifecycle_service.DeploymentAction.PAUSE,
    )

    return _dispatch_lifecycle_task(
        db,
        deployment,
        current_user,
        task_type=TaskType.PAUSE,
        response_status="pausing",
    )


# ----------------------------------------------------------------
# RESUME DEPLOYMENT
# ----------------------------------------------------------------
#
# Reverses Pause. Allowed on ``paused`` (and after a failed pause/resume)
# — a deployment that was never paused has nothing to resume, so the
# lifecycle matrix gates this strictly. Returns 202 with the same shape as
# Pause/Destroy so the frontend handles all three the same way.
@router.post("/{deployment_id}/resume", status_code=status.HTTP_202_ACCEPTED, response_model=LifecycleActionResponse)
def resume_deployment(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Resume a paused deployment by starting its compute instances.

    Same gate and response as pause (202 ``{task_id, status: "resuming"}``);
    409 unless the deployment is ``paused``, ``pause_failed`` or
    ``resume_failed``.
    """
    deployment = crud_deployments.get_deployment_with_details(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )

    ensure_operate_deployment(current_user, deployment, db)
    # Per-deployment advisory lock — same justification as in
    # ``pause_deployment`` above: keep the status check and the task
    # insert atomic against concurrent /resume / /pause / DELETE
    # requests on this deployment.
    crud_locks.acquire_deployment_xact_lock(db, deployment_id)
    lifecycle_service.ensure_action_allowed(
        db, deployment, lifecycle_service.DeploymentAction.RESUME,
    )

    return _dispatch_lifecycle_task(
        db,
        deployment,
        current_user,
        task_type=TaskType.RESUME,
        response_status="resuming",
    )


# ----------------------------------------------------------------
# DOWNLOAD UPLOADED FILE
# ----------------------------------------------------------------
#
# Lets the deployment owner re-fetch a file they uploaded at deploy
# time. The list / detail endpoints strip the base64 payload so they
# don't ship megabytes per page render; this endpoint is the only
# path that returns the actual bytes. Owner-only — members can see
# that a file was uploaded (metadata survives the strip), but the
# bytes themselves stay restricted to whoever created the deployment.
@router.get(
    "/{deployment_id}/files/{var_name}/{slot_key}",
    response_class=Response,
)
def download_deployment_file(
    deployment_id: UUID,
    var_name: str,
    slot_key: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download one file uploaded in the deploy wizard, as ``application/octet-stream``.

    Requires the owner view (owner, project peers, admins); plain team
    members only see the file's metadata in the detail response.

    Path components mirror how the upload was indexed:
      * ``var_name`` — the ``@openstack:file:*`` variable name
      * ``slot_key`` — the inner-map key (``"all"`` for scope=all,
        team name for scope=team, ``Team-User`` composite for scope=user)

    Returns 404 if any layer of the lookup misses; the frontend can
    therefore probe a slot's existence via this endpoint without
    needing a separate metadata response.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    # Inspect-only view, gated through capabilities: whoever has the
    # owner view (logs / detail) may download the wizard-uploaded files
    # referenced there. The list/detail strip-pass already hid the
    # base64 payload from plain members, so this endpoint stays
    # restricted to the owner-view set.
    ensure_view_deployment_owner(current_user, deployment, db)

    if not deployment.userInputVar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No files")
    try:
        user_input = json.loads(deployment.userInputVar)
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No files")

    tf_block = user_input.get("terraform") if isinstance(user_input, dict) else None
    var_value = (tf_block or {}).get(var_name)
    if not _looks_like_file_var(var_value) or not isinstance(var_value, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No uploaded file under variable '{var_name}'",
        )
    # ``var_value`` is ``{slot_key: {name, content_b64, size, content_type}}``;
    # the slot-level entry IS the file metadata, no extra wrapper.
    entry = var_value.get(slot_key)
    if not isinstance(entry, dict) or "content_b64" not in entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No file in slot '{slot_key}'",
        )

    try:
        payload = base64.b64decode(entry["content_b64"], validate=True)
    except (binascii.Error, ValueError):
        # Persisted bytes are corrupt — surface as 500 because there's
        # nothing the caller can do; this is a server-side data bug.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored file payload is not valid base64",
        )

    filename = str(entry.get("name") or f"{var_name}-{slot_key}")
    # Always a download of opaque bytes: the stored content type came from
    # the uploader's browser, and serving e.g. text/html from the API's
    # origin would let an upload run script in a colleague's session.
    return Response(
        content=payload,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(filename),
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(payload)),
        },
    )


# ----------------------------------------------------------------
# GET OWN ACCESS CREDENTIALS (member self-service)
# ----------------------------------------------------------------
@router.get("/{deployment_id}/my-access", response_model=MyAccessResponse)
def get_my_deployment_access(
    deployment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the calling member's OWN access credentials for a deployment.

    The full terraform ``outputs`` are owner-view-only (they carry every
    teammate's credentials in one object). This endpoint is the member
    counterpart: a team member — typically a student — retrieves only
    THEIR OWN account, extracted server-side from the latest successful
    deploy. Teammates' credentials are never included in the response.

    Authorisation reuses :func:`ensure_resend_access` with the target set
    to the caller themself, which collapses to the member-view gate
    (owner view or team member). A caller with no access to the
    deployment gets 403, an unknown deployment 404; the resend endpoint uses the same
    gate for the self-resend button, so the two stay consistent.

    Returns 200 with empty maps when there's no successful deploy yet or
    the app issued no per-user credential for this user — the UI renders
    a "no credentials yet" state rather than treating it as an error.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    # Self-target → member-view gate. Non-members get 403 here.
    ensure_resend_access(current_user, deployment, current_user.userId, db)

    access = deployment_notifier.get_user_access(
        db, deployment_id, current_user.userId
    )
    if access is None:
        # No successful deploy yet, user not in any team, or no per-user
        # credential in the outputs — surface an empty (but valid) payload.
        return MyAccessResponse()
    return MyAccessResponse(
        user_accounts=access.get("user_accounts", {}),
        team_vms=access.get("team_vms", {}),
    )


# ----------------------------------------------------------------
# RESEND ACCESS MAIL FOR ONE TEAM MEMBER
# ----------------------------------------------------------------
@router.post(
    "/{deployment_id}/teams/{team_id}/users/{user_id}/resend-access",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=dict[str, str],
)
def resend_access_mail(
    deployment_id: UUID,
    team_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Send the "Ihr Zugang ist bereit" mail to one team member again.

    The mail carries no credentials (plan E5), only the link to "Meine
    Zugänge". Members may resend their own; the owner view (owner, project
    peers, admins) may resend for anyone in the deployment. No rate limit
    at the API level; the relay is the backstop.

    Status codes:
      * 202 ``{"status": "sent"}``
      * 403 — not a member, or a member resending someone else's mail
      * 404 — deployment unknown, ``team_not_in_deployment`` / ``user_not_in_team``
      * 409 — a task is in flight, or ``no_successful_deploy`` (nothing is ready yet)
      * 502 ``smtp_send_failed`` — the mail relay rejected the mail
      * 503 ``smtp_disabled`` — mail sending is switched off by the operator
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deployment not found",
        )
    ensure_view_deployment_member(current_user, deployment, db)

    # Members may only re-send their own access mail. Owner-view
    # callers (owner, project peers, admin) can resend for anyone in any team. Without this check a student in team A could trigger
    # a mail to anyone else's address, which is both privacy-leaky
    # and a tiny SMTP-amplification vector.
    #
    # This 403 is decided BEFORE the SMTP-disabled 503 below: a
    # not-authorised caller must not learn the SMTP-state of the
    # platform — that would be a (small) information disclosure.
    ensure_resend_access(current_user, deployment, user_id, db)

    # SMTP kill-switch check: refuse cleanly with 503 BEFORE running the
    # notifier so the response carries the correct semantic ("we chose
    # not to send" — operator configuration) rather than the existing
    # 502 ("we tried and SMTP rejected" — infrastructure failure).
    # Frontend distinguishes the two reasons in the toast text so the
    # user understands whether to ask an admin to enable mail or to
    # simply retry. The 503 + Retry-After header signals "service
    # temporarily unavailable; come back later" semantics.
    #
    # Order vs. 409 in-flight: a 503 here is non-recoverable until an
    # operator flips the env-flag, whereas 409 is a transient state
    # the caller can simply wait out. Returning the 503 first matches
    # the "service-level concern beats per-request concern" pattern
    # used by every other 5xx vs 4xx ordering in this router.
    if not email_service.is_smtp_enabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"reason": "smtp_disabled"},
            headers={"Retry-After": "3600"},
        )

    # Refuse while another lifecycle action is in flight: the mail says
    # the environment is ready, which during pending/running/destroying/
    # pausing/resuming it may not be (paused → SHUTOFF, destroying →
    # tearing down). Returning 409 here keeps
    # the user's mental model consistent with the rest of the
    # lifecycle gates.
    #
    # Per-deployment advisory lock is acquired BEFORE the status
    # read so a concurrent /pause / /resume / DELETE can't slip a
    # transition past us between the check and the mail send. The
    # lock is the same one those endpoints take, so the four
    # mutators serialise against each other on the same deployment.
    crud_locks.acquire_deployment_xact_lock(db, deployment_id)
    current_status = crud_deployments.get_deployment_status(db, deployment_id)
    if current_status in lifecycle_service.IN_FLIGHT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot resend access mail while deployment is '{current_status}'. "
                "Wait for the active task to finish."
            ),
        )

    try:
        sent = deployment_notifier.resend_user_access(
            db, deployment_id, team_id, user_id,
        )
    except deployment_notifier.ResendError as e:
        reason = str(e)
        # 404 for "this user/team isn't in this deployment", 409 for
        # "no deploy has succeeded yet".
        if reason in ("deployment_not_found", "team_not_in_deployment", "user_not_in_team"):
            http_status = status.HTTP_404_NOT_FOUND
        else:
            http_status = status.HTTP_409_CONFLICT
        raise HTTPException(status_code=http_status, detail={"reason": reason})

    if not sent:
        # Template render + payload were fine, only SMTP rejected.
        # 502 makes the "upstream service failed" semantics clear so
        # the frontend can surface a retry rather than a 4xx that
        # implies the request itself was wrong.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"reason": "smtp_send_failed"},
        )
    return {"status": "sent"}


# ----------------------------------------------------------------
# LIVE STREAM — Server-Sent Events for progress + log tail
# ----------------------------------------------------------------
#
# Several kinds of events flow through the stream:
#
# * ``event: snapshot`` — fired once at connect with the latest task's
#   current_phase / progress_pct / status. Lets a freshly-loaded page
#   render the bar at the right position before the worker emits its
#   next progress update.
# * ``event: progress`` — every ``task-progress`` from the worker. The
#   payload includes ``phase``, ``phase_index``, ``total_phases``,
#   ``progress_pct``, ``message``.
# * ``event: log`` — every ``task-log`` from the worker. The payload
#   is the LogEntry dict (timestamp, level, category, message, plus
#   tool/streaming flags for streaming subprocess lines).
# * ``event: succeeded`` / ``failed`` / ``revoked`` — the task ended; the
#   stream closes after it.
# * comment lines starting with ``:`` are SSE keepalive pings.
#
# The events come from ``task_events``, where the worker appends them
# (plan D4: no broker, no in-process fan-out, any API replica can serve
# any stream). Each frame carries the row id as its SSE ``id``, so when
# EventSource reconnects on its own it sends ``Last-Event-ID`` and the
# stream resumes after the last event it saw instead of replaying all.
@router.get("/{deployment_id}/stream")
async def stream_deployment_events(
    deployment_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Live progress + log stream for one deployment as Server-Sent Events.

    Streams the events of the deployment's latest task, from the start
    (or from ``Last-Event-ID`` on a reconnect), then follows new ones by
    polling until the task's terminal event. Starts with a ``snapshot``
    event; with no task yet the stream ends right after it. Requires the
    owner view (owner, project peers, admins); 404/403 otherwise.
    """
    deployment = crud_deployments.get_deployment(db, deployment_id)
    if not deployment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deployment not found")
    # Inspect-only view via capabilities. The live stream surfaces
    # task-log lines (raw worker stdout incl. terraform output, packer
    # build chatter, etc.); the owner view sees it, plain members
    # still see metadata only.
    ensure_view_deployment_owner(current_user, deployment, db)

    latest_task = crud_deployments.get_latest_task(db, deployment_id)
    snapshot_payload = {
        "task_id": str(latest_task.taskId) if latest_task else None,
        "status": latest_task.status.value if latest_task else None,
        "current_phase": getattr(latest_task, "current_phase", None),
        "progress_pct": getattr(latest_task, "progress_pct", None),
        "type": latest_task.type.value if latest_task else None,
    }
    task_id = latest_task.taskId if latest_task else None
    try:
        after_id = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        after_id = 0

    async def event_stream() -> AsyncIterator[bytes]:
        """Yield the snapshot, then new task events until the terminal one or a disconnect."""
        nonlocal after_id
        yield _sse_frame("snapshot", snapshot_payload)
        if task_id is None:
            return
        keepalive_at = asyncio.get_running_loop().time() + _SSE_KEEPALIVE_SECONDS
        while True:
            if await request.is_disconnected():
                return
            rows, finished = await asyncio.to_thread(_task_events_after, task_id, after_id)
            for event_id, event_type, payload in rows:
                after_id = event_id
                yield _sse_frame(_event_name_for(event_type), json.loads(payload), event_id=event_id)
                if event_type in TERMINAL_EVENTS:
                    return
            if finished and not rows:
                # Ended without a terminal event on record; nothing more
                # will come.
                return
            if rows:
                continue
            now = asyncio.get_running_loop().time()
            if now >= keepalive_at:
                # Proxies and EventSource close idle connections.
                yield b": keepalive\n\n"
                keepalive_at = now + _SSE_KEEPALIVE_SECONDS
            await asyncio.sleep(_SSE_POLL_SECONDS)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
            "Connection": "keep-alive",
        },
    )


# New worker output shows up within this delay. Each open stream costs one
# small indexed query per interval, which is cheap at classroom scale.
_SSE_POLL_SECONDS = 1.0
_SSE_KEEPALIVE_SECONDS = 15.0
# Upper bound per query, so a long backlog is sent in chunks.
_SSE_BATCH = 500


def _task_events_after(task_id: UUID, after_id: int) -> tuple[list[tuple[int, str, str]], bool]:
    """The task's events with an id above ``after_id``, and whether the
    task has finished. Runs in a worker thread with its own session: the
    stream outlives the request's session."""
    with SessionLocal() as session:
        rows = session.execute(
            select(TaskEvent.id, TaskEvent.type, TaskEvent.payload)
            .where(TaskEvent.taskId == task_id, TaskEvent.id > after_id)
            .order_by(TaskEvent.id)
            .limit(_SSE_BATCH)
        ).all()
        status_value = session.execute(select(TaskModel.status).where(TaskModel.taskId == task_id)).scalar()
    finished = status_value in (TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED)
    return [(r[0], r[1], r[2]) for r in rows], finished


_EVENT_NAME_MAP: dict[str, str] = {
    "task-progress": "progress",
    "task-log": "log",
    "task-succeeded": "succeeded",
    "task-failed": "failed",
    "task-revoked": "revoked",
}


def _event_name_for(event_type: str | None) -> str:
    """Map stored event types onto short SSE event names.

    Frontend code attaches listeners by these short names;
    ``_EVENT_NAME_MAP`` is the single source of truth on both sides of
    the wire.
    """
    return _EVENT_NAME_MAP.get(event_type or "", "message")


def _sse_frame(event_name: str, payload: dict, event_id: int | None = None) -> bytes:
    """Serialise one SSE frame.

    SSE format:

    ```
    event: <name>\\n
    data: <json>\\n
    \\n
    ```

    Embedded newlines in the JSON would split the frame into multiple
    ``data:`` lines per the SSE spec; we use ``json.dumps`` defaults
    which keep everything on one line.
    """
    body = json.dumps(payload, default=str)
    id_line = f"id: {event_id}\n" if event_id is not None else ""
    return f"{id_line}event: {event_name}\ndata: {body}\n\n".encode()
