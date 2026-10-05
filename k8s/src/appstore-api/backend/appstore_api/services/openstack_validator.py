"""Check an OpenStack credential against Keystone and learn its project (plan AP5).

A credential is only stored after Keystone issued a project-scoped token for
it. The project id and name are taken from that token: they decide who is a
peer in a project (E2), so a value the user typed must never count.

The timeout is the session's (``api_timeout``), not the process-wide socket
default the original set and reset around the call, which raced with every
other request thread.
"""

from __future__ import annotations

from dataclasses import dataclass

import openstack
from keystoneauth1 import exceptions as ks_exc
from keystoneauth1.identity.base import BaseIdentityPlugin
from openstack import exceptions as os_exc

from appstore_api.config import settings
from appstore_api.schemas import OpenStackCredentialUpsert
from appstore_api.services.openstack_client import connect_kwargs
from appstore_api.services.openstack_simulation import simulated_project

TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Scope:
    """The project a validated credential is scoped to, as Keystone reports it."""

    project_id: str
    project_name: str | None


class CredentialRejected(Exception):
    """Keystone did not accept the credential; ``reason`` is safe to show.

    ``reason`` is one of ``invalid_credentials``, ``project_not_found``,
    ``unreachable``, ``rejected``, ``not_project_scoped``, ``error``; the UI
    translates it. The secret is never part of it.
    """

    def __init__(self, reason: str, status: int | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def payload_to_creds(payload: OpenStackCredentialUpsert) -> dict:
    """Convert an upsert payload into the plain dict ``connect_kwargs`` expects."""
    return {
        "auth_type": payload.auth_type.value,
        "auth_url": payload.auth_url,
        "region_name": payload.region_name,
        "interface": payload.interface,
        "identity_api_version": payload.identity_api_version,
        "project_id": payload.project_id,
        "project_name": payload.project_name,
        "user_domain_name": payload.user_domain_name,
        "project_domain_name": payload.project_domain_name,
        "identifier": payload.identifier,
        "secret": payload.secret,
    }


def validate(payload: OpenStackCredentialUpsert) -> Scope:
    """Get a token; return the project it is scoped to, or raise ``CredentialRejected``.

    Blocking network call (up to ``TIMEOUT_SECONDS`` per request). With
    ``OPENSTACK_SIMULATE`` no request is made and the project comes from
    ``simulated_project``.
    """
    if settings.OPENSTACK_SIMULATE:
        sim_id, sim_name = simulated_project(payload.project_id, payload.project_name, payload.identifier)
        return Scope(project_id=sim_id, project_name=sim_name)
    try:
        conn = openstack.connect(api_timeout=TIMEOUT_SECONDS, **connect_kwargs(payload_to_creds(payload)))
        try:
            auth = conn.session.auth
            if not isinstance(auth, BaseIdentityPlugin):
                raise CredentialRejected("error")
            access = auth.get_access(conn.session)
        finally:
            conn.close()
    except CredentialRejected:
        raise
    except (os_exc.HttpException, ks_exc.HttpError) as e:
        status = getattr(e, "status_code", None) or getattr(e, "http_status", None)
        if status in (401, 403):
            raise CredentialRejected("invalid_credentials", status) from None
        if status == 404:
            raise CredentialRejected("project_not_found", status) from None
        raise CredentialRejected("rejected", status) from None
    except (ks_exc.ConnectionError, ks_exc.ConnectTimeout, TimeoutError, OSError):
        raise CredentialRejected("unreachable") from None
    except Exception:
        # Unknown SDK errors may quote the request body; say nothing more.
        raise CredentialRejected("error") from None
    project_id = getattr(access, "project_id", None)
    if not project_id:
        raise CredentialRejected("not_project_scoped")
    return Scope(project_id=project_id, project_name=getattr(access, "project_name", None))
