"""The caller's OpenStack credentials, one per project (plan AP5).

All endpoints scope to the caller (`current_user`) — there is no
`{user_id}` path parameter, and another person's credential id answers 404.
Responses never contain identifier or secret material.

A credential is stored only after Keystone accepted it; its project comes
from the token, so holding one proves access to that project (E2). Saving a
credential for a project that already has one replaces it: that is how a
secret is rotated, and it is allowed at any time. Deleting is refused while
the caller owns live deployments in the project, which would otherwise be
left without anyone able to run them.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from appstore_api.auth import get_current_user
from appstore_api.crud import deployments as crud_deployments
from appstore_api.crud import locks as crud_locks
from appstore_api.crud import openstack_credentials as crud_creds
from appstore_api.database import get_db
from appstore_api.models import User, UserOpenStackCredential
from appstore_api.schemas import (
    OpenStackCredentialFromYaml,
    OpenStackCredentialResponse,
    OpenStackCredentialUpsert,
)
from appstore_api.services import clouds_yaml_parser, openstack_client, openstack_validator

router = APIRouter()


def _response(db: Session, row: UserOpenStackCredential) -> OpenStackCredentialResponse:
    """Serialize a credential row, adding how many live deployments of its owner use its project."""
    response = OpenStackCredentialResponse.model_validate(row)
    response.active_deployments = crud_deployments.count_active_user_deployments(db, row.userId, row.project_id)
    return response


def _rejected(e: openstack_validator.CredentialRejected) -> HTTPException:
    """422 ``openstack_credentials_invalid`` carrying Keystone's rejection reason as ``cause``."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"reason": "openstack_credentials_invalid", "cause": e.reason},
    )


def _save(db: Session, user: User, payload: OpenStackCredentialUpsert, response: Response):
    """Validate ``payload`` against Keystone, then insert or replace the caller's credential.

    The project id/name come from the Keystone token, not from the payload.
    Sets the response status to 201 (new project) or 200 (replaced) and drops
    any cached OpenStack connection for the credential. Commits via
    ``crud_creds.save``. Raises the 422 from ``_rejected`` when Keystone refuses.
    """
    try:
        scope = openstack_validator.validate(payload)
    except openstack_validator.CredentialRejected as e:
        raise _rejected(e) from None
    # Serialized with deploy dispatch, which reads the credential in its TX.
    crud_locks.acquire_user_xact_lock(db, user.userId)
    row, created = crud_creds.save(db, user.userId, payload, scope.project_id, scope.project_name)
    openstack_client.invalidate(row.credentialId)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(db, row)


@router.get("/me/openstack-credentials", response_model=list[OpenStackCredentialResponse])
def list_my_credentials(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List the caller's OpenStack credentials, one per project, without secrets.

    Each entry reports the result of the last Keystone check and the number of
    the caller's live deployments in that project.
    """
    return [_response(db, row) for row in crud_creds.list_for_user(db, current_user.userId)]


@router.post(
    "/me/openstack-credentials",
    response_model=OpenStackCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replaced the credential for the same project"}},
)
def save_my_credential(
    payload: OpenStackCredentialUpsert,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Check against Keystone, then store (201) or replace the one for the same project (200).

    422 ``openstack_credentials_invalid`` with a ``cause`` when Keystone
    does not accept it; nothing is stored then.
    """
    return _save(db, current_user, payload, response)


@router.post(
    "/me/openstack-credentials/from-yaml",
    response_model=OpenStackCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Replaced the credential for the same project"}},
)
def save_my_credential_from_yaml(
    body: OpenStackCredentialFromYaml,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Same as the plain POST, from a pasted `clouds.yaml`.

    ``cloud_name`` picks the entry when the file holds several clouds. Parse
    errors answer 422; otherwise status codes as for the plain POST.
    """
    payload = clouds_yaml_parser.parse(body.clouds_yaml, body.cloud_name)
    return _save(db, current_user, payload, response)


@router.post(
    "/me/openstack-credentials/{credential_id}/test",
    response_model=OpenStackCredentialResponse,
)
def test_my_credential(
    credential_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask Keystone again and record the outcome (e.g. a revoked application credential).

    Always answers 200 with the updated credential; a failure shows up in its
    validation fields (``project_changed`` when the credential now scopes to a
    different project). 404 for a credential that is not the caller's.
    """
    row = openstack_client.owned_credential(db, current_user, credential_id)
    plaintext = crud_creds.decrypted(row)
    payload = OpenStackCredentialUpsert(
        auth_type=row.auth_type,
        auth_url=row.auth_url,
        region_name=row.region_name,
        interface=row.interface,
        identity_api_version=row.identity_api_version,
        project_id=row.project_id,
        project_name=row.project_name,
        user_domain_name=row.user_domain_name,
        project_domain_name=row.project_domain_name,
        identifier=plaintext["identifier"],
        secret=plaintext["secret"],
    )
    try:
        scope = openstack_validator.validate(payload)
        error = None if scope.project_id == row.project_id else "project_changed"
    except openstack_validator.CredentialRejected as e:
        error = e.reason
    return _response(db, crud_creds.stamp_validation(db, row, error))


@router.delete(
    "/me/openstack-credentials/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_my_credential(
    credential_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete one of the caller's credentials (204).

    404 when it is not the caller's; 409 ``openstack_credentials_locked`` with
    ``active_deployments`` while the caller still owns live deployments in the
    credential's project.
    """
    crud_locks.acquire_user_xact_lock(db, current_user.userId)
    row = openstack_client.owned_credential(db, current_user, credential_id)
    active = crud_deployments.count_active_user_deployments(db, current_user.userId, row.project_id)
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"reason": "openstack_credentials_locked", "active_deployments": active},
        )
    openstack_client.invalidate(row.credentialId)
    crud_creds.delete(db, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
