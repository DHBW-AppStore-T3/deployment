"""Admin review of app versions, mounted under ``/admin``.

Admins approve, reject or revoke the release tags that app owners submit
(``routers/apps.py``) and can hide an app from the store in an emergency.
Every route requires the admin token (``require_admin``, 403 otherwise).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.crud import app_version_approvals as crud_approvals
from appstore_api.crud import apps as crud_apps
from appstore_api.database import get_db
from appstore_api.models import User
from appstore_api.routers.apps import (
    _serialize_app,
    load_variable_definitions,
    resolve_version_commit,
)
from appstore_api.schemas import (
    AppResponse,
    AppVersionApprovalDecision,
    AppVersionApprovalResponse,
    AppVersionApprovalWithApp,
)
from appstore_api.utils.capabilities import require_admin

router = APIRouter()


# ----------------------------------------------------------------
# PENDING REVIEW QUEUE
# ----------------------------------------------------------------
@router.get(
    "/apps/versions/pending",
    response_model=list[AppVersionApprovalWithApp],
    tags=["Admin"],
)
def list_pending_versions(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all version submissions awaiting admin review, oldest first.

    Each entry carries its app, so the review queue can be rendered without
    further calls. Admins only (403 otherwise).
    """
    return crud_approvals.get_pending_approvals(db)


# ----------------------------------------------------------------
# APPROVE VERSION
# ----------------------------------------------------------------
@router.post(
    "/apps/{app_id}/versions/{version_tag}/approve",
    response_model=AppVersionApprovalResponse,
    tags=["Admin"],
)
def approve_version(
    app_id: UUID,
    version_tag: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Approve a submitted version, making it deployable by all users.

    Admins only (403 otherwise). Works on PENDING and on previously REJECTED
    submissions.

    - 404: the app or the version submission does not exist.
    - 409 ``version_moved``: the tag no longer points to the submitted commit;
      the admin would be approving code that was not what got submitted.
    - 409: the version is already approved.
    - 422: the ``@openstack`` markers in this version's Terraform/Packer
      variable files are invalid (``marker_errors`` lists them). Checked with
      the same helper as ``GET /apps/{id}/variables``, on the submitted commit.
    - 502: the repository cannot be read; nothing is approved unchecked.
    """
    app = _require_app(db, app_id)
    submitted = crud_approvals.get_approval(db, app_id, version_tag)
    commit_sha = resolve_version_commit(app, version_tag)
    if submitted is not None and commit_sha != submitted.commit_sha:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "reason": "version_moved",
                "message": "The tag now points to a different commit than the one submitted; submit it again",
            },
        )

    # Block approval if any variable of the commit carries a marker error.
    # An unreadable repository fails the approval (502): an approval is a
    # statement about code that was checked.
    variables = load_variable_definitions(app, version_tag, commit_sha)
    marker_errors = [
        v.get("markerError") for v in variables if v.get("markerError")
    ]
    if marker_errors:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": (
                    "Version kann nicht approved werden — fehlerhafte "
                    "@openstack-Marker in den Variablen-Dateien"
                ),
                "marker_errors": marker_errors,
            },
        )

    return crud_approvals.approve(db, app_id, version_tag, current_user.userId)


# ----------------------------------------------------------------
# REJECT VERSION
# ----------------------------------------------------------------
@router.post(
    "/apps/{app_id}/versions/{version_tag}/reject",
    response_model=AppVersionApprovalResponse,
    tags=["Admin"],
)
def reject_version(
    app_id: UUID,
    version_tag: str,
    body: AppVersionApprovalDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Reject a PENDING version with a mandatory reason shown to the app owner.

    Admins only (403 otherwise). 404 if the app or submission does not exist,
    409 if the version is not PENDING (use ``/revoke`` for approved ones).
    """
    _require_app(db, app_id)
    return crud_approvals.reject(
        db, app_id, version_tag, current_user.userId, body.rejection_reason
    )


# ----------------------------------------------------------------
# REVOKE APPROVED VERSION
# ----------------------------------------------------------------
@router.post(
    "/apps/{app_id}/versions/{version_tag}/revoke",
    response_model=AppVersionApprovalResponse,
    tags=["Admin"],
)
def revoke_version(
    app_id: UUID,
    version_tag: str,
    body: AppVersionApprovalDecision,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Revoke a previously APPROVED version with a mandatory reason (sets status to REJECTED).

    A public app can no longer be deployed with this version. Admins only (403 otherwise). 404 if the app or submission
    does not exist, 409 if the version is not APPROVED.
    """
    _require_app(db, app_id)
    return crud_approvals.revoke(db, app_id, version_tag, current_user.userId, body.rejection_reason)


# ----------------------------------------------------------------
# EMERGENCY DEACTIVATION
# ----------------------------------------------------------------
@router.put(
    "/apps/{app_id}",
    response_model=AppResponse,
    tags=["Admin"],
)
def deactivate_app(
    app_id: UUID,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Emergency deactivation: set the app to private so it disappears from the store.

    Takes no body. Does not delete the app, its versions or its deployments.
    Marks it ``hidden_by_admin``: the owner can no longer make it public,
    only an admin can (``PUT /apps/{id}`` with ``is_private: false``).
    Admins only (403 otherwise), 404 if the app does not exist (soft-deleted
    apps included).
    """
    _require_app(db, app_id)
    updated = crud_apps.set_hidden_by_admin(db, app_id, True)
    return _serialize_app(updated)


# ----------------------------------------------------------------
# HELPER
# ----------------------------------------------------------------
def _require_app(db: Session, app_id: UUID):
    """Load the app including soft-deleted ones, so admins can still act on them; 404 if absent."""
    app =crud_apps.get_app(db, app_id, include_deleted=True)
    if not app:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="App not found",
        )
    return app
