"""Deployment lifecycle gating — single source of truth for which
actions are allowed in which state.

Centralises the state matrix so the API and the UI consult one
canonical mapping. The deployment routers call ``ensure_action_allowed``
before enqueuing a destroy/pause/resume/redeploy task or deleting a deployment, and
``allowed_actions`` to tell the UI which buttons to show.

Status values follow ``crud_deployments.get_deployment_status``:

* ``pending`` / ``running`` — a deploy task is in flight
* ``success`` — deploy finished, resources live in OpenStack
* ``failed`` — last deploy or destroy task ended in error
* ``cancelled`` — last task was revoked
* ``destroying`` — a destroy task is in flight (synthetic)
* ``destroyed`` — a destroy task finished successfully (synthetic)
* ``pausing`` — a pause task is in flight (synthetic)
* ``paused`` — a pause task finished successfully (synthetic)
* ``resuming`` — a resume task is in flight (synthetic)
* ``pause_failed`` / ``resume_failed`` — the last pause/resume task ended in
  error (synthetic)
* ``redeploy_failed`` — the last single-VM redeploy ended in error; the
  other resources are untouched (synthetic)
"""

from __future__ import annotations

from enum import Enum

from fastapi import HTTPException, status

from appstore_api.crud import deployments as crud_deployments


class DeploymentAction(str, Enum):
    """Lifecycle actions a user can request."""

    DESTROY = "destroy"
    DELETE = "delete"
    # Pause halts compute (``openstack server stop`` for every server);
    # volumes and networks stay so resume restores the same instances.
    PAUSE = "pause"
    # Resume reverses pause. Only valid in the synthetic ``paused``
    # state so the matrix stays unambiguous.
    RESUME = "resume"
    # Rebuild one compute instance (``tofu apply -replace``); only on a
    # deployment whose resources are up, so it cannot race a pause or run
    # against SHUTOFF instances.
    REDEPLOY = "redeploy"


# Synthetic statuses where a worker task is currently in flight. Every
# action endpoint must refuse while in any of these to avoid a parallel
# destroy mid-deploy or pause mid-resume. Single source of truth so the
# routes and the matrix below stay in sync.
IN_FLIGHT_STATUSES: frozenset[str] = frozenset({
    "pending",
    "running",
    "destroying",
    "pausing",
    "resuming",
})


# Status → set of allowed actions. Anything not listed gets the empty
# set (safe default: an unrecognised status allows no destructive action).
_ALLOWED: dict[str, set[DeploymentAction]] = {
    # Deployed and running — tear down or pause compute to free quota.
    "success": {DeploymentAction.DESTROY, DeploymentAction.PAUSE, DeploymentAction.REDEPLOY},
    # A failed deploy may have created some resources, so Destroy is
    # offered to reconcile; Delete is available when there's nothing to
    # clean up. Both end at "row hidden from UI".
    "failed": {DeploymentAction.DESTROY, DeploymentAction.DELETE},
    # No ``destroyed`` entry: a successful destroy auto-soft-deletes the
    # deployment, so that status only exists transiently (sub-second).
    "cancelled": {DeploymentAction.DELETE},
    # Paused — Resume is the obvious action; Destroy stays available so
    # the user needn't resume first (terraform-destroy works on SHUTOFF).
    "paused": {DeploymentAction.RESUME, DeploymentAction.DESTROY},
    # Pause failed: the deployment is still running. Allow PAUSE retry,
    # RESUME (harmless), and DESTROY.
    "pause_failed": {
        DeploymentAction.PAUSE,
        DeploymentAction.RESUME,
        DeploymentAction.DESTROY,
    },
    # Resume failed: instances are SHUTOFF. Allow RESUME retry, PAUSE
    # (idempotent), and DESTROY.
    "resume_failed": {
        DeploymentAction.RESUME,
        DeploymentAction.PAUSE,
        DeploymentAction.DESTROY,
    },
    # Redeploy failed: only that one VM is in doubt, the rest runs. Allow
    # a retry, PAUSE and DESTROY — not DELETE, which would orphan the
    # live resources.
    "redeploy_failed": {
        DeploymentAction.REDEPLOY,
        DeploymentAction.PAUSE,
        DeploymentAction.DESTROY,
    },
    # pending / running / destroying / pausing / resuming — no action
    # allowed; a DB partial-unique index on in-flight tasks enforces
    # this at insert time too.
}

# Human-readable explanation for the 409 we throw when an action isn't
# allowed. Keys match the action; the message lists the statuses where
# the action is valid.
_REQUIRED_STATES: dict[DeploymentAction, str] = {
    DeploymentAction.DESTROY: "success, failed, paused, pause_failed, resume_failed or redeploy_failed",
    DeploymentAction.DELETE: "failed or cancelled",
    DeploymentAction.PAUSE: "success, pause_failed, resume_failed or redeploy_failed",
    DeploymentAction.REDEPLOY: "success or redeploy_failed",
    DeploymentAction.RESUME: "paused, pause_failed or resume_failed",
}


def allowed_actions(db, deployment) -> set[DeploymentAction]:
    """Return the set of actions allowed for the given deployment.

    ``deployment`` can be a Deployment ORM instance or just its id —
    we only need the id to look up its status. We pass the ORM instance
    in routers because they already have it loaded.
    """
    deployment_id = getattr(deployment, "deploymentId", deployment)
    current = crud_deployments.get_deployment_status(db, deployment_id)
    if current is None:
        return set()
    return _ALLOWED.get(current, set())


def ensure_action_allowed(db, deployment, action: DeploymentAction) -> None:
    """Raise ``HTTPException(409)`` if ``action`` isn't allowed right now.

    Produces a friendly status-mismatch message on top of the DB-level
    partial unique index (whose own error is opaque).
    """
    if action in allowed_actions(db, deployment):
        return
    deployment_id = getattr(deployment, "deploymentId", deployment)
    current = crud_deployments.get_deployment_status(db, deployment_id) or "unknown"
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            f"Cannot {action.value} a deployment in status '{current}'. "
            f"Required status: {_REQUIRED_STATES[action]}."
        ),
    )
