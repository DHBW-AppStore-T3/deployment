"""The app contract v2 (``appstore.yaml``) as the API uses it.

An app version either has an ``appstore.yaml`` at its commit (it runs as pods)
or not (it is a Terraform/Packer app that runs as VMs). This module reads the
file from exactly the commit being submitted, approved or deployed, validates it
against the platform limits and derives what the rest of the API needs: the
runtime, the spec hash and image digests an approval covers, and the wizard
variables.
"""

from __future__ import annotations

import copy
import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from appstore_api.config import settings
from appstore_shared.k8s.spec import (
    AppSpec,
    PlatformLimits,
    SpecValidationError,
    parse_cpu_millicores,
    parse_memory_mib,
    parse_spec,
)

SPEC_FILE = "appstore.yaml"
RUNTIME_K8S = "kubernetes"
RUNTIME_VM = "openstack-vm"
# os_project_id of deployments that live in the cluster, not in an OpenStack project.
K8S_PROJECT = "kubernetes"


@dataclass(frozen=True)
class LoadedSpec:
    spec: AppSpec
    sha256: str
    image_digests: tuple[str, ...]

    @property
    def runtime(self) -> str:
        return RUNTIME_K8S if self.spec.runtime == "kubernetes" else RUNTIME_VM


def platform_limits() -> PlatformLimits:
    """Limits from the environment (``APP_IMAGE_REGISTRY_ALLOWLIST``, ``APP_MAX_*``)."""
    prefixes = tuple(p.strip() for p in settings.APP_IMAGE_REGISTRY_ALLOWLIST.split(",") if p.strip())
    storage = settings.APP_MAX_STORAGE
    return PlatformLimits(
        image_registry_allowlist=prefixes,
        max_cpu_millicores=parse_cpu_millicores(settings.APP_MAX_CPU),
        max_memory_mib=parse_memory_mib(settings.APP_MAX_MEMORY),
        max_storage_mib=int(storage[:-2]) * (1024 if storage.endswith("Gi") else 1),
    )


def parse_checked(text: str | bytes) -> LoadedSpec:
    """Parse and validate ``text``; 422 with a field path per problem (``errors``)."""
    try:
        spec = parse_spec(text, platform_limits())
    except SpecValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "appstore.yaml is invalid", "errors": exc.errors},
        ) from exc
    raw = text if isinstance(text, bytes) else text.encode()
    digests = tuple(
        sorted({c.image.split("@", 1)[1] for c in spec.workload.containers}) if spec.workload else ()
    )
    return LoadedSpec(spec=spec, sha256=hashlib.sha256(raw).hexdigest(), image_digests=digests)


_CACHE: OrderedDict[tuple[str, str], LoadedSpec | None] = OrderedDict()
_CACHE_MAX = 256
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _CACHE.clear()


def read_spec_from_repo(repo_path: str) -> LoadedSpec | None:
    """The validated spec in a cloned commit, or None for a VM app."""
    path = os.path.join(repo_path, SPEC_FILE)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return parse_checked(fh.read())


def remember(git_link: str, sha: str, loaded: LoadedSpec | None) -> None:
    with _lock:
        _CACHE[(git_link, sha)] = loaded
        _CACHE.move_to_end((git_link, sha))
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)


def cached(git_link: str, sha: str) -> tuple[bool, LoadedSpec | None]:
    with _lock:
        if (git_link, sha) in _CACHE:
            _CACHE.move_to_end((git_link, sha))
            return True, _CACHE[(git_link, sha)]
    return False, None


def spec_variables(spec: AppSpec) -> list[dict[str, Any]]:
    """The spec's variables in the shape ``GET /apps/{id}/variables`` returns.

    Same keys as the Terraform variables, so the wizard renders them with the
    same components: a file variable is ``@openstack:file``-like (``osType``
    ``file``), an enum has ``osType`` ``enum`` with its values.
    """
    out: list[dict[str, Any]] = []
    for v in spec.variables:
        entry: dict[str, Any] = {
            "name": v.name,
            "type": "string",
            "description": None,
            "default": v.default,
            "required": v.default is None and v.type != "enum",
            "source": "appstore",
            "osType": None,
            "osMode": None,
            "osMulti": None,
            "osScope": None,
            "varScope": v.scope if v.scope != "deployment" else None,
            "fileExtensions": None,
            "markerError": None,
            "template_key": None,
        }
        if v.type == "file":
            entry.update(osType="file", osScope="file", fileExtensions=[e.lstrip(".") for e in v.ext] or None)
        elif v.type == "enum":
            entry.update(osType="enum", values=list(v.values), required=False)
        out.append(copy.deepcopy(entry))
    return out
