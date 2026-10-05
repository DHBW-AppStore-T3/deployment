"""Whether a Packer image is still needed after a destroy (plan E1).

Images are named after app and commit (``_build_image_names``) and live in
the project's Glance, so every deployment of the same app at the same commit
in the same project shares them. A destroy deletes them only when no other
such deployment is left: not soft-deleted and not destroyed (a failed
destroy still has servers that were booted from the image).

Asked under the image's ``PackerBuildLock``: a deploy that reuses the image
holds the same lock while it checks Glance, and its deployment row exists
before its job runs, so the two cannot miss each other.
"""

from __future__ import annotations

import uuid

from sqlalchemy import exists, select

from appstore_shared.models import Deployment, Task, TaskStatus, TaskType


def others_share_images(deployment_id: str) -> bool:
    """True if another live deployment uses this deployment's images (same app, commit, project).

    Also True when the deployment itself is unknown, so the image is kept.
    """
    from ..db import SessionLocal  # imported late: tests run without a database

    with SessionLocal() as session:
        me = session.get(Deployment, uuid.UUID(deployment_id))
        if me is None:
            # Unknown deployment: keep the image rather than guess.
            return True
        destroyed = exists().where(
            Task.deploymentId == Deployment.deploymentId,
            Task.type == TaskType.DESTROY,
            Task.status == TaskStatus.SUCCESS,
        )
        other = session.execute(
            select(Deployment.deploymentId)
            .where(
                Deployment.deploymentId != me.deploymentId,
                Deployment.appId == me.appId,
                Deployment.commit_sha == me.commit_sha,
                Deployment.os_project_id == me.os_project_id,
                Deployment.deleted_at.is_(None),
                ~destroyed,
            )
            .limit(1)
        ).first()
        return other is not None
