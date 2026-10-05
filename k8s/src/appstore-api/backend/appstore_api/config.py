"""The API's configuration, read once from environment variables (and ``.env``).

Import the ``settings`` singleton; every variable is also listed in the README.
The worker has its own ``config.py``; ``CREDENTIAL_ENCRYPTION_KEY`` must match.
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings

from appstore_shared.git_urls import parse_allowed_hosts


class Settings(BaseSettings):
    """All settings; each attribute is the environment variable of the same name (case-sensitive).

    Groups: database (``DATABASE_URL``), Git sources (``APP_GIT_ALLOWED_HOSTS``,
    ``TEMP_REPO_BASE_PATH``), development switches (``API_MODE``,
    ``API_DUMMY_AUTH``, ``OPENSTACK_SIMULATE``, ``ROLE_PROVIDER=mock``), sign-in
    (``OIDC_*``), group tokens (``ROLE_PROVIDER*``, ``APPSTORE_ADMIN_GROUPS``),
    HTTP (``CORS_ORIGINS``, ``API_ROOT_PATH``), encryption
    (``CREDENTIAL_ENCRYPTION_KEY``) and mail (``SMTP_*``, ``APPSTORE_UI_URL``).
    ``DATABASE_URL`` and ``CREDENTIAL_ENCRYPTION_KEY`` have no default. The
    validators below make the service refuse to start with an inconsistent
    combination rather than fail per request.
    """

    # Database: SQLAlchemy URL of the Postgres database shared with the worker
    # (it is also the job queue).
    DATABASE_URL: str

    # Git. Apps come from public repositories only, cloned anonymously
    # (plan D6), so there is no token to configure.
    # Scratch directory for the API's sparse clones (an app's
    # terraform/variables.tf and packer/ templates).
    TEMP_REPO_BASE_PATH: str = "/tmp/worker_repos"
    # Comma-separated hosts apps may be registered and cloned from. The URL
    # is user input; everything else is refused before git ever runs.
    # gitlab.dhbw.cloud is the DHBW Cloud's own GitLab.
    APP_GIT_ALLOWED_HOSTS: str = "github.com,gitlab.dhbw.cloud"

    # "development" unlocks API_DUMMY_AUTH; anything else is production.
    API_MODE: str = "production"
    # Development only: trust the X-Dummy-Auth-User header as the caller's
    # e-mail, the same switch the other platform services and the UI's dev
    # setup use. Like openstack-management-api, the service refuses to start
    # with it unless API_MODE=development: silently ignoring it would hide a
    # misconfiguration, silently honouring it would turn authentication off.
    API_DUMMY_AUTH: bool = False

    # OIDC bearer tokens (see oidc.py). Required unless dummy auth is on.
    OIDC_ISSUER_URL: str = ""
    # The audience the tokens must carry; the same client as the UI's.
    OIDC_CLIENT_ID: str = ""
    # Optional: with it, no discovery request is needed to find the keys.
    OIDC_JWKS_URL: str = ""

    # Where group memberships come from (services/role_provider.py): "http"
    # (role-provider-service) or "mock" (development only).
    ROLE_PROVIDER: str = "http"
    ROLE_PROVIDER_URL: str = ""
    # A read token of role-provider-service (its API_TOKENS).
    ROLE_PROVIDER_API_TOKEN: str = ""
    # Per lookup; on timeout the caller keeps only their user: token (auth.py).
    ROLE_PROVIDER_TIMEOUT_SECONDS: float = 5.0

    # Comma-separated tokens (e.g. "group:appstore_admins") whose holders are
    # AppStore admins: they approve app versions and can see everything.
    APPSTORE_ADMIN_GROUPS: str = ""

    # CORS: browser origins allowed to call the API directly (JSON list in the
    # env var). Behind the UI's proxy the calls are same-origin.
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Path prefix the API is reached under behind a proxy that strips it
    # (``/api/appstore`` behind the self-service UI). Only the docs page's
    # links use it; routes stay where they are.
    API_ROOT_PATH: str = ""

    # Symmetric Fernet key shared with the worker. Used to encrypt OpenStack
    # credentials at rest and to seal the envelope shipped to the worker.
    # Generate: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
    CREDENTIAL_ENCRYPTION_KEY: str

    # Mail after a deploy (plan E5; the mails carry no secrets). Off unless
    # SMTP_ENABLED is set and SMTP_HOST is given. SMTP_USER/SMTP_PASSWORD are
    # optional: the DHBW relay accepts mail from the cluster without login.
    # Port 465 means implicit TLS; otherwise SMTP_STARTTLS decides whether
    # the connection is upgraded (keep it on unless the relay cannot).
    # Being able to turn delivery off separately lets the resend endpoint
    # tell "we chose not to send" (503) from "the relay refused" (502).
    SMTP_ENABLED: bool = False
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_STARTTLS: bool = True
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "DHBW AppStore"

    # Public URL of the self-service UI, without trailing slash. Mails link
    # to its AppStore pages ("Meine Zugänge", the deployment detail page).
    APPSTORE_UI_URL: str = "http://localhost:5173"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"

    @model_validator(mode="after")
    def _dummy_auth_only_in_development(self) -> "Settings":
        """Refuse API_DUMMY_AUTH outside API_MODE=development."""
        if self.API_DUMMY_AUTH and self.API_MODE != "development":
            raise ValueError(
                "API_DUMMY_AUTH=true is not allowed unless API_MODE=development — "
                "refusing to start with an authentication bypass"
            )
        return self

    # Development without a cloud (plan AP7): credentials are accepted
    # without Keystone and the resource picker, quota and live server view
    # answer from fixed data (services/openstack_simulation.py). Pairs with
    # the worker's WORKER_SIMULATE. Only with API_MODE=development.
    OPENSTACK_SIMULATE: bool = False

    @model_validator(mode="after")
    def _simulation_only_in_development(self) -> "Settings":
        """Refuse OPENSTACK_SIMULATE outside API_MODE=development."""
        if self.OPENSTACK_SIMULATE and self.API_MODE != "development":
            raise ValueError("OPENSTACK_SIMULATE=true fakes OpenStack; only with API_MODE=development")
        return self

    @model_validator(mode="after")
    def _auth_is_configured(self) -> "Settings":
        """Require OIDC (or dummy auth) and a usable role provider configuration."""
        # Checked at start-up so a misconfiguration stops the pod instead of
        # rejecting every request later; the provider itself is not asked.
        if not self.API_DUMMY_AUTH and not (self.OIDC_ISSUER_URL and self.OIDC_CLIENT_ID):
            raise ValueError("OIDC_ISSUER_URL and OIDC_CLIENT_ID are required unless API_DUMMY_AUTH=true")
        if self.ROLE_PROVIDER not in ("http", "mock"):
            raise ValueError(f"ROLE_PROVIDER must be 'http' or 'mock', not {self.ROLE_PROVIDER!r}")
        if self.ROLE_PROVIDER == "mock" and self.API_MODE != "development":
            raise ValueError("ROLE_PROVIDER=mock hands out fake group memberships; only with API_MODE=development")
        if self.ROLE_PROVIDER == "http" and not (self.ROLE_PROVIDER_URL and self.ROLE_PROVIDER_API_TOKEN):
            raise ValueError("ROLE_PROVIDER=http needs ROLE_PROVIDER_URL and ROLE_PROVIDER_API_TOKEN")
        return self

    @property
    def git_allowed_hosts(self) -> frozenset[str]:
        """``APP_GIT_ALLOWED_HOSTS`` parsed into normalised host names."""
        return parse_allowed_hosts(self.APP_GIT_ALLOWED_HOSTS)

    @property
    def admin_tokens(self) -> frozenset[str]:
        """``APPSTORE_ADMIN_GROUPS`` as a set of tokens; holding any one makes a caller admin."""
        return frozenset(t.strip() for t in self.APPSTORE_ADMIN_GROUPS.split(",") if t.strip())


settings = Settings()
