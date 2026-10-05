"""Jobs without OpenStack, for development (``WORKER_SIMULATE=true``, plan AP7).

Students work on the UI and the API without access to a cloud. With this
switch the worker claims tasks as usual but, instead of cloning the app and
running OpenTofu, plays each job through: the same phases, progress events
and log lines as a real run, a few seconds each, and for a deploy the outputs
an app like the Online-IDE produces (``team_vms``, ``user_accounts`` for every
team member) plus an OpenTofu state with one server per team, written to the
API's state backend like a real apply would. So the live view, the
infrastructure tab, "Meine Zugänge" and the mails all have something real to
show.

A deploy whose Terraform variables contain ``simulate_failure: true`` fails
in the apply phase, for working on the error paths.

Nothing here touches OpenStack or Git, and no credential is decrypted.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import time
import urllib.request
import uuid
from typing import Any

from .config import settings
from .services.terraform_executor import StateBackend
from .tasks import (
    _PHASES_DESTROY,
    _PHASES_PAUSE,
    _PHASES_REDEPLOY,
    _PHASES_RESUME,
    _PHASES_WITHOUT_PACKER,
    PHASE_TERRAFORM_APPLY,
    Failure,
    JobEvents,
    _PhaseTracker,
)
from .utils.logger import LogCategory, get_logger

# Documentation addresses (RFC 5737), so a simulated VM is never mistaken for
# a real one.
_PUBLIC_NET = "203.0.113."


def _account_name(email: str) -> str:
    """The Online-IDE's account name: the address's local part, [a-z0-9-] only."""
    return re.sub(r"[^a-z0-9]+", "-", email.split("@", 1)[0].lower()).strip("-") or "user"


def _outputs(deployment_id: str, teams: dict[str, list]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """``tofu output -json`` of a deploy, and the servers for the state."""
    team_vms: dict[str, Any] = {}
    accounts: dict[str, Any] = {}
    servers: list[dict[str, Any]] = []
    for i, (team, members) in enumerate(sorted(teams.items()), start=10):
        ip = f"{_PUBLIC_NET}{i}"
        server_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{deployment_id}/{team}"))
        name = f"sim-{re.sub(r'[^a-z0-9]+', '-', team.lower())}"
        team_vms[team] = {
            "code_server_url": f"http://{ip}:8080",
            "floating_ip": ip,
            "fixed_ip": f"10.0.0.{i}",
            "instance_id": server_id,
            "instance_name": name,
        }
        for member in members:
            account = _account_name(member.get("email", ""))
            accounts[f"{team}-{account}"] = {
                "auth": secrets.token_urlsafe(12),
                "ip": ip,
                "port": 8080,
                "type": "password",
                "username": account,
            }
        servers.append({
            "index_key": team,
            "schema_version": 0,
            "attributes": {
                "id": server_id,
                "name": name,
                "access_ip_v4": f"10.0.0.{i}",
                "flavor_name": "sim.small",
                "image_name": "simulated",
                "power_state": "active",
                "metadata": {"team": team, "simulated": "true"},
            },
        })
    outputs = {
        "team_vms": {"value": team_vms, "type": ["map", "dynamic"], "sensitive": False},
        "user_accounts": {"value": accounts, "type": ["map", "dynamic"], "sensitive": True},
        "teams_summary": {
            "value": {team: len(members) for team, members in teams.items()},
            "type": ["map", "number"],
            "sensitive": False,
        },
    }
    return outputs, servers


def _write_state(state_backend: StateBackend | None, outputs: dict[str, Any], servers: list[dict[str, Any]]) -> None:
    """Store a minimal OpenTofu v4 state with ``outputs`` and ``servers`` in the API's state backend.

    Skipped without a backend (no state token in the payload).
    """
    if state_backend is None:
        return
    state = {
        "version": 4,
        "terraform_version": "1.12.6",
        "serial": 1,
        "lineage": str(uuid.uuid4()),
        "outputs": {k: {"value": v["value"], "type": v["type"], "sensitive": v["sensitive"]} for k, v in outputs.items()},
        "resources": [
            {
                "mode": "managed",
                "type": "openstack_compute_instance_v2",
                "name": "team_vm",
                "provider": 'provider["registry.opentofu.org/terraform-provider-openstack/openstack"]',
                "instances": servers,
            }
        ]
        if servers
        else [],
    }
    _post(state_backend, json.dumps(state).encode())


def _post(state_backend: StateBackend, body: bytes) -> None:
    """POST to the state backend the way OpenTofu does (Basic auth); raises on HTTP errors."""
    basic = base64.b64encode(f"{state_backend.username}:{state_backend.password}".encode()).decode()
    request = urllib.request.Request(  # noqa: S310 — the configured API URL, http(s) only
        state_backend.address,
        data=body,
        method="POST",
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30):  # noqa: S310
        pass


def _play(
    job: JobEvents,
    deployment_id: str,
    action: str,
    phases: tuple[str, ...],
    *,
    fail_at: str | None = None,
    after_phase: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk through ``phases`` with the real phase tracker and logger, sleeping in each.

    ``after_phase`` maps a phase to a hook called with the task logger once
    that phase is done; ``fail_at`` raises in that phase. Raises ``Failure``
    like a real job, otherwise returns the common result shape without outputs.
    """
    task_logger = get_logger(f"{action}:{deployment_id}", correlation_id=deployment_id)
    task_logger.set_event_emitter(lambda name, payload: job.send_event(name, deployment_id=deployment_id, **payload))
    tracker = _PhaseTracker(task_logger, phases)
    task_logger.warning(
        "WORKER_SIMULATE is on: nothing is created in OpenStack, this run is played through",
        category=LogCategory.WARNING,
    )
    try:
        for phase in phases:
            tracker.mark(phase, f"{phase.replace('_', ' ').capitalize()} (simulated)")
            task_logger.info(f"Simulating {phase}", category=LogCategory.OPERATION)
            time.sleep(settings.WORKER_SIMULATE_STEP_SECONDS)
            if phase == fail_at:
                raise RuntimeError(f"Simulated failure in {phase} (simulate_failure is set)")
            hook = (after_phase or {}).get(phase)
            if hook:
                hook(task_logger)
        task_logger.success(f"Simulated {action} of {deployment_id} completed", category=LogCategory.STATUS)
    except Exception as e:
        task_logger.exception(f"{action.capitalize()} failed: {e}", exception=e, deployment_id=deployment_id)
        raise Failure(
            message=str(e), deployment_id=deployment_id, logs_dict=task_logger.get_logs_dict(), terraform_outputs={}
        ) from None
    return {"status": "success", "deployment_id": deployment_id, "logs": task_logger.get_logs_dict()}


def deploy_application(
    job: JobEvents,
    deployment_id: str,
    user_vars: dict[str, Any],
    teams: dict[str, list] | None = None,
    state_backend: StateBackend | None = None,
    commit_sha: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Simulated deploy: the no-Packer phases; stores a fake state after the apply.

    Returns Online-IDE-like outputs for ``teams``. Fails in TERRAFORM_APPLY
    when ``user_vars["terraform"]["simulate_failure"]`` is truthy.
    """
    outputs, servers = _outputs(deployment_id, teams or {})
    fail = bool((user_vars.get("terraform") or {}).get("simulate_failure"))

    def write(task_logger: Any) -> None:
        _write_state(state_backend, outputs, servers)
        task_logger.info(f"Simulated state with {len(servers)} server(s) stored", category=LogCategory.OPERATION)

    result = _play(
        job,
        deployment_id,
        "deploy",
        _PHASES_WITHOUT_PACKER,
        fail_at=PHASE_TERRAFORM_APPLY if fail else None,
        after_phase={PHASE_TERRAFORM_APPLY: write},
    )
    return {
        **result,
        "commit_info": {"hash": commit_sha, "message": "simulated", "author": "simulated"},
        "terraform_outputs": outputs,
    }


def destroy_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Simulated destroy: plays the destroy phases, touches no state."""
    return {**_play(job, deployment_id, "destroy", _PHASES_DESTROY), "terraform_outputs": {}}


def pause_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Simulated pause: plays the pause phases."""
    return {**_play(job, deployment_id, "pause", _PHASES_PAUSE), "terraform_outputs": {}}


def resume_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Simulated resume: plays the resume phases."""
    return {**_play(job, deployment_id, "resume", _PHASES_RESUME), "terraform_outputs": {}}


def redeploy_resource(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Simulated redeploy of one resource: plays the redeploy phases."""
    return {**_play(job, deployment_id, "redeploy", _PHASES_REDEPLOY), "terraform_outputs": {}}
