"""Worker configuration, read from environment variables only (see the README table)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All worker settings; one field per environment variable of the same name."""

    # The AppStore database. It is also the job queue (plan D4): the worker
    # claims tasks from it, appends their events and records their results.
    DATABASE_URL: str

    # Jobs run in parallel per worker process. Each is mostly waiting on
    # OpenTofu, Packer or OpenStack, so threads are enough.
    WORKER_CONCURRENCY: int = 4
    # How often an idle worker looks for new tasks.
    WORKER_POLL_INTERVAL_SECONDS: float = 2.0
    # A claimed task belongs to this worker until the lease runs out; it is
    # renewed every third of it while the job runs. When a worker dies, the
    # API fails its tasks once their lease has expired.
    WORKER_LEASE_SECONDS: int = 120

    # A job taking longer is stopped: its running tool is killed and the task
    # fails. Covers a Packer build plus an apply with room to spare.
    WORKER_JOB_TIMEOUT_SECONDS: int = 7200
    # When set, worker slot n runs its jobs' tools as UID/GID base+n (see
    # job_context.py). Requires the worker to run as root; the image sets it.
    WORKER_JOB_UID_BASE: int | None = None
    # Per-slot home directories of those users (plugin caches).
    WORKER_JOB_HOME_BASE: str = "/var/lib/appstore-worker"

    # Where jobs clone app repositories.
    TEMP_REPO_BASE_PATH: str = "/tmp/worker_repos"
    # Same list as the API's: checked again before cloning, so a URL that
    # got into the database some other way is still not fetched.
    APP_GIT_ALLOWED_HOSTS: str = "github.com,gitlab.dhbw.cloud"

    # The AppStore API as the worker's jobs reach it; OpenTofu keeps each
    # deployment's state there (plan E3), e.g. http://appstore-api:8000.
    APPSTORE_API_URL: str

    # Tool paths in the image.
    TOFU_PATH: str = "/usr/local/bin/tofu"
    PACKER_PATH: str = "/usr/local/bin/packer"
    # OpenTofu log level for debugging the worker (TF_LOG); off by default
    # because the trace drowns the error a user needs to see.
    WORKER_TF_LOG: str = ""

    # Development without a cloud (plan AP7): jobs are played through with
    # realistic phases, logs, outputs and state, and nothing is created in
    # OpenStack (simulate.py). Never on in a real installation.
    WORKER_SIMULATE: bool = False
    # How long each simulated phase takes.
    WORKER_SIMULATE_STEP_SECONDS: float = 1.5

    # --- Pod runtime (apps with an appstore.yaml) ------------------------
    # Same ceilings and allowlist as the API; the spec is validated again here.
    APP_IMAGE_REGISTRY_ALLOWLIST: str = "ghcr.io/dhbw-appstore-t3/"
    APP_MAX_CPU: str = "2"
    APP_MAX_MEMORY: str = "4Gi"
    APP_MAX_STORAGE: str = "20Gi"
    # Student workloads get https://<workload>-<deployment>.apps.<K8S_ZONE>.
    K8S_ZONE: str = ""
    K8S_INGRESS_CLASS: str = "traefik"
    # Namespace of the ingress controller (allowed to reach the pods).
    K8S_INGRESS_NAMESPACE: str = "kube-system"
    # TLS: a ready wildcard Secret to reference in every namespace, or a
    # cert-manager ClusterIssuer that issues one certificate per host.
    K8S_TLS_SECRET: str = ""
    K8S_CLUSTER_ISSUER: str = ""
    K8S_STORAGE_CLASS: str = ""
    # JSON objects: {"appstore.dhbw/workload": "student"} and a list of tolerations.
    K8S_STUDENT_NODE_SELECTOR: str = ""
    K8S_STUDENT_TOLERATIONS: str = ""
    # Pod/service/node CIDRs of the cluster, excluded from "internet" egress
    # on top of the private ranges (comma separated, IPv4 and IPv6).
    K8S_EXTRA_EGRESS_EXCEPT: str = ""
    # The worker's own service account; the namespace's RoleBinding grants it
    # the ClusterRole below inside that namespace and nowhere else.
    K8S_WORKER_SERVICE_ACCOUNT: str = "appstore-worker"
    K8S_WORKER_NAMESPACE: str = ""
    K8S_DEPLOYER_CLUSTER_ROLE: str = "appstore-deployer-ns"
    # How long a deploy may wait for all pods to become ready / a namespace to disappear.
    K8S_READY_TIMEOUT_SECONDS: float = 300.0
    K8S_DELETE_TIMEOUT_SECONDS: float = 300.0
    K8S_POLL_INTERVAL_SECONDS: float = 2.0

    # Fernet key shared with the API: opens the job payload and the
    # OpenStack credential inside it.
    CREDENTIAL_ENCRYPTION_KEY: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
