"""A stand-in for OpenStack in development (``OPENSTACK_SIMULATE=true``, plan AP7).

The counterpart of the worker's ``WORKER_SIMULATE``: students develop the UI
and the API without a cloud. Saving a credential then needs no Keystone (the
project is derived from what was entered), and the resource picker, the quota
and the live view of a deployment's servers answer from the fixed data below
through the same code paths as with a real connection.

Only allowed with ``API_MODE=development`` (config validation). Used by
``openstack_client._connection`` and ``openstack_validator.validate``. Only the
proxy methods this API calls exist; anything else raises AttributeError.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace as NS
from typing import Any

_NETWORKS = [
    NS(id="sim-net-internal", name="internal", description="Projektnetz", is_shared=False,
       is_router_external=False, status="ACTIVE"),
    NS(id="sim-net-public", name="public", description="Floating-IP-Pool", is_shared=True,
       is_router_external=True, status="ACTIVE"),
]
_SUBNETS = [
    NS(id="sim-subnet-internal", name="internal-v4", cidr="10.0.0.0/24", ip_version=4,
       network_id="sim-net-internal", gateway_ip="10.0.0.1"),
]
_FLAVORS = [
    NS(id="sim-flavor-small", name="sim.small", vcpus=1, ram=2048, disk=20, is_public=True),
    NS(id="sim-flavor-medium", name="sim.medium", vcpus=2, ram=4096, disk=40, is_public=True),
    NS(id="sim-flavor-large", name="sim.large", vcpus=4, ram=8192, disk=80, is_public=True),
]
_IMAGES = [
    NS(id="sim-image-ubuntu", name="Ubuntu 22.04", status="active", visibility="public",
       size=2_361_393_152, disk_format="qcow2"),
    NS(id="sim-image-debian", name="Debian 12", status="active", visibility="public",
       size=1_073_741_824, disk_format="qcow2"),
]
_SECURITY_GROUPS = [
    NS(id="sim-sg-default", name="default", description="Standard-Sicherheitsgruppe"),
    NS(id="sim-sg-web", name="web", description="HTTP und HTTPS"),
]
_KEYPAIRS = [NS(name="sim-key", fingerprint="00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff", type="ssh")]
_ROUTERS = [NS(id="sim-router", name="router", status="ACTIVE",
               external_gateway_info={"network_id": "sim-net-public"})]
_ZONES = [NS(name="nova", state={"available": True})]


def simulated_project(project_id: str | None, project_name: str | None, identifier: str) -> tuple[str, str]:
    """Return ``(project_id, project_name)`` a simulated Keystone scopes a credential to.

    What was entered decides it, so two people who enter the same project
    become project peers, as with real credentials of one project. Without
    a project id the id is a stable hash of the project name (or, lacking
    that, of the credential identifier).
    """
    if project_id:
        return project_id, project_name or project_id
    seed = project_name or identifier
    return "sim-" + hashlib.sha256(seed.encode()).hexdigest()[:12], project_name or "Simuliertes Projekt"


def _quota(**limits: int) -> NS:
    """A quota object with the given limits as attributes, like the SDK's."""
    return NS(**limits)


class _Compute:
    """Fake ``conn.compute`` (Nova): fixed flavors/keypairs/quota; every server id exists and is ACTIVE."""

    def flavors(self, **_: Any):
        return list(_FLAVORS)

    def keypairs(self, **_: Any):
        return list(_KEYPAIRS)

    def availability_zones(self, **_: Any):
        return list(_ZONES)

    def get_quota_set(self, _project_id: str):
        return _quota(instances=10, cores=20, ram=40960)

    def get_limits(self):
        return NS(absolute=NS(total_instances_used=2, total_cores_used=4, total_ram_used=8192))

    def find_server(self, server_id: str, **_: Any):
        return NS(
            id=server_id,
            name=f"sim-{server_id[:8]}",
            status="ACTIVE",
            task_state=None,
            vm_state="active",
            power_state=1,
            fault=None,
            flavor={"original_name": "sim.small", "vcpus": 1, "ram": 2048, "disk": 20},
            image={"id": "sim-image-ubuntu"},
            availability_zone="nova",
            launched_at=None,
            addresses={"internal": [{"addr": "10.0.0.10", "version": 4, "OS-EXT-IPS:type": "fixed"}]},
            metadata={"simulated": "true"},
        )

    def volume_attachments(self, *_: Any, **__: Any):
        return []


class _Network:
    """Fake ``conn.network`` (Neutron): fixed networks/SGs/routers; no ports, no floating IPs."""

    def networks(self, **_: Any):
        return list(_NETWORKS)

    def subnets(self, **filters: Any):
        network_id = filters.get("network_id")
        return [s for s in _SUBNETS if network_id in (None, s.network_id)]

    def security_groups(self, **_: Any):
        return list(_SECURITY_GROUPS)

    def security_group_rules(self, **_: Any):
        return [NS(id="sim-rule")]

    def find_security_group(self, *_: Any, **__: Any):
        return None

    def routers(self, **_: Any):
        return list(_ROUTERS)

    def ips(self, **_: Any):
        return []

    def ports(self, **_: Any):
        return []

    def availability_zones(self, **_: Any):
        return list(_ZONES)

    def get_quota(self, _project_id: str):
        return _quota(floatingip=5, security_group=10, security_group_rule=100, network=10, port=50, router=2)


class _Image:
    """Fake ``conn.image`` (Glance) with two public images."""

    def images(self, **filters: Any):
        status = filters.get("status")
        return [i for i in _IMAGES if status in (None, i.status)]

    def find_image(self, name_or_id: str, **_: Any):
        return next((i for i in _IMAGES if name_or_id in (i.id, i.name)), None)


class _Volume:
    """Fake ``conn.volume`` (Cinder, resource picker and quota): no volumes or snapshots."""

    def volumes(self, **_: Any):
        return []

    def snapshots(self, **_: Any):
        return []

    def availability_zones(self, **_: Any):
        return list(_ZONES)

    def get_quota_set(self, _project_id: str):
        return _quota(volumes=10, snapshots=10, gigabytes=500)


class _BlockStorage:
    """Fake ``conn.block_storage`` (Cinder, live view): no volume is ever found."""

    def find_volume(self, *_: Any, **__: Any):
        return None


class SimulatedConnection:
    """What ``openstack.connect`` returns, for the calls this API makes."""

    def __init__(self) -> None:
        self.compute = _Compute()
        self.network = _Network()
        self.image = _Image()
        self.volume = _Volume()
        self.block_storage = _BlockStorage()

    def close(self) -> None:
        pass
