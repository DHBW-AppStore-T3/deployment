"""Admin review of app versions (plan E6).

A review covers one commit: ``commit_sha`` is what the tag pointed to at
submission. When the tag is moved later, the old review no longer applies —
the version is unapproved and can be submitted again.
"""

import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from appstore_api.models import App, AppVersionApproval, AppVersionApprovalStatus
from appstore_api.utils.time import utcnow


def submit_version(
    db: Session,
    app_id: UUID,
    version_tag: str,
    commit_sha: str,
    diff_url: str | None = None,
    notes: str | None = None,
    runtime: str = "openstack-vm",
    spec_sha256: str | None = None,
    image_digests: list[str] | None = None,
) -> AppVersionApproval:
    """Submit ``version_tag`` at ``commit_sha`` for admin review.

    ``runtime``, ``spec_sha256`` and ``image_digests`` record what the review
    covers besides the commit (Kubernetes apps: the appstore.yaml and its images).

    Raises 409 if this commit is already pending or approved. A rejected
    version, or one whose review was for a commit the tag no longer points
    to, can be submitted again: the old entry is replaced.
    """
    existing = (
        db.query(AppVersionApproval)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.version_tag == version_tag,
        )
        .first()
    )

    if existing and existing.commit_sha == commit_sha:
        if existing.status == AppVersionApprovalStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Version is already pending review",
            )
        if existing.status == AppVersionApprovalStatus.APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Version is already approved",
            )
    if existing:
        # Rejected, or reviewed for another commit: start over.
        db.delete(existing)
        db.flush()

    approval = AppVersionApproval(
        appId=app_id,
        version_tag=version_tag,
        commit_sha=commit_sha,
        runtime=runtime,
        spec_sha256=spec_sha256,
        image_digests=json.dumps(image_digests) if image_digests is not None else None,
        diff_url=diff_url,
        notes=notes,
        status=AppVersionApprovalStatus.PENDING,
        created_at=utcnow(),
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def get_pending_approvals(db: Session) -> list[AppVersionApproval]:
    """Return all PENDING version approvals for public apps, oldest first."""
    return (
        db.query(AppVersionApproval)
        .join(App, App.appId == AppVersionApproval.appId)
        .filter(
            AppVersionApproval.status == AppVersionApprovalStatus.PENDING,
            App.is_private.is_(False),
        )
        .order_by(AppVersionApproval.created_at.asc())
        .all()
    )


def get_approvals_for_app(db: Session, app_id: UUID) -> list[AppVersionApproval]:
    """Return all review entries of an app, whatever their status, newest first."""
    return (
        db.query(AppVersionApproval)
        .filter(AppVersionApproval.appId == app_id)
        .order_by(AppVersionApproval.created_at.desc())
        .all()
    )


def has_approved_version(db: Session, app_id: UUID, version_tag: str, commit_sha: str) -> bool:
    """Whether ``version_tag`` is approved for exactly ``commit_sha``."""
    return (
        db.query(AppVersionApproval.approvalId)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.version_tag == version_tag,
            AppVersionApproval.commit_sha == commit_sha,
            AppVersionApproval.status == AppVersionApprovalStatus.APPROVED,
        )
        .first()
    ) is not None


def approved_commits(db: Session, app_id: UUID) -> dict[str, str]:
    """Approved versions of the app: tag -> the commit the approval covers."""
    rows = (
        db.query(AppVersionApproval.version_tag, AppVersionApproval.commit_sha)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.status == AppVersionApprovalStatus.APPROVED,
        )
        .all()
    )
    return {row.version_tag: row.commit_sha for row in rows}


def has_any_approved_version(db: Session, app_id: UUID) -> bool:
    """Return True if the app has at least one approved version."""
    return (
        db.query(AppVersionApproval.approvalId)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.status == AppVersionApprovalStatus.APPROVED,
        )
        .first()
    ) is not None


def withdraw(db: Session, app_id: UUID, version_tag: str) -> None:
    """Delete a PENDING approval entry (owner withdraws the submission) and commit.

    Raises 404 if there is no entry for the tag, 409 if it is not PENDING.
    """
    approval = _get_approval_or_404(db, app_id, version_tag)

    if approval.status != AppVersionApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Only pending submissions can be withdrawn (current status: '{approval.status.value}')",
        )

    db.delete(approval)
    db.commit()


def get_approval(db: Session, app_id: UUID, version_tag: str) -> AppVersionApproval | None:
    """The review entry of ``version_tag`` (any status), or None."""
    return (
        db.query(AppVersionApproval)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.version_tag == version_tag,
        )
        .first()
    )


def _get_approval_or_404(
    db: Session, app_id: UUID, version_tag: str
) -> AppVersionApproval:
    approval = (
        db.query(AppVersionApproval)
        .filter(
            AppVersionApproval.appId == app_id,
            AppVersionApproval.version_tag == version_tag,
        )
        .first()
    )
    if not approval:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version approval entry not found",
        )
    return approval


def approve(
    db: Session,
    app_id: UUID,
    version_tag: str,
    admin_id: UUID,
) -> AppVersionApproval:
    """Approve a PENDING or REJECTED version (at its stored ``commit_sha``) and commit.

    Raises 404 without an entry, 409 if it is already approved.
    """
    approval = _get_approval_or_404(db, app_id, version_tag)

    if approval.status == AppVersionApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Version is already approved",
        )

    approval.status = AppVersionApprovalStatus.APPROVED
    approval.reviewed_by = admin_id
    approval.reviewed_at = utcnow()
    approval.rejection_reason = None
    db.commit()
    db.refresh(approval)
    return approval


def reject(
    db: Session,
    app_id: UUID,
    version_tag: str,
    admin_id: UUID,
    rejection_reason: str,
) -> AppVersionApproval:
    """Reject a PENDING version with a mandatory reason and commit.

    Raises 404 without an entry, 409 if it is not PENDING.
    """
    approval = _get_approval_or_404(db, app_id, version_tag)

    if approval.status != AppVersionApprovalStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reject a version with status '{approval.status.value}'",
        )

    approval.status = AppVersionApprovalStatus.REJECTED
    approval.reviewed_by = admin_id
    approval.reviewed_at = utcnow()
    approval.rejection_reason = rejection_reason
    db.commit()
    db.refresh(approval)
    return approval


def revoke(
    db: Session,
    app_id: UUID,
    version_tag: str,
    admin_id: UUID,
    rejection_reason: str,
) -> AppVersionApproval:
    """Revoke a previously APPROVED version (sets status back to REJECTED) and commit.

    Existing deployments of the version are not touched. Raises 404 without
    an entry, 409 if it is not APPROVED.
    """
    approval = _get_approval_or_404(db, app_id, version_tag)

    if approval.status != AppVersionApprovalStatus.APPROVED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot revoke a version with status '{approval.status.value}'",
        )

    approval.status = AppVersionApprovalStatus.REJECTED
    approval.reviewed_by = admin_id
    approval.reviewed_at = utcnow()
    approval.rejection_reason = rejection_reason
    db.commit()
    db.refresh(approval)
    return approval
