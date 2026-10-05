"""Tests for the Postgres advisory-lock based PackerBuildLock."""

import pytest

from appstore_worker.services import build_lock as build_lock_module
from appstore_worker.services.build_lock import PackerBuildLock

pytestmark = pytest.mark.integration


@pytest.fixture
def no_sleep(mocker):
    return mocker.patch.object(build_lock_module.time, "sleep")


def test_key_includes_project_and_image():
    assert PackerBuildLock("my-proj", "ubuntu-22").key == "lock:packer:my-proj:ubuntu-22"
    assert PackerBuildLock("", "img").key == "lock:packer:unknown:img"


def test_second_holder_waits_until_the_first_releases(db_engine, no_sleep):
    first = PackerBuildLock("p", "img", engine=db_engine)
    second = PackerBuildLock("p", "img", engine=db_engine, poll_interval_s=7)

    assert first.acquire_or_wait() is True
    assert second.acquire_or_wait() is False
    no_sleep.assert_called_once_with(7)

    first.release()
    assert second.acquire_or_wait() is True
    second.release()


def test_different_images_do_not_block_each_other(db_engine, no_sleep):
    a = PackerBuildLock("p", "img-a", engine=db_engine)
    b = PackerBuildLock("p", "img-b", engine=db_engine)
    try:
        assert a.acquire_or_wait() is True
        assert b.acquire_or_wait() is True
    finally:
        a.release()
        b.release()


def test_waiting_past_the_budget_raises(db_engine, no_sleep):
    holder = PackerBuildLock("p", "img", engine=db_engine)
    waiter = PackerBuildLock("p", "img", engine=db_engine, total_wait_s=-1)
    try:
        assert holder.acquire_or_wait() is True
        with pytest.raises(TimeoutError):
            waiter.acquire_or_wait()
    finally:
        holder.release()


def test_a_dead_holder_frees_the_lock(db_engine, no_sleep):
    holder = PackerBuildLock("p", "img", engine=db_engine)
    assert holder.acquire_or_wait() is True
    # The worker process dies: its database session ends.
    holder._conn.invalidate()
    holder._conn = None

    other = PackerBuildLock("p", "img", engine=db_engine)
    assert other.acquire_or_wait() is True
    other.release()


def test_release_without_holding_is_a_no_op(db_engine):
    PackerBuildLock("p", "img", engine=db_engine).release()


def test_context_manager_releases(db_engine, no_sleep):
    with PackerBuildLock("p", "img", engine=db_engine) as lock:
        assert lock.acquire_or_wait() is True
    again = PackerBuildLock("p", "img", engine=db_engine)
    assert again.acquire_or_wait() is True
    again.release()
