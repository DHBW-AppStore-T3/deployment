"""Pytest configuration and fixtures."""

import shutil
import tempfile
import uuid
from pathlib import Path

import pytest


# ----------------------------------------------------------------
# Auto-marker policy
# ----------------------------------------------------------------
# CI rennt zwei getrennte Lanes: ``pytest -m unit`` und
# ``pytest -m integration``. Tests, die *gar keinen* Marker tragen,
# fallen aus **beiden** Selektoren raus — d.h. sie würden lautlos
# nicht in CI ausgeführt, obwohl sie lokal grün sind. Genau das ist
# uns hier passiert: 12 von 23 Tests waren unmarked und wurden nie
# durch die Pipeline laufen.
#
# Diese Hook setzt für jeden Test ohne ``integration``/``slow``-
# Marker implizit ``unit``. Damit gilt: **default ist unit**, und
# nur Tests, die echte externe Abhängigkeiten brauchen (DB, Broker,
# Netz), müssen explizit als ``integration`` markiert werden.
def pytest_collection_modifyitems(config, items):
    for item in items:
        markers = {m.name for m in item.iter_markers()}
        # ``integration`` / ``slow`` haben Vorrang — wer explizit
        # markiert, will nicht in die unit-Lane gezogen werden.
        if "integration" not in markers and "slow" not in markers and "unit" not in markers:
            item.add_marker(pytest.mark.unit)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    if temp_path.exists():
        shutil.rmtree(temp_path)


@pytest.fixture
def mock_git_url():
    """Mock Git URL for testing."""
    return "https://github.com/test-org/test-repo.git"


@pytest.fixture
def mock_tag():
    """Mock Git tag for testing."""
    return "v1.0.0"


# ----------------------------------------------------------------
# Database (queue, runner and lock tests)
# ----------------------------------------------------------------
# The worker's own tables are the API's: the schema comes from the shared
# models. Like the backend suite, these tests need a database of their own
# (`make test-db`); they truncate everything between tests.
@pytest.fixture(scope="session")
def db_engine():
    from appstore_shared.models import Base
    from appstore_worker.db import engine

    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture
def session_factory(db_engine):
    from sqlalchemy import text

    from appstore_shared.models import Base
    from appstore_worker.db import SessionLocal

    yield SessionLocal
    names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with db_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def make_task(session_factory):
    """Queue a task the way the API does; returns its id."""
    from appstore_shared.jobs import seal_payload
    from appstore_shared.models import App, Deployment, Task, TaskStatus, TaskType, User
    from appstore_worker.utils.crypto import cipher

    def _make(task_type=TaskType.DEPLOY, payload=None, status=TaskStatus.PENDING, sealed=None):
        with session_factory() as s:
            user = User(email=f"{uuid.uuid4().hex}@dhbw.de", username="u")
            s.add(user)
            s.flush()
            app = App(name="a", userId=user.userId, git_link="https://example.org/a/b")
            s.add(app)
            s.flush()
            dep = Deployment(name="d", userId=user.userId, appId=app.appId, commit_sha="c" * 40, course="group:wwi23seb", os_project_id="project-1")
            s.add(dep)
            s.flush()
            payload = payload or {
                "app_id": str(app.appId),
                "app_git_link": app.git_link,
                "release": "v1",
                "commit_sha": "c" * 40,
                "user_vars": {"terraform": {"x": 1}},
                "teams": {"T1": [{"email": "s@dhbw.de"}]},
                "openstack_envelope": {"project_id": "p1"},
            }
            task = Task(
                deploymentId=dep.deploymentId,
                type=task_type,
                status=status,
                payload=sealed if sealed is not None else seal_payload(cipher, payload),
            )
            s.add(task)
            s.commit()
            return task.taskId

    return _make
