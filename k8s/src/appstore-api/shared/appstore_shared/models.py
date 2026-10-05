"""Database models, shared by the API and the worker.

Both write to the same tables — the API creates deployments and queues tasks,
the worker claims tasks and records their progress — so both must agree on the
schema. It lives here once. Migrations are generated from these classes (in
``backend/alembic``); indexes and constraints are declared here too, never only
in a migration, or the next autogenerate drops them again.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """Current UTC time as a naive ``datetime``.

    Every ``DateTime`` column here is naive (UTC by convention); mixing aware
    and naive values would raise ``TypeError`` on comparison.
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base of all AppStore tables (alembic's target metadata)."""


# ----------------------------------------------------------------
# ENUMS
# ----------------------------------------------------------------
class AppVersionApprovalStatus(str, enum.Enum):
    """Review state of an app version; a public app deploys only APPROVED versions (plan E6)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskType(str, enum.Enum):
    """What a task does; each type except UPDATE has a job in ``appstore_worker.runner.JOBS``."""

    DEPLOY = "deploy"
    UPDATE = "update"
    DESTROY = "destroy"
    PAUSE = "pause"
    RESUME = "resume"
    # Single-resource redeploy of ONE Compute-Instance via
    # ``terraform apply -replace=<addr> -target=<addr>``, without
    # touching the other team VMs of the same deployment.
    REDEPLOY = "redeploy"


class TaskStatus(str, enum.Enum):
    """Queue state of a task: PENDING -> RUNNING -> SUCCESS | FAILED; CANCELLED is also terminal."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OpenStackAuthType(str, enum.Enum):
    """How a stored credential authenticates; values are Keystone's ``auth_type`` names."""

    APPLICATION_CREDENTIAL = "v3applicationcredential"
    PASSWORD = "password"


def _uuid_pk() -> Mapped[uuid.UUID]:
    """A UUID primary key generated on the Python side."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# ----------------------------------------------------------------
# USER MODEL
# ----------------------------------------------------------------
class User(Base):
    """A person the AppStore has seen, keyed by the e-mail from their token.

    Rows are created on first sign-in (see ``appstore_api.auth``); the
    identity provider stays the source of truth. Roles are not stored here:
    they come from the caller's tokens on every request.
    """

    __tablename__ = "users"

    userId: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    username: Mapped[str] = mapped_column(String)
    firstName: Mapped[str | None] = mapped_column(String)
    lastName: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Not persisted. Set per request by ``auth.get_current_user`` from the
    # caller's tokens; a row loaded any other way (e.g. a team member) carries
    # no rights, which is the safe default. Plain attributes without
    # annotations: SQLAlchemy would try to map an annotated one as a column.
    tokens = frozenset[str]()
    is_admin = False
    is_dozent = False

    apps: Mapped[list[App]] = relationship(back_populates="user")
    deployments: Mapped[list[Deployment]] = relationship(back_populates="user")
    user_to_deployments: Mapped[list[UserToDeployment]] = relationship(back_populates="user")
    user_to_teams: Mapped[list[UserToTeam]] = relationship(back_populates="user")
    openstack_credentials: Mapped[list[UserOpenStackCredential]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ----------------------------------------------------------------
# APP MODEL
# ----------------------------------------------------------------
class App(Base):
    """An app: a Git repository with Terraform (and optionally Packer) code.

    Owned by the user who registered it. Deployable versions are its Git
    tags, reviewed through ``AppVersionApproval`` rows. A private app is
    visible to its owner and admins only and deploys any tag; a public one
    is visible to everyone once a version is approved.
    """

    __tablename__ = "apps"
    # Nearly every query filters out soft-deleted apps.
    __table_args__ = (
        Index("ix_apps_live", "appId", postgresql_where=text("deleted_at IS NULL")),
    )

    appId: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(String)
    image: Mapped[bytes | None] = mapped_column(LargeBinary)  # raw bytes of the uploaded logo
    # e.g. "image/png" — needed to build a data-URL on read
    image_mime: Mapped[str | None] = mapped_column(String(64))
    git_link: Mapped[str | None] = mapped_column(String)
    is_private: Mapped[bool] = mapped_column(default=False)
    # Set by an admin's emergency deactivation: the app stays private until
    # an admin publishes it again; the owner cannot undo it.
    hidden_by_admin: Mapped[bool] = mapped_column(default=False)
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.userId"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Soft-delete marker. When set, the app is hidden from default
    # queries but the row stays so existing deployments keep their FK
    # valid. Soft-delete is refused while the app has live deployments.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="apps")
    deployments: Mapped[list[Deployment]] = relationship(back_populates="app")
    version_approvals: Mapped[list[AppVersionApproval]] = relationship(
        back_populates="app",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ----------------------------------------------------------------
# DEPLOYMENT MODEL
# ----------------------------------------------------------------
class Deployment(Base):
    """One run of an app version for a course, with its teams.

    Created by a lecturer (``userId``, the owner) in their OpenStack project.
    Its ``tasks`` are the jobs run on it (deploy, destroy, ...); its OpenTofu
    state is the ``TerraformState`` row with the same id. ``userInputVar``
    holds the variables entered in the deploy form as JSON.
    """

    __tablename__ = "deployments"
    # Nearly every query filters out soft-deleted deployments.
    __table_args__ = (
        Index("ix_deployments_live", "deploymentId", postgresql_where=text("deleted_at IS NULL")),
    )

    deploymentId: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String)
    releaseTag: Mapped[str | None] = mapped_column(String)
    # The commit ``releaseTag`` pointed to at creation. Every job of the
    # deployment checks out exactly this commit, so a moved tag changes
    # nothing about what runs (plan AP2).
    commit_sha: Mapped[str] = mapped_column(String(40))
    # The course this deployment is for, as its group token
    # (``group:<id>``). Its ``#studierende`` are who may be put into the
    # teams; the owner had ``#dozent`` in it when creating (plan AP4).
    course: Mapped[str] = mapped_column(String)
    # The OpenStack project the resources live in, taken from the owner's
    # credential at creation. Everyone with a credential for this project
    # may see and run the deployment, each with their own credential (E2).
    os_project_id: Mapped[str] = mapped_column(String, index=True)
    userInputVar: Mapped[str | None] = mapped_column(Text)  # JSON
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.userId"), index=True
    )
    appId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.appId"), index=True
    )
    # Soft-delete marker. Set to hide the deployment from default
    # queries while keeping the row for audit/restore. DELETE is only
    # allowed in terminal states, so OpenStack resources are already
    # gone by the time this is set.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    user: Mapped[User] = relationship(back_populates="deployments")
    app: Mapped[App] = relationship(back_populates="deployments")
    user_to_deployments: Mapped[list[UserToDeployment]] = relationship(
        back_populates="deployment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    teams: Mapped[list[Team]] = relationship(
        back_populates="deployment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tasks: Mapped[list[Task]] = relationship(
        back_populates="deployment",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ----------------------------------------------------------------
# TASK MODEL
# ----------------------------------------------------------------
class Task(Base):
    """One job run on a deployment, and at the same time its queue entry (plan D4).

    The API inserts it PENDING with a sealed payload; a worker claims it,
    appends ``TaskEvent`` rows and records ``logs``/``outputs`` and the final
    status; the API then finalizes it (``finalized_at``).
    """

    __tablename__ = "tasks"
    # At most one pending or running task per deployment. This is the
    # backstop for the advisory lock in ``crud.locks``: two concurrent
    # lifecycle requests that both slip past it still cannot start two jobs,
    # the second insert fails and ``task_service`` turns that into a 409.
    # Declared on the model, not only in a migration: an index that exists
    # only in a migration is what autogenerate drops again (the original
    # project lost this one that way).
    __table_args__ = (
        Index(
            "uq_tasks_active_per_deployment",
            "deploymentId",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING')"),
        ),
        # Polled by every worker thread every few seconds, and by the API's
        # finalizer; both only ever look at a handful of rows, so these stay
        # small however long the task history gets.
        Index("ix_tasks_pending", "created_at", postgresql_where=text("status = 'PENDING'")),
        Index("ix_tasks_unfinalized", "finished_at", postgresql_where=text("finalized_at IS NULL")),
    )

    taskId: Mapped[uuid.UUID] = _uuid_pk()
    deploymentId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.deploymentId", ondelete="CASCADE"),
        index=True,
    )
    type: Mapped[TaskType] = mapped_column(Enum(TaskType))
    status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), default=TaskStatus.PENDING)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    logs: Mapped[str | None] = mapped_column(Text)  # JSON or text
    # OpenTofu outputs, Fernet-encrypted JSON (jobs.seal_outputs): they carry
    # the generated credentials of the students.
    outputs: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Last known phase/percent, so a page reload shows where a running task
    # is without replaying its log.
    current_phase: Mapped[str | None] = mapped_column(String(50))
    progress_pct: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # --- The task row is also the job queue entry (plan D4). ---------------
    # What the worker needs to run the job (app, release, variables, teams,
    # the caller's OpenStack credential envelope), Fernet-encrypted JSON.
    # Cleared when a worker claims the task, so credentials and variable
    # values sit in the queue only while nobody is working on them.
    payload: Mapped[bytes | None] = mapped_column(LargeBinary)
    # Which worker holds the task, and until when. The worker extends the
    # lease while it runs; a RUNNING task whose lease ran out belongs to a
    # worker that died, and the API's reaper fails it.
    claimed_by: Mapped[str | None] = mapped_column(String)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    # Set by the API once the follow-up work for a finished task is done
    # (notification mails, soft-delete after destroy). NULL on a finished
    # task means "still to do", which is how that work runs exactly once
    # even with several API replicas.
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime)
    # SHA-256 of the secret the job presents to the state backend
    # (``/internal/tfstate``). The secret itself travels in the sealed
    # payload only; it opens the state of this task's deployment and only
    # while the task is RUNNING.
    state_token_hash: Mapped[str | None] = mapped_column(String(64))

    deployment: Mapped[Deployment] = relationship(back_populates="tasks")
    events: Mapped[list[TaskEvent]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ----------------------------------------------------------------
# TERRAFORM STATE MODEL
# ----------------------------------------------------------------
class TerraformState(Base):
    """The OpenTofu state of one deployment (plan E3).

    Written and read by OpenTofu through the API's HTTP state backend, never
    by the worker directly: the job holds no database credentials. The state
    lists every resource with its attributes, generated passwords included,
    so it is stored encrypted. Deleted once a destroy has succeeded.
    """

    __tablename__ = "terraform_states"

    deploymentId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.deploymentId", ondelete="CASCADE"),
        primary_key=True,
    )
    state: Mapped[bytes | None] = mapped_column(LargeBinary)  # Fernet, JSON inside
    # OpenTofu's lock: its lock ID, the lock info it sent (returned to a
    # competing client), and the task that took it. A lock whose task is no
    # longer running is stale and may be taken over; otherwise a worker that
    # died mid-apply would block the deployment for good.
    lock_id: Mapped[str | None] = mapped_column(String)
    lock_info: Mapped[str | None] = mapped_column(Text)
    lock_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


# ----------------------------------------------------------------
# TASK EVENT MODEL
# ----------------------------------------------------------------
class TaskEvent(Base):
    """One progress, log or lifecycle event of a running task.

    Appended by the worker as the job runs; the API's live stream reads them
    in ``id`` order, so the id doubles as the stream's resume cursor. The
    payload is the same dict the stream sends to the browser.
    """

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    taskId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.taskId", ondelete="CASCADE"), index=True
    )
    # "task-progress", "task-log", "task-succeeded", ...
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    task: Mapped[Task] = relationship(back_populates="events")


# ----------------------------------------------------------------
# USERTODEPLOYMENT MODEL
# ----------------------------------------------------------------
class UserToDeployment(Base):
    """Direct membership of a user in a deployment (every team member gets one).

    Written alongside the team rows when a deployment is created; counts as
    team membership for access checks (``capabilities.is_team_member``).
    """

    __tablename__ = "user_to_deployments"

    userToDeploymentId: Mapped[uuid.UUID] = _uuid_pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.userId", ondelete="CASCADE"), index=True
    )
    deploymentId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.deploymentId", ondelete="CASCADE"),
        index=True,
    )

    user: Mapped[User] = relationship(back_populates="user_to_deployments")
    deployment: Mapped[Deployment] = relationship(back_populates="user_to_deployments")


# ----------------------------------------------------------------
# TEAM MODEL
# ----------------------------------------------------------------
class Team(Base):
    """A named team within a deployment; typically one VM per team in the app."""

    __tablename__ = "teams"

    teamId: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String)
    deploymentId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deployments.deploymentId", ondelete="CASCADE"),
        index=True,
    )

    deployment: Mapped[Deployment] = relationship(back_populates="teams")
    user_to_teams: Mapped[list[UserToTeam]] = relationship(
        back_populates="team",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


# ----------------------------------------------------------------
# USERTOTEAM MODEL
# ----------------------------------------------------------------
class UserToTeam(Base):
    """Membership of a user (usually a student of the course) in a team."""

    __tablename__ = "user_to_teams"

    userToTeamId: Mapped[uuid.UUID] = _uuid_pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.userId", ondelete="CASCADE"), index=True
    )
    teamId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.teamId", ondelete="CASCADE"), index=True
    )

    user: Mapped[User] = relationship(back_populates="user_to_teams")
    team: Mapped[Team] = relationship(back_populates="user_to_teams")


# ----------------------------------------------------------------
# USER OPENSTACK CREDENTIAL MODEL
# ----------------------------------------------------------------
class UserOpenStackCredential(Base):
    """A user's credential for one OpenStack project (plan AP5).

    A user holds one per project. ``project_id``/``project_name`` are what
    Keystone scoped the token to when the credential was saved, not what
    the user typed: they decide who counts as a peer in the project (E2),
    so they must not be claimable.
    """

    __tablename__ = "user_openstack_credentials"
    __table_args__ = (UniqueConstraint("userId", "project_id", name="uq_user_openstack_credentials_project"),)

    credentialId: Mapped[uuid.UUID] = _uuid_pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.userId", ondelete="CASCADE"),
        index=True,
    )
    auth_type: Mapped[OpenStackAuthType] = mapped_column(
        Enum(
            OpenStackAuthType,
            name="openstackauthtype",
            values_callable=lambda x: [e.value for e in x],
        ),
    )

    # Non-secret display fields (plaintext)
    auth_url: Mapped[str] = mapped_column(String)
    region_name: Mapped[str | None] = mapped_column(String)
    interface: Mapped[str | None] = mapped_column(String, default="public")
    identity_api_version: Mapped[str | None] = mapped_column(String, default="3")
    project_id: Mapped[str] = mapped_column(String, index=True)
    project_name: Mapped[str | None] = mapped_column(String)
    user_domain_name: Mapped[str | None] = mapped_column(String)
    project_domain_name: Mapped[str | None] = mapped_column(String)

    # Encrypted (Fernet ciphertext) — never logged, never returned via API
    encrypted_identifier: Mapped[bytes] = mapped_column(LargeBinary)
    encrypted_secret: Mapped[bytes] = mapped_column(LargeBinary)

    last_validated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_validation_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="openstack_credentials")


# ----------------------------------------------------------------
# APP VERSION APPROVAL MODEL
# ----------------------------------------------------------------
class AppVersionApproval(Base):
    """The review of one app version (Git tag) by an admin; one row per (app, tag).

    Submitted as PENDING, then APPROVED or REJECTED (``reviewed_by``,
    ``rejection_reason``). The approval is bound to ``commit_sha``.
    """

    __tablename__ = "app_version_approvals"
    __table_args__ = (
        UniqueConstraint("appId", "version_tag", name="uq_app_version_approval"),
    )

    approvalId: Mapped[uuid.UUID] = _uuid_pk()
    appId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("apps.appId", ondelete="CASCADE"), index=True
    )
    version_tag: Mapped[str] = mapped_column(String)
    # The commit the tag pointed to when it was submitted. The approval
    # covers this commit only: once the tag points elsewhere, the version
    # counts as unapproved until it is submitted and reviewed again.
    commit_sha: Mapped[str] = mapped_column(String(40))
    status: Mapped[AppVersionApprovalStatus] = mapped_column(
        Enum(AppVersionApprovalStatus), default=AppVersionApprovalStatus.PENDING
    )
    diff_url: Mapped[str | None] = mapped_column(String)
    notes: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.userId", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    app: Mapped[App] = relationship(back_populates="version_approvals")
    reviewer: Mapped[User | None] = relationship(foreign_keys=[reviewed_by])


__all__ = [
    "Base",
    "utcnow",
    "AppVersionApprovalStatus",
    "TaskType",
    "TaskStatus",
    "OpenStackAuthType",
    "User",
    "App",
    "Deployment",
    "Task",
    "TaskEvent",
    "TerraformState",
    "UserToDeployment",
    "Team",
    "UserToTeam",
    "UserOpenStackCredential",
    "AppVersionApproval",
]
