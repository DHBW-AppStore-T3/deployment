"""The contract between the API, which queues jobs, and the worker, which runs them.

A job is a row in ``tasks`` (plan D4: Postgres is the queue). The API writes
it with an encrypted :class:`JobPayload`; a worker claims it, runs it, appends
:class:`~appstore_shared.models.TaskEvent` rows while it runs and records the
result on the row. Event types keep the names the live stream has always
used, so the browser side does not change.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, NotRequired, TypedDict

from appstore_shared.crypto import Cipher
from appstore_shared.models import Task, TaskStatus

# Emitted while a job runs.
EVENT_PROGRESS = "task-progress"
EVENT_LOG = "task-log"
# Exactly one of these ends every task's event stream.
EVENT_SUCCEEDED = "task-succeeded"
EVENT_FAILED = "task-failed"
EVENT_CANCELLED = "task-revoked"
TERMINAL_EVENTS = frozenset({EVENT_SUCCEEDED, EVENT_FAILED, EVENT_CANCELLED})

# Why a task failed, for the UI: the job itself failed (OpenTofu, Packer, …),
# or the worker running it disappeared and nothing is known about the result.
FAILURE_KIND_JOB = "worker_failure"
FAILURE_KIND_WORKER_LOST = "worker_lost"

_TERMINAL_STATUS = {
    TaskStatus.SUCCESS: (EVENT_SUCCEEDED, "success"),
    TaskStatus.FAILED: (EVENT_FAILED, "failed"),
    TaskStatus.CANCELLED: (EVENT_CANCELLED, "cancelled"),
}


class JobPayload(TypedDict):
    """Everything a worker needs to run one task. Stored encrypted."""

    app_id: str
    app_git_link: str
    # The tag, for display, and the commit it pointed to when the deployment
    # was created; jobs check out the commit (see git_service).
    release: str
    commit_sha: str
    user_vars: dict[str, Any]
    # team name -> [{"email": ...}]
    teams: dict[str, list[dict[str, str]]]
    # The caller's OpenStack credential, itself encrypted field by field.
    openstack_envelope: dict[str, Any]
    # Opens this deployment's state in the API's state backend while the
    # task runs (plan E3); the task row keeps only its hash. Added when the
    # task is queued, not by the caller.
    state_token: NotRequired[str]
    # Only for REDEPLOY: the resource address to replace.
    resource_address: NotRequired[str]


def state_token_hash(token: str) -> str:
    """What the task row stores of the state token."""
    return hashlib.sha256(token.encode()).hexdigest()


def seal_payload(cipher: Cipher, payload: JobPayload) -> bytes:
    """Encrypt a job payload for ``Task.payload`` (API side)."""
    return cipher.encrypt(json.dumps(payload))


def open_payload(cipher: Cipher, sealed: bytes) -> JobPayload:
    """Decrypt ``Task.payload`` (worker side). Raises InvalidToken with the wrong key."""
    data: JobPayload = json.loads(cipher.decrypt(sealed))
    return data


def seal_outputs(cipher: Cipher, outputs: dict[str, Any] | None) -> bytes | None:
    """OpenTofu outputs as stored on the task row: encrypted, since they carry
    the generated credentials (``user_accounts``)."""
    if not outputs:
        return None
    return cipher.encrypt(json.dumps(outputs, ensure_ascii=False, default=str))


def open_outputs(cipher: Cipher, sealed: bytes | None) -> dict[str, Any] | None:
    """Decrypt ``Task.outputs``; None when empty or not a JSON object."""
    if not sealed:
        return None
    value = json.loads(cipher.decrypt(sealed))
    return value if isinstance(value, dict) else None


def redact_sensitive_outputs(outputs: dict[str, Any] | None) -> dict[str, Any] | None:
    """``outputs`` with the value of every output marked ``sensitive`` removed.

    For views that show a deployment's outputs to people other than the one
    each secret belongs to. The app contract marks ``user_accounts`` sensitive;
    students get their own entry through their access view instead.
    """
    if outputs is None:
        return None
    redacted: dict[str, Any] = {}
    for name, out in outputs.items():
        if isinstance(out, dict) and out.get("sensitive"):
            redacted[name] = {**{k: v for k, v in out.items() if k != "value"}, "value": None, "redacted": True}
        else:
            redacted[name] = out
    return redacted


def terminal_event(task: Task, failure_kind: str | None = None) -> tuple[str, dict[str, Any]]:
    """The last event of ``task``'s stream, for a task in a terminal state.

    Returns ``(event_type, payload)``. The payload shape is what the live
    stream has always sent when a task ended.
    """
    event_type, status = _TERMINAL_STATUS[task.status]
    payload: dict[str, Any] = {
        "type": event_type,
        "deployment_id": str(task.deploymentId),
        "task_id": str(task.taskId),
        "task_type": task.type.value,
        "status": status,
    }
    if task.status == TaskStatus.FAILED and failure_kind:
        payload["failure_kind"] = failure_kind
    return event_type, payload


__all__ = [
    "EVENT_PROGRESS",
    "EVENT_LOG",
    "EVENT_SUCCEEDED",
    "EVENT_FAILED",
    "EVENT_CANCELLED",
    "TERMINAL_EVENTS",
    "FAILURE_KIND_JOB",
    "FAILURE_KIND_WORKER_LOST",
    "JobPayload",
    "state_token_hash",
    "seal_payload",
    "seal_outputs",
    "open_outputs",
    "redact_sensitive_outputs",
    "open_payload",
    "terminal_event",
]
