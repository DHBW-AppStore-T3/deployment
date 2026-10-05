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

    # Fernet key shared with the API: opens the job payload and the
    # OpenStack credential inside it.
    CREDENTIAL_ENCRYPTION_KEY: str

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
