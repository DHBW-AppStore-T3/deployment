"""Stage-1 live fetch of the resource list: per-VM failures and the time budget."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from appstore_api.services import deployment_status
from appstore_api.services.deployment_status import DeploymentResourceView


def _view(provider_id: str) -> DeploymentResourceView:
    return DeploymentResourceView(
        address=f"openstack_compute_instance_v2.vm[\"{provider_id}\"]",
        type="openstack_compute_instance_v2",
        category="instance",
        team=None,
        provider_id=provider_id,
        display_name=provider_id,
    )


def test_slow_failed_and_missing_servers_degrade_per_vm(monkeypatch):
    """A VM that does not answer within the budget is ``stale`` and the call
    returns without waiting for it; errors and missing servers stay per VM."""
    monkeypatch.setattr(deployment_status, "_STAGE1_BUDGET_S", 0.3)
    release = threading.Event()
    healthy = MagicMock(status="ACTIVE", flavor={}, addresses={}, metadata={})

    def find_server(provider_id, ignore_missing=True):
        if provider_id == "slow":
            release.wait(5)
        if provider_id == "broken":
            raise RuntimeError("boom")
        return None if provider_id == "gone" else healthy

    conn = MagicMock()
    conn.compute.find_server.side_effect = find_server
    views = [_view(p) for p in ("ok", "slow", "broken", "gone")]

    started = time.monotonic()
    deployment_status._enrich_instances_stage1(conn, views)
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 2
    assert [v.drift for v in views] == ["in_sync", "stale", "stale", "missing"]
    assert views[0].lifecycle is not None
