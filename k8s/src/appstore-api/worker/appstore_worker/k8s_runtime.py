"""Jobs for apps that run as pods (``runtime: kubernetes``, an appstore.yaml).

The API read and validated the app's spec at the pinned commit and put it into
the job payload, so the worker never clones or executes anything from the app
repository: it renders the Kubernetes objects itself
(:mod:`appstore_shared.k8s.render`), applies them with Server-Side Apply and
waits for them. The same phases/progress/log events as the OpenTofu jobs reach
the live view. There is no OpenTofu state: the state of a deployment is its
namespace ``dep-<id>`` in the cluster.

Every job has the signature of the VM jobs (see ``simulate.py``) and returns
the same result shape, with ``terraform_outputs`` carrying ``team_vms`` and
``user_accounts`` so ``my-access`` and the mails work unchanged.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable
from typing import Any

from appstore_shared.k8s.kube import Kube, KubeApi, Snapshot, deployment_selector
from appstore_shared.k8s.render import (
    DeploymentCtx,
    RenderSettings,
    Team,
    render,
    render_access,
    workload_refs,
)
from appstore_shared.k8s.spec import (
    AppSpec,
    PlatformLimits,
    SpecValidationError,
    parse_cpu_millicores,
    parse_memory_mib,
    parse_spec,
)

from .config import settings
from .tasks import Failure, JobEvents, _PhaseTracker
from .utils.logger import LogCategory, get_logger

PHASE_STARTING = "STARTING"
PHASE_SPEC_LOAD = "SPEC_LOAD"
PHASE_NAMESPACE = "K8S_NAMESPACE"
PHASE_POLICIES = "K8S_POLICIES"
PHASE_APPLY = "K8S_APPLY"
PHASE_WAIT_READY = "K8S_WAIT_READY"
PHASE_OUTPUTS = "OUTPUTS_AND_CLEANUP"
PHASE_DELETE = "K8S_DELETE"
PHASE_WAIT_GONE = "K8S_WAIT_GONE"
PHASE_CLEANUP = "CLEANUP"
PHASE_SCALE_DOWN = "K8S_SCALE_DOWN"
PHASE_WAIT_STOPPED = "K8S_WAIT_STOPPED"
PHASE_SCALE_UP = "K8S_SCALE_UP"
PHASE_RESTART = "K8S_RESTART"

PHASES_DEPLOY = (PHASE_STARTING, PHASE_SPEC_LOAD, PHASE_NAMESPACE, PHASE_POLICIES, PHASE_APPLY, PHASE_WAIT_READY, PHASE_OUTPUTS)
PHASES_DESTROY = (PHASE_STARTING, PHASE_DELETE, PHASE_WAIT_GONE, PHASE_CLEANUP)
PHASES_PAUSE = (PHASE_STARTING, PHASE_SCALE_DOWN, PHASE_WAIT_STOPPED)
PHASES_RESUME = (PHASE_STARTING, PHASE_SCALE_UP, PHASE_WAIT_READY)
PHASES_REDEPLOY = (PHASE_STARTING, PHASE_RESTART, PHASE_WAIT_READY)

# A container that sits in one of these is not going to come up by waiting.
_FATAL_WAITING = {
    "ImagePullBackOff": "the image cannot be pulled (does it exist, is the digest right and the registry public?)",
    "InvalidImageName": "the image reference is invalid",
    "CreateContainerConfigError": "the container configuration is invalid",
    "CreateContainerError": "the container could not be created",
}

KubeFactory = Callable[[], Kube]
_kube_factory: KubeFactory = KubeApi


def set_kube_factory(factory: KubeFactory) -> None:
    """Replace how the cluster connection is made (tests)."""
    global _kube_factory
    _kube_factory = factory


def limits() -> PlatformLimits:
    prefixes = tuple(p.strip() for p in settings.APP_IMAGE_REGISTRY_ALLOWLIST.split(",") if p.strip())
    storage = settings.APP_MAX_STORAGE
    return PlatformLimits(
        image_registry_allowlist=prefixes,
        max_cpu_millicores=parse_cpu_millicores(settings.APP_MAX_CPU),
        max_memory_mib=parse_memory_mib(settings.APP_MAX_MEMORY),
        max_storage_mib=int(storage[:-2]) * (1024 if storage.endswith("Gi") else 1),
    )


def render_settings() -> RenderSettings:
    return RenderSettings(
        zone=settings.K8S_ZONE,
        app_domain_override=settings.K8S_APP_DOMAIN,
        ingress_class=settings.K8S_INGRESS_CLASS,
        ingress_namespace=settings.K8S_INGRESS_NAMESPACE,
        tls_secret=settings.K8S_TLS_SECRET,
        cluster_issuer=settings.K8S_CLUSTER_ISSUER,
        storage_class=settings.K8S_STORAGE_CLASS,
        node_selector=json.loads(settings.K8S_STUDENT_NODE_SELECTOR or "{}"),
        tolerations=tuple(json.loads(settings.K8S_STUDENT_TOLERATIONS or "[]")),
        extra_egress_except=tuple(c.strip() for c in settings.K8S_EXTRA_EGRESS_EXCEPT.split(",") if c.strip()),
    )


def account_name(email: str) -> str:
    """The account name of a member: the address's local part, [a-z0-9-] only."""
    return re.sub(r"[^a-z0-9]+", "-", email.split("@", 1)[0].lower()).strip("-") or "user"


def _teams(teams: dict[str, list]) -> list[Team]:
    return [
        Team(name, tuple(dict.fromkeys(account_name(m.get("email", "")) for m in members)))
        for name, members in sorted(teams.items())
    ]


def _logger(job: JobEvents, action: str, deployment_id: str, phases: tuple[str, ...]):
    task_logger = get_logger(f"{action}:{deployment_id}", correlation_id=deployment_id)
    task_logger.set_event_emitter(lambda name, payload: job.send_event(name, deployment_id=deployment_id, **payload))
    return task_logger, _PhaseTracker(task_logger, phases)


def _fail(task_logger: Any, deployment_id: str, exc: Exception, action: str) -> Failure:
    task_logger.error(f"{action.capitalize()} failed: {exc}", category=LogCategory.ERROR)
    return Failure(message=str(exc), deployment_id=deployment_id, logs_dict=task_logger.get_logs_dict(), terraform_outputs={})


def _result(task_logger: Any, deployment_id: str, **extra: Any) -> dict[str, Any]:
    return {"status": "success", "deployment_id": deployment_id, "logs": task_logger.get_logs_dict(), **extra}


def explain(snap: Snapshot) -> str | None:
    """A readable reason when the namespace cannot become ready, else None."""
    for pod in snap.pods:
        if pod.waiting_reason in _FATAL_WAITING:
            return f"Pod {pod.name}: {_FATAL_WAITING[pod.waiting_reason]} ({pod.waiting_reason})"
        if pod.waiting_reason == "CrashLoopBackOff" and pod.restarts >= 2:
            return f"Pod {pod.name}: the container keeps crashing (CrashLoopBackOff, {pod.restarts} restarts)"
        if pod.unschedulable:
            return f"Pod {pod.name} cannot be scheduled, the cluster has no capacity: {pod.message or ''}".strip()
    for event in snap.events:
        if event.reason == "FailedCreate" and "exceeded quota" in event.message:
            return f"{event.object}: resource quota exceeded: {event.message}"
    return None


class Cancelled(RuntimeError):
    """The deployment was cancelled while the job ran."""


def _check_cancelled(job: JobEvents) -> None:
    is_cancelled = getattr(job, "is_cancelled", None)
    if is_cancelled is not None and is_cancelled():
        raise Cancelled("the deployment was cancelled")


def wait_until(
    kube: Kube,
    namespace: str,
    done: Callable[[Snapshot], bool],
    timeout: float,
    what: str,
    check_failure: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    stop: Callable[[], None] | None = None,
) -> Snapshot:
    """Poll the namespace until ``done``; raise with a readable reason on a fatal state or timeout."""
    deadline = time.monotonic() + timeout
    while True:
        if stop is not None:
            stop()
        snap = kube.snapshot(namespace)
        if check_failure and (not snap.exists or snap.terminating):
            raise RuntimeError("the namespace disappeared while waiting (the deployment was cancelled or destroyed)")
        if done(snap):
            return snap
        reason = explain(snap) if check_failure else None
        if reason:
            raise RuntimeError(reason)
        if time.monotonic() > deadline:
            raise RuntimeError(f"timed out after {int(timeout)} s waiting for {what}")
        sleep(settings.K8S_POLL_INTERVAL_SECONDS)


def _all_ready(expected: set[str]) -> Callable[[Snapshot], bool]:
    def check(snap: Snapshot) -> bool:
        ready = {s.name for s in snap.statefulsets if s.replicas >= 1 and s.ready_replicas >= 1}
        return expected <= ready and all(p.ready for p in snap.pods if p.workload in expected)

    return check


def _bootstrap_objects(dep: DeploymentCtx) -> list[dict[str, Any]]:
    """The RoleBinding that gives the worker its rights inside the new namespace."""
    return [
        {
            "apiVersion": "rbac.authorization.k8s.io/v1",
            "kind": "RoleBinding",
            "metadata": {
                "name": "appstore-deployer",
                "namespace": dep.namespace,
                "labels": {"appstore.dhbw/deployment-id": dep.id, "app.kubernetes.io/managed-by": "appstore"},
            },
            "roleRef": {
                "apiGroup": "rbac.authorization.k8s.io",
                "kind": "ClusterRole",
                "name": settings.K8S_DEPLOYER_CLUSTER_ROLE,
            },
            "subjects": [
                {
                    "kind": "ServiceAccount",
                    "name": settings.K8S_WORKER_SERVICE_ACCOUNT,
                    "namespace": settings.K8S_WORKER_NAMESPACE,
                }
            ],
        }
    ]


def _file_contents(user_vars: dict[str, Any], spec: AppSpec) -> dict[str, dict[str, bytes]]:
    """Uploaded files per file variable as ``{slot: bytes}``, from ``userInputVar.terraform``."""
    import base64

    terraform = user_vars.get("terraform") or {}
    out: dict[str, dict[str, bytes]] = {}
    for v in spec.variables:
        if v.type != "file":
            continue
        slots = terraform.get(v.name)
        if isinstance(slots, dict):
            out[v.name] = {k: base64.b64decode(s["content_b64"]) for k, s in slots.items() if "content_b64" in s}
    return out


def build_outputs(
    spec: AppSpec, dep: DeploymentCtx, teams: list[Team], passwords: dict[str, str]
) -> dict[str, Any]:
    """``team_vms`` and ``user_accounts`` like an OpenTofu app produces them.

    Account keys are ``<team>-<account>`` (the account is the address's local
    part), which is exactly what ``my-access`` looks for. For ``scope: team``
    every member of the team gets the team's access; for ``scope: user`` each
    person gets their own workload and password.
    """
    entries = render_access(spec, dep, teams, render_settings(), passwords)
    team_vms: dict[str, Any] = {}
    accounts: dict[str, Any] = {}
    for e in entries:
        host = (e.url or "").split("://", 1)[-1].split("/", 1)[0]
        team_vms.setdefault(e.team, {"url": e.url, "workloads": []})["workloads"].append(e.workload)
        members = [e.user] if e.user else list(next(t.members for t in teams if t.name == e.team))
        for member in members:
            accounts[f"{e.team}-{member}"] = {
                "type": "password",
                "username": e.username or member,
                "auth": e.password,
                "url": e.url,
                "ip": host,
                "port": 443,
            }
    return {
        "team_vms": {"value": team_vms, "type": ["map", "dynamic"], "sensitive": False},
        "user_accounts": {"value": accounts, "type": ["map", "dynamic"], "sensitive": True},
    }


def deploy_application(
    job: JobEvents,
    deployment_id: str,
    user_vars: dict[str, Any],
    teams: dict[str, list] | None = None,
    commit_sha: str = "",
    spec: dict[str, Any] | None = None,
    course: str = "",
    owner: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Deploy a pod app: namespace, policies, workloads, wait until ready.

    On any error the half-created namespace is deleted again, then ``Failure``
    is raised with a readable reason (ImagePullBackOff, no capacity, quota, ...).
    """
    task_logger, tracker = _logger(job, "deploy", deployment_id, PHASES_DEPLOY)
    dep = DeploymentCtx(id=deployment_id, course=course, owner=owner)
    kube: Kube | None = None
    try:
        tracker.mark(PHASE_STARTING, "Starting")
        tracker.mark(PHASE_SPEC_LOAD, "Validating appstore.yaml")
        try:
            app = parse_spec(spec or {}, limits())
        except SpecValidationError as e:
            raise RuntimeError(f"appstore.yaml is invalid: {e}") from None
        if app.runtime != "kubernetes":
            raise RuntimeError("the spec is not a kubernetes app")
        team_list = _teams(teams or {})
        refs = workload_refs(app, team_list)
        if not refs:
            raise RuntimeError("the deployment has no teams or members to run workloads for")
        passwords = {r.name: secrets.token_urlsafe(12) for r in refs}
        objects = render(
            app,
            dep,
            team_list,
            render_settings(),
            passwords,
            files=_file_contents(user_vars, app),
            variable_values=user_vars.get("terraform") or {},
        )
        kube = _kube_factory()

        _check_cancelled(job)
        tracker.mark(PHASE_NAMESPACE, f"Creating namespace {dep.namespace}")
        kube.apply(objects[0])
        for o in _bootstrap_objects(dep):
            kube.apply(o)
        tracker.mark(PHASE_POLICIES, "Applying quota and network policies")
        policy_kinds = {"ResourceQuota", "LimitRange", "NetworkPolicy"}
        for o in (o for o in objects if o["kind"] in policy_kinds):
            kube.apply(o)
        _check_cancelled(job)
        tracker.mark(PHASE_APPLY, f"Applying {len(refs)} workload(s)")
        for o in (o for o in objects[1:] if o["kind"] not in policy_kinds):
            kube.apply(o)
        tracker.mark(PHASE_WAIT_READY, "Waiting for the pods to become ready")
        wait_until(
            kube,
            dep.namespace,
            _all_ready({r.name for r in refs}),
            settings.K8S_READY_TIMEOUT_SECONDS,
            "the pods",
            stop=lambda: _check_cancelled(job),
        )
        tracker.mark(PHASE_OUTPUTS, "Collecting access data")
        outputs = build_outputs(app, dep, team_list, passwords)
        task_logger.success(f"Deployment {deployment_id} is running in {dep.namespace}", category=LogCategory.STATUS)
    except Exception as e:
        if kube is not None:
            _cleanup_after_failure(kube, dep, task_logger)
        raise _fail(task_logger, deployment_id, e, "deploy") from None
    return _result(
        task_logger,
        deployment_id,
        commit_info={"hash": commit_sha, "message": "", "author": ""},
        terraform_outputs=outputs,
    )


def _cleanup_after_failure(kube: Kube, dep: DeploymentCtx, task_logger: Any) -> None:
    try:
        kube.delete_namespace(dep.namespace)
        task_logger.info(f"Removed {dep.namespace} after the failure", category=LogCategory.OPERATION)
    except Exception as e:  # best effort; the failure being reported is the original one
        task_logger.warning(f"Could not remove {dep.namespace}: {e}", category=LogCategory.WARNING)


def destroy_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Delete the namespace (which removes everything in it) and wait until it is gone."""
    task_logger, tracker = _logger(job, "destroy", deployment_id, PHASES_DESTROY)
    dep = DeploymentCtx(id=deployment_id)
    try:
        tracker.mark(PHASE_STARTING, "Starting")
        kube = _kube_factory()
        tracker.mark(PHASE_DELETE, f"Deleting namespace {dep.namespace}")
        kube.delete_namespace(dep.namespace)
        tracker.mark(PHASE_WAIT_GONE, "Waiting for the namespace to disappear")
        wait_until(
            kube, dep.namespace, lambda s: not s.exists, settings.K8S_DELETE_TIMEOUT_SECONDS, "the namespace",
            check_failure=False,
        )
        tracker.mark(PHASE_CLEANUP, "Verifying nothing is left")
        left = kube.namespaces(deployment_selector(deployment_id))
        if left:
            raise RuntimeError(f"objects of this deployment are still in the cluster: {', '.join(left)}")
        task_logger.success(f"Destroyed {deployment_id}", category=LogCategory.STATUS)
    except Exception as e:
        raise _fail(task_logger, deployment_id, e, "destroy") from None
    return _result(task_logger, deployment_id, terraform_outputs={})


def pause_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Scale every workload to zero; volumes and secrets stay, so resume brings the data back."""
    task_logger, tracker = _logger(job, "pause", deployment_id, PHASES_PAUSE)
    dep = DeploymentCtx(id=deployment_id)
    try:
        tracker.mark(PHASE_STARTING, "Starting")
        kube = _kube_factory()
        tracker.mark(PHASE_SCALE_DOWN, "Stopping the workloads")
        snap = kube.snapshot(dep.namespace)
        if not snap.exists:
            raise RuntimeError(f"namespace {dep.namespace} does not exist")
        for s in snap.statefulsets:
            kube.scale(dep.namespace, s.name, 0)
        tracker.mark(PHASE_WAIT_STOPPED, "Waiting for the pods to stop")
        wait_until(kube, dep.namespace, lambda s: not s.pods, settings.K8S_DELETE_TIMEOUT_SECONDS, "the pods to stop")
        task_logger.success("Paused", category=LogCategory.STATUS)
    except Exception as e:
        raise _fail(task_logger, deployment_id, e, "pause") from None
    return _result(task_logger, deployment_id, terraform_outputs={})


def resume_deployment(job: JobEvents, deployment_id: str, **_: Any) -> dict[str, Any]:
    """Scale every workload back to one and wait until it is ready."""
    task_logger, tracker = _logger(job, "resume", deployment_id, PHASES_RESUME)
    dep = DeploymentCtx(id=deployment_id)
    try:
        tracker.mark(PHASE_STARTING, "Starting")
        kube = _kube_factory()
        tracker.mark(PHASE_SCALE_UP, "Starting the workloads")
        snap = kube.snapshot(dep.namespace)
        if not snap.exists:
            raise RuntimeError(f"namespace {dep.namespace} does not exist")
        names = {s.name for s in snap.statefulsets}
        for name in names:
            kube.scale(dep.namespace, name, 1)
        tracker.mark(PHASE_WAIT_READY, "Waiting for the pods to become ready")
        wait_until(kube, dep.namespace, _all_ready(names), settings.K8S_READY_TIMEOUT_SECONDS, "the pods")
        task_logger.success("Resumed", category=LogCategory.STATUS)
    except Exception as e:
        raise _fail(task_logger, deployment_id, e, "resume") from None
    return _result(task_logger, deployment_id, terraform_outputs={})


def redeploy_resource(
    job: JobEvents, deployment_id: str, resource_address: str | None = None, **_: Any
) -> dict[str, Any]:
    """Restart one team's/person's workload by deleting its pod; the data stays.

    ``resource_address`` is the workload name; ``reset:<name>`` also deletes
    the volume, so the workload starts from scratch.
    """
    task_logger, tracker = _logger(job, "redeploy", deployment_id, PHASES_REDEPLOY)
    dep = DeploymentCtx(id=deployment_id)
    try:
        tracker.mark(PHASE_STARTING, "Starting")
        address = resource_address or ""
        reset = address.startswith("reset:")
        workload = address.removeprefix("reset:")
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", workload):
            raise RuntimeError(f"invalid workload name {workload!r}")
        kube = _kube_factory()
        snap = kube.snapshot(dep.namespace)
        if workload not in {s.name for s in snap.statefulsets}:
            raise RuntimeError(f"unknown workload {workload!r}")
        old_pods = {p.name: p.uid for p in snap.pods if p.workload == workload}
        tracker.mark(PHASE_RESTART, f"Resetting {workload}" if reset else f"Restarting {workload}")
        if reset:
            kube.scale(dep.namespace, workload, 0)
            wait_until(
                kube, dep.namespace, lambda s: not [p for p in s.pods if p.workload == workload],
                settings.K8S_DELETE_TIMEOUT_SECONDS, "the pod to stop",
            )
            kube.delete_pvcs(dep.namespace, workload)
            # The claim is only marked for deletion while it is protected; a pod
            # started now would collide with it (name and quota).
            wait_until(
                kube,
                dep.namespace,
                lambda s: not [c for c, w in s.pvcs if w == workload],
                settings.K8S_DELETE_TIMEOUT_SECONDS,
                "the volume to be deleted",
            )
            kube.scale(dep.namespace, workload, 1)
        else:
            for pod_name in old_pods:
                kube.delete_pod(dep.namespace, pod_name)
        tracker.mark(PHASE_WAIT_READY, "Waiting for the pod to become ready")
        ready = _all_ready({workload})
        old_uids = set(old_pods.values())
        # The old pod may still look ready for a moment after it was deleted.
        wait_until(
            kube,
            dep.namespace,
            lambda s: not any(p.uid in old_uids for p in s.pods) and ready(s),
            settings.K8S_READY_TIMEOUT_SECONDS,
            "the pod",
        )
        task_logger.success(f"{workload} is running again", category=LogCategory.STATUS)
    except Exception as e:
        raise _fail(task_logger, deployment_id, e, "redeploy") from None
    return _result(task_logger, deployment_id, terraform_outputs={})
