"""Packer images are deleted on destroy once nothing in the project uses them (plan E1)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from appstore_worker import tasks
from appstore_worker.services import image_usage


class _Lock:
    taken: list[str] = []

    def __init__(self, project_id, image_name):
        self.key = f"{project_id}:{image_name}"

    def acquire_or_wait(self):
        _Lock.taken.append(self.key)
        return True

    def release(self):
        pass


@pytest.fixture
def cleanup(monkeypatch):
    _Lock.taken = []
    monkeypatch.setattr(tasks, "PackerBuildLock", _Lock)
    openstack = MagicMock()
    openstack.check_image_exists.return_value = (True, "img-1")
    openstack.delete_image.return_value = (True, None)
    logger = MagicMock()

    def run(shared: bool, delete_result=(True, None)):
        openstack.delete_image.return_value = delete_result
        monkeypatch.setattr(image_usage, "others_share_images", lambda _d: shared)
        tasks._delete_unused_images(
            "dep-1", {"web": "app-web-abc", "db": "app-db-abc"},
            project_id="p1", openstack_service=openstack, task_logger=logger,
        )
        return openstack, logger

    return run


def test_unused_images_are_deleted_under_the_build_lock(cleanup):
    openstack, _ = cleanup(shared=False)

    assert _Lock.taken == ["p1:app-web-abc", "p1:app-db-abc"]
    assert openstack.delete_image.call_count == 2


def test_shared_images_are_kept(cleanup):
    openstack, _ = cleanup(shared=True)

    openstack.check_image_exists.assert_not_called()
    openstack.delete_image.assert_not_called()


def test_a_failing_delete_is_a_warning_not_a_failed_destroy(cleanup):
    openstack, logger = cleanup(shared=False, delete_result=(False, "403 forbidden"))

    assert openstack.delete_image.call_count == 2
    assert logger.warning.call_count == 2


# ----------------------------------------------------------------
# who shares the image (needs the test database, like test_job_queue)
# ----------------------------------------------------------------
def _deployment(s, app, *, commit="c" * 40, project="p1", deleted=False):
    from appstore_shared.models import Deployment

    dep = Deployment(
        name="d", userId=app.userId, appId=app.appId, commit_sha=commit, course="group:x", os_project_id=project
    )
    if deleted:
        from datetime import datetime

        dep.deleted_at = datetime(2026, 1, 1)
    s.add(dep)
    s.flush()
    return dep


@pytest.mark.integration
def test_who_shares_an_image(session_factory):
    from appstore_shared.models import App, Task, TaskStatus, TaskType, User

    with session_factory() as s:
        user = User(email=f"{uuid.uuid4().hex}@dhbw.de", username="u")
        s.add(user)
        s.flush()
        app = App(name="a", userId=user.userId, git_link="https://example.org/a/b")
        s.add(app)
        s.flush()
        me = _deployment(s, app)
        _deployment(s, app, commit="d" * 40)  # other commit: other image
        _deployment(s, app, project="p2")  # other project: other Glance
        _deployment(s, app, deleted=True)
        destroyed = _deployment(s, app)
        s.add(Task(deploymentId=destroyed.deploymentId, type=TaskType.DESTROY, status=TaskStatus.SUCCESS))
        s.commit()
        me_id = str(me.deploymentId)

    assert image_usage.others_share_images(me_id) is False

    with session_factory() as s:
        app = s.get(App, app.appId)
        failed = _deployment(s, app)
        s.add(Task(deploymentId=failed.deploymentId, type=TaskType.DESTROY, status=TaskStatus.FAILED))
        s.commit()

    # A failed destroy still has servers booted from the image.
    assert image_usage.others_share_images(me_id) is True
