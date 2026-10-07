"""Pydantic request and response models of the API.

Class docstrings become the schema descriptions in ``openapi.json`` and the
generated TypeScript client; routers import from here, crud modules take the
request models as input.
"""

import json
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from appstore_api.models import AppVersionApprovalStatus, OpenStackAuthType, TaskStatus, TaskType


def _member_email(value: str) -> str:
    """Addresses are identities (plan AP3), compared lower-case everywhere."""
    email = value.strip().lower()
    local, at, domain = email.partition("@")
    if not at or not local or not domain or any(c.isspace() for c in email) or len(email) > 254:
        raise ValueError("not an e-mail address")
    return email


MemberEmail = Annotated[str, AfterValidator(_member_email)]
# A course is the group token of role-provider-service, e.g. ``group:wwi23seb``.
CourseToken = Annotated[str, StringConstraints(pattern=r"^group:[^#\s]+$", max_length=200)]
TeamName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


# ----------------------------------------------------------------
# USER SCHEMAS
# ----------------------------------------------------------------
class UserResponse(BaseModel):
    """A person as other resources reference them. Rights are not part of it:
    they come from the caller's tokens and are never stored."""

    userId: UUID
    email: EmailStr
    username: str
    firstName: str | None = None
    lastName: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# APP SCHEMAS
# ----------------------------------------------------------------
class AppBase(BaseModel):
    """Fields shared by app requests and responses."""

    name: str
    description: str | None = None
    git_link: str | None = None
    is_private: bool = False


class AppCreate(AppBase):
    """Body of ``POST /apps``: register an app from a Git repository."""

    # Image is sent as a full data-URL string, e.g.
    # ``"data:image/png;base64,iVBORw0KG..."``. The router decodes the
    # base64 part to bytes and stores mime + bytes in two columns.
    image: str | None = None
    # When True and is_private=False, all existing Git tags are
    # automatically submitted for review right after creation.
    submit_all_versions: bool = False


class AppUpdate(BaseModel):
    """Body of ``PUT /apps/{id}``: partial update; omitted fields stay unchanged."""

    # ``git_link`` is intentionally NOT editable — once an app has
    # deployments, changing the repo would make the version history
    # inconsistent. Callers may include it; it is silently ignored.
    name: str | None = None
    description: str | None = None
    is_private: bool | None = None
    # Same data-URL convention as ``AppCreate``. Pass ``""`` to clear
    # the image; ``None`` (the default) leaves it unchanged.
    image: str | None = None

    model_config = ConfigDict(extra="ignore")


class AppResponse(AppBase):
    """An app of the catalogue."""

    appId: UUID
    userId: UUID
    created_at: datetime
    is_private: bool
    # An admin deactivated the app; only an admin can make it public again.
    hidden_by_admin: bool = False
    # Data-URL or null. Populated from ``app.image`` + ``app.image_mime``
    # by ``serialize_app_image``; the raw bytes never leave the backend.
    image: str | None = None

    model_config = ConfigDict(from_attributes=True)


class AppWithUser(AppResponse):
    """An app with its owner."""

    user: UserResponse

    model_config = ConfigDict(from_attributes=True)


class AppWithVersions(AppWithUser):
    """An app with its owner and its Git tags, each marked with its approval state."""

    # version, commit, sha, type, approved (bool), and release metadata when the host has it
    versions: list[dict[str, Any]] = []

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# APP VERSION APPROVAL SCHEMAS
# ----------------------------------------------------------------
class AppVersionApprovalSubmit(BaseModel):
    """Body of a version submission: optional hints for the reviewing admin."""

    diff_url: str | None = None
    notes: str | None = None


class AppVersionApprovalDecision(BaseModel):
    """Body of reject and revoke: the reason, shown to the app owner."""

    rejection_reason: str


class AppVersionApprovalResponse(BaseModel):
    """The review state of one version tag of an app, bound to the reviewed commit."""

    approvalId: UUID
    appId: UUID
    version_tag: str
    # The reviewed commit; the approval does not cover the tag once it moves.
    commit_sha: str
    # How the version runs and, for pods, what the approval covers besides the commit.
    runtime: str = "openstack-vm"
    spec_sha256: str | None = None
    image_digests: list[str] | None = None
    status: AppVersionApprovalStatus
    diff_url: str | None = None
    notes: str | None = None
    rejection_reason: str | None = None
    reviewed_by: UUID | None = None
    reviewed_at: datetime | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("image_digests", mode="before")
    @classmethod
    def _digests_from_json(cls, value):
        return json.loads(value) if isinstance(value, str) else value


class AppVersionApprovalWithApp(AppVersionApprovalResponse):
    """A version review with its app, for the admins' review queue."""

    app: AppResponse

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# DEPLOYMENT SCHEMAS
# ----------------------------------------------------------------
class Team(BaseModel):
    """A team in a deployment request: a name and its members' e-mail addresses."""

    name: TeamName
    # Members by address; each must be a student of the deployment's course.
    emails: list[MemberEmail] = []


class DeploymentBase(BaseModel):
    """Fields shared by deployment requests and responses."""

    name: str
    appId: UUID


class DeploymentFileUpload(BaseModel):
    """Single file uploaded by the lecturer in the deploy wizard.

    Persisted verbatim into ``userInputVar.terraform`` keyed by the
    variable name (and recipient key for team/user scope) so the worker
    passes it to terraform and cloud-init decodes it into ``write_files``.

    ``content_b64`` MUST be standard (RFC 4648) base64. The value sent
    to Terraform stays base64 for cloud-init's ``encoding: b64``.
    """
    name: str
    content_b64: str
    size: int
    content_type: str | None = None


class DeploymentCreate(DeploymentBase):
    """Body of ``POST /deployments``: deploy an app version for a course, in teams."""

    # Required: a deployment is always of a specific version, never of
    # whatever the default branch holds at the time.
    releaseTag: str
    # One of the caller's ``#dozent`` courses (``GET /me/courses``).
    course: CourseToken
    # One of the caller's OpenStack credentials; the deployment lives in
    # its project (``GET /me/openstack-credentials``).
    # Not needed for apps that run as pods (appstore.yaml).
    credentialId: UUID | None = None
    userInputVar: dict[str, Any] | None = None
    # Files-map keyed by ``@openstack:file:<scope>``-marked variable
    # name. Inner key:
    #   * scope = all  → exactly one inner key, conventionally "all"
    #   * scope = team → one entry per team name
    #   * scope = user → one entry per ``Team-User`` composite key
    # The backend doesn't auto-route — what the wizard puts in here
    # ends up 1:1 in the Terraform variable.
    files: dict[str, dict[str, DeploymentFileUpload]] | None = None
    teams: list[Team] = []


class DeploymentResponse(DeploymentBase):
    """A deployment; ``status`` is taken from its latest task."""

    deploymentId: UUID
    userId: UUID
    releaseTag: str | None = None
    commit_sha: str | None = None
    course: str | None = None
    os_project_id: str | None = None
    userInputVar: dict[str, Any] | None = None
    status: str | None = None  # From latest task
    created_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DeploymentWithRelations(DeploymentResponse):
    """A deployment with its owner and app."""

    user: UserResponse
    app: AppResponse

    model_config = ConfigDict(from_attributes=True)


class DeploymentTeamMember(BaseModel):
    """A member of a deployment's team."""

    userId: UUID
    email: str
    username: str

    model_config = ConfigDict(from_attributes=True)


class DeploymentTeamResponse(BaseModel):
    """A team of a deployment with its members, as stored."""

    teamId: UUID
    name: str
    members: list[DeploymentTeamMember] = []

    model_config = ConfigDict(from_attributes=True)


class TaskSummary(BaseModel):
    """The latest task of a deployment: type, status and progress."""

    taskId: UUID
    type: TaskType
    status: TaskStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    # Live-progress fields (mirror of Task model), used to render the
    # progress bar on page reload; SSE supplies real-time updates.
    current_phase: str | None = None
    progress_pct: int | None = None

    model_config = ConfigDict(from_attributes=True)


class DeploymentOutputs(BaseModel):
    """The deployment's OpenTofu outputs; their structure depends on the app."""
    raw: dict[str, Any] | None = None  # Full outputs as dict

    model_config = ConfigDict(from_attributes=True)


class MyAccessResponse(BaseModel):
    """A single team member's own access credentials.

    Returned by ``GET /deployments/{id}/my-access`` so a member (student)
    can see their OWN credentials without the owner-view that gates the
    full outputs. Only the caller's own account is ever present.

    Both maps mirror the raw terraform ``user_accounts`` / ``team_vms``
    output shape (one key each: the member's account and their team's VM)
    so the frontend's existing account-matching pipeline consumes this
    unchanged. Empty maps mean "no credentials yet" (no successful deploy,
    or the app issued no per-user account) — a valid 200, not an error.
    """
    user_accounts: dict[str, dict[str, Any]] = {}
    team_vms: dict[str, dict[str, Any]] = {}

    model_config = ConfigDict(from_attributes=True)


class MyAccessEntry(BaseModel):
    """One deployment on "Meine Zugänge": where the caller is a team member."""

    deploymentId: UUID
    name: str
    app_name: str
    course: str
    team_name: str
    status: str | None = None
    user_accounts: dict[str, dict[str, Any]] = {}
    team_vms: dict[str, dict[str, Any]] = {}


class DeploymentPermissions(BaseModel):
    """What the caller may do with this deployment, as capabilities.py decides.

    For the UI to offer the right things; every action is checked again.
    """
    # Tasks, logs, all teams and outputs (owner, project peer, admin).
    owner_view: bool
    # Pause, resume, destroy, redeploy, change teams (owner, project peer).
    operate: bool


class DeploymentDetail(DeploymentWithRelations):
    """A deployment with the caller's permissions, teams, latest task and outputs.

    Outputs and logs are only present for callers with the owner view.
    """
    permissions: DeploymentPermissions
    teams: list[DeploymentTeamResponse] = []
    latest_task: TaskSummary | None = None
    outputs: DeploymentOutputs | None = None
    logs: str | None = None  # Optional: can be excluded for large logs

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# DEPLOYMENT RESOURCE / INFRASTRUCTURE SCHEMAS
# ----------------------------------------------------------------
# These mirror the dataclasses in ``services/deployment_status.py``
# 1:1 so the conversion at the endpoint boundary is a plain
# ``model_validate(asdict(view))``. Defined separately from the
# dataclasses because Pydantic integrates better with FastAPI's OpenAPI
# emitter and the service module stays free of a Pydantic dependency.


class LifecycleStatesSchema(BaseModel):
    """Server lifecycle quad + optional fault message.

    Fields are pass-through from OpenStack's Nova response (stable
    strings like ``"ACTIVE"`` / ``"BUILD"`` / ``"ERROR"``). The frontend
    renders a pill from ``status`` + ``task_state`` and shows
    ``fault_message`` as a banner when ``status == "ERROR"``.
    """
    status: str | None = None
    task_state: str | None = None
    vm_state: str | None = None
    power_state: str | None = None
    fault_message: str | None = None


class HardwareSpecSchema(BaseModel):
    """Flavor, image and placement of a server."""

    flavor_name: str | None = None
    ram_mb: int | None = None
    vcpus: int | None = None
    disk_gb: int | None = None
    image_id: str | None = None
    image_name: str | None = None
    availability_zone: str | None = None
    launched_at: str | None = None


class NetworkAddressSchema(BaseModel):
    """One address of a server on one network."""

    network: str
    fixed_ip: str | None = None
    floating_ip: str | None = None
    mac: str | None = None


class NetworkPortSchema(BaseModel):
    """A Neutron port of a server (detail endpoint only)."""

    port_id: str
    network_id: str | None = None
    status: str | None = None
    mac: str | None = None
    fixed_ip: str | None = None
    security_group_ids: list[str] = []


class SecurityGroupSummarySchema(BaseModel):
    """A security group of a server with its rule counts (detail endpoint only)."""

    id: str
    name: str
    description: str | None = None
    ingress_rules: int
    egress_rules: int


class VolumeAttachmentSchema(BaseModel):
    """A volume attached to a server (detail endpoint only)."""

    volume_id: str
    device: str | None = None
    size_gb: int | None = None
    bootable: bool | None = None
    status: str | None = None
    name: str | None = None


class DeploymentResourceSchema(BaseModel):
    """One row in the resource list (stage 1) or the response of the
    detail endpoint (stage 2 — same shape, more fields populated).

    Non-instance categories (network, subnet, etc.) only populate
    ``address``, ``type``, ``category``, ``provider_id``,
    ``display_name``; the instance-only fields stay ``None`` /
    empty list.
    """
    address: str
    type: str
    category: str
    team: str | None = None
    provider_id: str
    display_name: str
    drift: Literal["in_sync", "stale", "missing"] = "in_sync"
    # Stage 1 fields (instance-only)
    lifecycle: LifecycleStatesSchema | None = None
    hardware: HardwareSpecSchema | None = None
    addresses: list[NetworkAddressSchema] = []
    # Stage 2 fields (instance-only, only set on the detail endpoint)
    ports: list[NetworkPortSchema] | None = None
    security_groups: list[SecurityGroupSummarySchema] | None = None
    volumes: list[VolumeAttachmentSchema] | None = None
    metadata: dict[str, str] | None = None


class PodWorkloadSchema(BaseModel):
    """One pod workload (a team's or a person's) of a Kubernetes deployment."""

    workload: str
    team: str | None = None
    user: str | None = None
    ready: bool
    restarts: int = 0
    # Pending, Running, Stopped (paused), or the reason it does not start.
    phase: str
    url: str | None = None
    lastEvent: str | None = None


class DeploymentResourceListResponse(BaseModel):
    """The resources of a deployment's OpenTofu state, optionally joined with live OpenStack data.

    An object rather than a bare list so metadata can be added later without a breaking change.
    """
    resources: list[DeploymentResourceSchema]
    # Kubernetes deployments: the pods instead of OpenStack resources.
    runtime: str = "openstack-vm"
    workloads: list[PodWorkloadSchema] = []
    # True when the response was fetched with live OpenStack join.
    # False means the caller passed ``?refresh=false`` and the
    # response reflects only cached TF state.
    live: bool


# ----------------------------------------------------------------
# Task SCHEMAS
# ----------------------------------------------------------------
class TaskBase(BaseModel):
    """Fields of a task (a job run by the worker for a deployment)."""

    deploymentId: UUID
    type: TaskType
    status: TaskStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: str | None = None
    current_phase: str | None = None
    progress_pct: int | None = None

class TaskUpdate(BaseModel):
    """Partial update of a task; only set fields are written."""

    status: TaskStatus | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    logs: str | None = None
    current_phase: str | None = None
    progress_pct: int | None = None

class TaskResponse(TaskBase):
    """A task of a deployment, including its log."""

    taskId: UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# TEAM SCHEMAS
#
# Teams are bound directly to a deployment (FK
# ``deployments.deploymentId`` -> ``Team.deploymentId``). The schemas
# mirror the model 1:1.
# ----------------------------------------------------------------
class TeamBase(BaseModel):
    """Fields shared by team requests and responses."""

    name: TeamName
    deploymentId: UUID


class TeamCreate(TeamBase):
    """Body of ``POST /teams``: a new team of a deployment with its members."""

    emails: list[MemberEmail] = []


class TeamUpdate(BaseModel):
    """Body of ``PUT /teams/{id}``: rename a team."""

    name: TeamName | None = None


class TeamMemberAdd(BaseModel):
    """Body for adding one member to a team, by e-mail address."""

    email: MemberEmail


class TeamResponse(TeamBase):
    """A team of a deployment."""

    teamId: UUID

    model_config = ConfigDict(from_attributes=True)


class TeamWithMembers(TeamResponse):
    """A team with its members."""

    users: list[UserResponse] = []

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# COURSE SCHEMAS
# ----------------------------------------------------------------
class MeResponse(BaseModel):
    """The caller and what they may do here, for the UI to offer the right actions.

    Derived from this request's tokens; the API checks every action itself,
    so this only decides what the UI shows.
    """

    userId: UUID
    email: str
    is_admin: bool
    is_dozent: bool
    # May register apps (a dozent or an admin).
    can_register_apps: bool
    # May start deployments (teaches at least one course).
    can_deploy: bool


class CourseResponse(BaseModel):
    """A course the caller teaches (a ``#dozent`` relation in role-provider-service)."""

    course: str
    display_name: str
    description: str = ""

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# OPENSTACK CREDENTIAL SCHEMAS
# ----------------------------------------------------------------
class OpenStackCredentialBase(BaseModel):
    """Non-secret connection metadata. Mirrors the `clouds.yaml` shape."""
    auth_type: OpenStackAuthType
    auth_url: str
    region_name: str | None = None
    interface: str | None = "public"
    identity_api_version: str | None = "3"
    project_id: str | None = None
    project_name: str | None = None
    user_domain_name: str | None = None
    project_domain_name: str | None = None


class OpenStackCredentialUpsert(OpenStackCredentialBase):
    """Body of POST /me/openstack-credentials.

    `identifier` is either a username (password auth) or an
    application-credential ID (preferred: revocable, bound to one project).
    `secret` is the corresponding password or application-credential
    secret. Both are stored encrypted at rest. For password auth,
    `project_id`/`project_name` say which project to scope to; what is
    stored is the project Keystone actually scoped the token to.
    """
    identifier: str = Field(..., min_length=1, description="username OR application-credential ID")
    secret: str = Field(..., min_length=1, description="password OR application-credential secret")

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "OpenStackCredentialUpsert":
        """Password auth needs a user domain and a project to scope to (422 otherwise)."""
        if self.auth_type == OpenStackAuthType.PASSWORD:
            if not self.user_domain_name:
                raise ValueError("user_domain_name is required for password auth")
            if not (self.project_id or self.project_name):
                raise ValueError("project_id or project_name is required for password auth")
        # application-credential auth: project_id is recommended but not required;
        # the credential itself carries the project scope.
        return self


class OpenStackCredentialFromYaml(BaseModel):
    """Convenience body: paste/upload a `clouds.yaml` and let the server pick it apart."""
    clouds_yaml: str = Field(..., min_length=1, description="raw clouds.yaml file contents")
    cloud_name: str | None = Field(
        None, description="Pick a specific cloud from the YAML; required when there is more than one"
    )


class OpenStackCredentialResponse(BaseModel):
    """A stored credential, masked — never identifier or secret material.

    ``project_id``/``project_name`` are the project Keystone scoped the
    credential to. ``active_deployments`` counts the caller's live
    deployments in that project; deleting the credential is refused while
    there are any, so they cannot be orphaned.
    """
    credentialId: UUID
    auth_type: OpenStackAuthType
    auth_url: str
    region_name: str | None = None
    interface: str | None = None
    identity_api_version: str | None = None
    project_id: str
    project_name: str | None = None
    user_domain_name: str | None = None
    project_domain_name: str | None = None
    last_validated_at: datetime | None = None
    last_validation_error: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    active_deployments: int = 0

    model_config = ConfigDict(from_attributes=True)


# ----------------------------------------------------------------
# OPENSTACK RESOURCE PICKER (``/me/openstack-credentials/{id}/resources``)
# ----------------------------------------------------------------
# Flat views of what the wizard offers for ``@openstack:`` markers. Every
# item has ``id`` and ``name``, so a picker reads them uniformly.
class PickerItem(BaseModel):
    """An OpenStack resource offered in the deploy wizard's value help."""

    id: str | None = None
    name: str = ""


class NetworkItem(PickerItem):
    """A Neutron network."""

    description: str = ""
    shared: bool = False
    external: bool = False
    status: str = ""


class SubnetItem(PickerItem):
    """A Neutron subnet."""

    cidr: str = ""
    ip_version: int | None = 4
    network_id: str | None = None
    gateway_ip: str = ""


class FlavorItem(PickerItem):
    """A Nova flavor."""

    vcpus: int = 0
    ram: int = Field(0, description="MB")
    disk: int = Field(0, description="GB")
    is_public: bool = True


class ImageItem(PickerItem):
    """A Glance image."""

    status: str = ""
    visibility: str = ""
    size: int = Field(0, description="bytes")
    disk_format: str = ""


class KeypairItem(PickerItem):
    """A Nova key pair of the credential's user."""

    fingerprint: str = ""
    type: str = "ssh"


class DescribedItem(PickerItem):
    """A resource with a description (security groups, floating IP pools)."""

    description: str = ""


class VolumeItem(PickerItem):
    """A Cinder volume."""

    size: int = Field(0, description="GB")
    status: str = ""
    volume_type: str = ""
    bootable: bool = False


class RouterItem(PickerItem):
    """A Neutron router."""

    status: str = ""
    external_gateway_info: dict[str, Any] | None = None


class AvailabilityZoneItem(PickerItem):
    """A compute availability zone."""

    state: str | dict[str, Any] = ""


# ----------------------------------------------------------------
# LIFECYCLE ACTIONS
# ----------------------------------------------------------------
class LifecycleActionResponse(BaseModel):
    """202 answer of pause/resume/destroy/redeploy: the queued task.

    ``status`` is the deployment's status right after queueing, so the UI
    can switch to the live view without another request.
    """
    status: str
    task_id: UUID | None = None
    deployment_id: UUID | None = None
