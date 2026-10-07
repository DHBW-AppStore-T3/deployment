"""Live status of pod deployments, read from the cluster.

The Infrastructure tab shows, for a deployment that runs as pods, one row per
workload: ready, restarts, phase, URL and the last warning. Nothing is cached
in the database; the namespace ``dep-<id>`` is the state (issue #4, 2.6).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from appstore_api.config import settings
from appstore_shared.k8s.kube import Kube, KubeApi, Snapshot
from appstore_shared.k8s.render import DeploymentCtx

logger = logging.getLogger(__name__)

_factory: Callable[[], Kube] | None = None


def set_kube_factory(factory: Callable[[], Kube] | None) -> None:
    """Replace how the cluster connection is made (tests)."""
    global _factory
    _factory = factory


def _kube() -> Kube | None:
    if _factory is not None:
        return _factory()
    if not settings.K8S_STATUS_ENABLED:
        return None
    return KubeApi()


def _phase(snap: Snapshot, workload: str, replicas: int) -> tuple[str, bool, int]:
    pods = [p for p in snap.pods if p.workload == workload]
    if replicas == 0 and not pods:
        return "Stopped", False, 0
    if not pods:
        return "Pending", False, 0
    pod = pods[0]
    if pod.unschedulable:
        return "Unschedulable", False, pod.restarts
    return pod.waiting_reason or pod.phase, pod.ready, pod.restarts


def workload_views(deployment_id, namespace: str) -> list[dict] | None:
    """Rows for the Infrastructure tab, or None when the cluster cannot be asked."""
    kube = _kube()
    if kube is None:
        return None
    try:
        snap = kube.snapshot(namespace)
    except Exception:
        logger.exception("could not read namespace %s", namespace)
        return None
    dep = DeploymentCtx(id=str(deployment_id))
    rows = []
    for s in snap.statefulsets:
        phase, ready, restarts = _phase(snap, s.name, s.replicas)
        event = next((f"{e.reason}: {e.message}" for e in reversed(snap.events) if s.name in e.object), None)
        rows.append(
            {
                "workload": s.name,
                "team": s.team or None,
                "user": s.user or None,
                "ready": ready,
                "restarts": restarts,
                "phase": phase,
                "url": f"https://{s.name}-{dep.short_id}.apps.{settings.K8S_ZONE}" if settings.K8S_ZONE else None,
                "lastEvent": event,
            }
        )
    return rows
