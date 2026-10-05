"""Postgres advisory lock around the Packer image build.

Why this exists: the build phase in `tasks.py` does a check-then-act pair
(`check_image_exists` → `packer.build`) on the shared OpenStack Glance store.
Two parallel workers triggering a build of the same `(project_id, image_name)`
both observe "not found" and both kick off a build, leaving a duplicate image
behind and burning ~10 minutes of compute. This lock serializes the build for
a given image name within a given OpenStack project so only one worker
actually builds; the other re-checks Glance after waiting and skips straight
to the OpenTofu phase if the image now exists.

A session-level advisory lock on a connection held for the duration of the
build. Postgres releases it when that connection ends, so a worker that
crashes mid-build frees the lock at once — no lease, no heartbeat, nothing
to expire.
"""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from ..utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_POLL_S = 5
_DEFAULT_TOTAL_WAIT_S = 25 * 60


def _engine() -> Engine:
    from ..db import engine  # imported late: tests construct locks without a database

    return engine


class PackerBuildLock:
    """Advisory lock keyed on (project, image_name).

    A polling loop with a release, used like this:

        lock = PackerBuildLock(project_id, image_name)
        try:
            while True:
                held = lock.acquire_or_wait()
                if held:
                    if image_already_exists(): break
                    packer.build(...)
                    break
                if image_already_exists(): break
        finally:
            lock.release()
    """

    def __init__(
        self,
        project_id: str,
        image_name: str,
        *,
        poll_interval_s: int = _DEFAULT_POLL_S,
        total_wait_s: int = _DEFAULT_TOTAL_WAIT_S,
        engine: Engine | None = None,
    ):
        self.key = f"lock:packer:{project_id or 'unknown'}:{image_name}"
        self.poll_interval_s = poll_interval_s
        self.deadline = time.monotonic() + total_wait_s
        self._engine = engine
        self._conn: Connection | None = None

    def acquire_or_wait(self) -> bool:
        """Try to acquire. Returns True if held, False if we slept and the
        caller should re-check Glance and call again. Raises TimeoutError
        if the total wait budget is exhausted."""
        conn = (self._engine or _engine()).connect()
        try:
            held = bool(
                conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": self.key}
                ).scalar()
            )
            # The lock belongs to the session, not to a transaction; end the
            # implicit transaction so the pooled connection is not left idle
            # in one for the length of a build.
            conn.commit()
        except Exception:
            conn.close()
            raise
        if held:
            self._conn = conn
            logger.info("Acquired Packer build lock", lock_key=self.key)
            return True
        conn.close()
        if time.monotonic() > self.deadline:
            raise TimeoutError(
                f"Timed out waiting for Packer build lock {self.key} (another worker is still building this image)"
            )
        logger.info("Waiting for in-progress Packer build", lock_key=self.key, poll_interval_s=self.poll_interval_s)
        time.sleep(self.poll_interval_s)
        return False

    def release(self) -> None:
        """Release the lock if held (idempotent); ends the DB session if unlocking fails."""
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            conn.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": self.key})
            conn.commit()
        except Exception as e:
            # close() alone would hand the connection back to the pool with
            # the lock still held; invalidate() ends the database session,
            # and with it the lock.
            logger.warning(f"Failed to release Packer lock {self.key}: {e}")
            conn.invalidate()
        finally:
            conn.close()

    def __enter__(self) -> PackerBuildLock:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
