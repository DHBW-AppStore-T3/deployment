"""Test-suite-wide fixtures and DB-isolation primitives.

# DB-Isolation: schema once per session, TRUNCATE per test

History — bis Juni 2026 baute jeder Test sein eigenes Schema auf und
riss es danach wieder ab (``Base.metadata.create_all`` /
``drop_all`` als ``autouse=True``-Fixture). Bei einer Suite von ~420
Tests sind das ~840 DDL-Wellen pro Lauf, jede mit FK-Lock-Kaskade
über ein Dutzend Tabellen. Das hat in der Praxis zwei Probleme
erzeugt:

1. **Hänger** — eine offene Test-Session, die noch eine Row in
   ``users`` hielt, blockierte das ``DROP TABLE users`` des nächsten
   Tests; psycopg2 wartete dann ewig im ``recv()`` und der Run blieb
   einfach stehen. Symptom: pytest-Prozess in ``do_sys_poll`` /
   ``futex_wait_queue`` ohne CPU-Last, kein Fortschritt mehr.
2. **Speicher** — Postgres reservierte für jede DDL-Welle frischen
   Backend-Speicher; bei 800+ Wellen sammelten sich genug Verbindungen
   und Catalog-Caches, dass der Container am Ende OOM-gekillt wurde
   (``Error 137`` SIGKILL auf dem nächstbesten Test, hier
   ``test_admin_can_deactivate_app_hides_from_students``, der vier
   Fixtures gleichzeitig zieht und so der nächste anstehende Lock-
   Wait war).

Lösung: Schema einmal pro Test-Session anlegen, zwischen den Tests
nur per ``TRUNCATE ... RESTART IDENTITY CASCADE`` reinigen. Postgres
macht das in einer einzigen Cursor-Operation, kein DDL-Lock, ~50× so
schnell wie der alte Pfad. Identische Test-Semantik (jeder Test
startet mit leeren Tabellen), aber ohne Lock-Stau und ohne
Speicherleck.

# TEST_DATABASE_URL-Gate

Wenn ``TEST_DATABASE_URL`` nicht gesetzt ist, fallen wir auf
``settings.DATABASE_URL`` zurück und warnen einmalig — local-dev mit
einer einzigen Postgres-Instanz darf das (der Entwickler akzeptiert,
dass der Dev-Datenbestand truncate-d wird). CI MUSS ``TEST_DATABASE_URL``
auf den isolierten ``postgres-test``-Service zeigen lassen, sonst
killt die Suite die Dev-Daten.
"""

import os
import uuid
import warnings

# IMPORTANT: this env-var must be set BEFORE ``appstore_api.main`` is imported.
# ``lifespan`` reads it on every ``TestClient(app)`` enter to decide
# whether to start the task finalizer loop; every test client would
# otherwise start another one against the test database. See
# ``appstore_api/main.py``.
os.environ.setdefault("DISABLE_BACKGROUND_TASKS", "1")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from appstore_api.auth import get_current_user
from appstore_api.config import settings
from appstore_api.database import Base, get_db
from appstore_api.main import app
from appstore_api.models import (  # noqa: F401  (importiert für seitliche Effekte / Metadata-Registrierung)
    App,
    User,
)
from tests.roles import COURSE, Role, make_user

# The commit every tag resolves to in tests (see ``_tags_resolve_offline``).
TEST_SHA = "0123456789abcdef0123456789abcdef01234567"
TEST_COURSE = COURSE

# ----------------------------------------------------------------
# Engine — einmal pro Test-Prozess.
#
# Connection-Pool großzügig dimensioniert, weil mehrere Fixtures
# gleichzeitig Sessions ziehen können (z.B. ``admin_client``,
# ``student_client``, ``db``, ``mock_user``, ``mock_admin`` in einem
# Test) und der dahinterliegende ``TestClient`` zusätzlich
# Dependency-overrides für ``get_db`` öffnet. Bei 7 max-Connections
# (alter Wert) trat in der Praxis Pool-Exhaustion auf, sobald die
# Background-Task-Threads (jetzt deaktiviert) noch dazukamen.
# 20 reicht mit Reserve; sequentielle Suite, Postgres-Container hat
# ``max_connections=100`` per Default.
# ----------------------------------------------------------------
_TEST_DB_URL = os.getenv("TEST_DATABASE_URL", settings.DATABASE_URL)
if _TEST_DB_URL == settings.DATABASE_URL:
    warnings.warn(
        "TEST_DATABASE_URL not set — tests will run against settings.DATABASE_URL "
        "and will TRUNCATE on tear-down. Set TEST_DATABASE_URL to a dedicated test DB.",
        UserWarning,
        stacklevel=2,
    )

engine = create_engine(
    _TEST_DB_URL,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    pool_recycle=300,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ----------------------------------------------------------------
# Schema-Lifecycle — einmal pro pytest-Session.
# ----------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _setup_schema():
    """Create the full schema once at session start, drop at the end.

    The drop is a safety net for shared Postgres instances; on the
    isolated ``postgres-test`` service it's effectively a no-op
    because the container will be torn down anyway. Using
    ``scope='session'`` means the fixture body runs exactly twice
    (setup + teardown), not 2 × 420 = 840 times.
    """
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _truncate_tables(_setup_schema):
    """Reset DB state to empty between tests.

    Runs AFTER each test (yield first) so a failing test still leaves
    behind useful data for ``pdb`` / log inspection within the test
    itself. The ``TRUNCATE ... RESTART IDENTITY CASCADE`` form is
    Postgres-specific but the whole project is Postgres-only, so this
    is fine.

    Tables are listed in ``sorted_tables`` order (parents first) and
    we pass them in reverse so CASCADE handles the FK chain top-down
    without ``DETAIL`` warnings.

    The fixture depends on ``_setup_schema`` so pytest enforces
    ordering: schema MUST exist before the first truncate runs.
    """
    yield
    table_names = [t.name for t in reversed(Base.metadata.sorted_tables)]
    if not table_names:
        return
    quoted = ", ".join(f'"{n}"' for n in table_names)
    with engine.connect() as conn:
        conn.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
        conn.commit()


# ----------------------------------------------------------------
# DB-Session-Fixture — frische Session pro Test, immer geschlossen.
# ----------------------------------------------------------------
@pytest.fixture(autouse=True)
def _tags_resolve_offline(monkeypatch):
    """Every tag of every app points to ``TEST_SHA``, without asking a Git host.

    Approvals and deployments pin the commit of a tag (``git ls-remote``);
    tests that care about a moved tag patch ``resolve_tag`` themselves.
    """
    from appstore_api.services.git_service import git_service

    monkeypatch.setattr(git_service, "resolve_tag", lambda _url, _tag: TEST_SHA)


@pytest.fixture
def empty_app_checkout(tmp_path, monkeypatch):
    """The variable scan reads an empty checkout instead of cloning: the app
    declares no variables. For tests whose apps point at no real repository
    but go through submit, approve or a deploy with inputs."""
    from appstore_api.services.git_service import git_service

    checkout = tmp_path / "checkout"
    checkout.mkdir()
    monkeypatch.setattr(git_service, "clone_release_vars", lambda _url, _tag, _sha: str(checkout))
    monkeypatch.setattr(git_service, "cleanup_repository", lambda _path: None)
    return checkout


@pytest.fixture(autouse=True)
def _fresh_variable_cache():
    """The variable scan is cached per (repository, commit); tests reuse both."""
    from appstore_api.routers.apps import clear_variable_cache

    clear_variable_cache()
    yield
    clear_variable_cache()


def approve_version(db, app, tag="v1.0", commit_sha=TEST_SHA):
    """Mark ``tag`` of ``app`` approved, so non-owners may deploy it."""
    from appstore_api.models import AppVersionApproval, AppVersionApprovalStatus

    db.add(
        AppVersionApproval(
            appId=app.appId, version_tag=tag, commit_sha=commit_sha, status=AppVersionApprovalStatus.APPROVED
        )
    )
    db.commit()


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        # Defensiv: alle laufenden Transaktionen rollen wir zurück,
        # bevor wir schließen — sonst hält ein open ``begin()`` eine
        # Connection im Pool, die der nächste ``_truncate_tables``
        # auf der gleichen Connection als Lock-Halter sieht.
        try:
            session.rollback()
        finally:
            session.close()


# ----------------------------------------------------------------
# Mock-User-Fixtures
# ----------------------------------------------------------------
@pytest.fixture
def mock_user(db):
    user = make_user(
        userId=uuid.uuid4(),
        email="test@dhbw.de",
        username="testuser",
        firstName="Test",
        lastName="User",
        role=Role.DOZENT,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mock_admin(db):
    user = make_user(
        userId=uuid.uuid4(),
        email="admin@dhbw.de",
        username="adminuser",
        firstName="Admin",
        lastName="User",
        role=Role.ADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def mock_student(db):
    user = make_user(
        userId=uuid.uuid4(),
        email="student@dhbw.de",
        username="studentuser",
        firstName="Student",
        lastName="User",
        role=Role.STUDENT,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ----------------------------------------------------------------
# FastAPI-Test-Clients
# ----------------------------------------------------------------
def _make_client(user):
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            try:
                session.rollback()
            finally:
                session.close()

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app)


@pytest.fixture
def client(mock_user):
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            try:
                session.rollback()
            finally:
                session.close()

    def override_get_current_user():
        return mock_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.fixture
def admin_client(mock_admin):
    c = _make_client(mock_admin)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def student_client(mock_student):
    c = _make_client(mock_student)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture
def unauth_client():
    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            try:
                session.rollback()
            finally:
                session.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ----------------------------------------------------------------
# SHARED DB HELPERS
# ----------------------------------------------------------------
def create_app_in_db(db, user, *, name="Test App", git_link="https://github.com/example/repo", is_private=False):
    db_app = App(
        appId=uuid.uuid4(),
        name=name,
        git_link=git_link,
        is_private=is_private,
        userId=user.userId,
    )
    db.add(db_app)
    db.commit()
    db.refresh(db_app)
    return db_app


def queued_task(db, deployment_id):
    """The newest task of ``deployment_id`` and its decrypted job payload.

    Queueing a job is committing a PENDING task row; this is what a worker
    would claim.
    """
    from appstore_api.models import Task
    from appstore_api.utils.crypto import cipher
    from appstore_shared.jobs import open_payload

    db.expire_all()
    task = (
        db.query(Task)
        .filter(Task.deploymentId == deployment_id)
        .order_by(Task.created_at.desc())
        .first()
    )
    if task is None:
        return None, None
    return task, (open_payload(cipher, task.payload) if task.payload else None)


@pytest.fixture
def jobs(db):
    """Tasks queued through the API during the test.

    Only the API attaches a job payload; task rows a test inserts to set the
    scene have none, so they do not count.
    """
    from appstore_api.models import Task

    class _Jobs:
        def queued(self):
            db.expire_all()
            return (
                db.query(Task)
                .filter(Task.payload.is_not(None))
                .order_by(Task.created_at)
                .all()
            )

    return _Jobs()


class _CourseProvider:
    """A role provider whose course roster a test sets; groups are described plainly."""

    def __init__(self):
        self.students: set[str] = set()
        self.down = False

    def get_user_tokens(self, email):
        return [f"user:{email}"]

    def get_group(self, group_token):
        from appstore_api.services.role_provider import Group, RoleProviderError

        if self.down:
            raise RoleProviderError("down")
        return Group(group_token, group_token.removeprefix("group:").upper(), "Kurs")

    def get_member_emails(self, group_token, relation):
        from appstore_api.services.role_provider import RoleProviderError

        if self.down:
            raise RoleProviderError("down")
        return sorted(self.students) if (group_token, relation) == (TEST_COURSE, "studierende") else []


@pytest.fixture
def course_students(monkeypatch):
    """The ``studierende`` of ``TEST_COURSE``: a set the test fills.

    ``course_students.down = True`` makes the role provider fail.
    """
    from appstore_api.services import courses

    provider = _CourseProvider()
    monkeypatch.setattr(courses, "get_role_provider", lambda: provider)
    provider.students.add("student@dhbw.de")  # mock_student
    return provider


TEST_PROJECT = "project-1"


def add_credential(
    db, user, project_id=TEST_PROJECT, *, project_name="Projekt 1", identifier="app-cred-id", credential_id=None
):
    """A stored application credential of ``user`` for ``project_id``."""
    from appstore_api.models import OpenStackAuthType, UserOpenStackCredential
    from appstore_api.utils import crypto

    row = UserOpenStackCredential(
        credentialId=credential_id or uuid.uuid4(),
        userId=user.userId,
        auth_type=OpenStackAuthType.APPLICATION_CREDENTIAL,
        auth_url="https://keystone.example/v3",
        region_name="RegionOne",
        project_id=project_id,
        project_name=project_name,
        encrypted_identifier=crypto.encrypt(identifier),
        encrypted_secret=crypto.encrypt("app-cred-secret"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
