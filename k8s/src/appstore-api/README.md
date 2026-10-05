# appstore-api

Backend of the DHBW AppStore: lecturers deploy ready-made exercise environments
("apps", OpenTofu/Terraform plus optional Packer) into OpenStack for the students
of a course, in teams, and every student finds their own access afterwards.
The UI is part of [self-service-ui](https://github.com/pfisterer/self-service-ui).

## Why

The AppStore started as a student project (see [NOTICE](NOTICE)). It shipped its
own Keycloak, course and user management, a Vue frontend and a Docker Compose
stack. On the cloud self-service platform all of that already exists: sign-in is
the platform's OIDC, courses and roles come from
[role-provider-service](https://github.com/pfisterer/role-provider-service)
(`group:<course>#dozent`, `group:<course>#studierende`), and the UI is the
platform's. This repository keeps what is specific to the AppStore — the app
catalogue with approvals, deployments, teams and the worker that runs the jobs —
and drops the rest. The decisions behind that (repository layout, OpenStack
access, queue, tooling) are recorded in the workspace plan
`docs/PLAN-appstore-basis.md`.

Consequences worth knowing before changing things:

- **No accounts, no roles in the database.** A caller is an e-mail address plus
  tokens. AppStore admins hold a token from `APPSTORE_ADMIN_GROUPS`; lecturers
  hold a `#dozent` token. The `users` table exists only so rows can reference a
  person and is filled on first sign-in ([auth.py](backend/appstore_api/auth.py)).
- **Apps come from public Git repositories**, read anonymously with
  `git ls-remote` and shallow clones. No tokens, no GitHub App.
- **Users bring their own OpenStack credentials**, one per project
  (application credential preferred, or a password `clouds.yaml`), stored
  Fernet-encrypted and only after Keystone accepted them. The project is taken
  from the token, so holding a credential proves access to it: everyone with
  one for the same project sees and runs that project's deployments, always
  with their own credential (plan E2). The AppStore is not coupled to
  openstack-management-api.

## Layout

| Path | What |
|---|---|
| `backend/` | `appstore_api` — FastAPI service, SQLAlchemy models, Alembic migrations |
| `worker/` | `appstore_worker` — runs deploy/destroy/pause/resume jobs with OpenTofu, Packer and the OpenStack CLI |
| `shared/` | `appstore_shared` — code both need: the database models, encryption, Git URL handling |
| `helm-chart/` | chart metadata; its version is kept equal to `VERSION` |

One [uv](https://docs.astral.sh/uv/) workspace with one lockfile, so the API and
the worker cannot drift apart on a shared dependency. Two images, both built from
the repository root.

## Versions and approvals

A version is a Git tag, but what gets reviewed and deployed is the commit the
tag points to. Submitting a version stores that commit; the approval covers it
and nothing else. A deployment pins the commit at creation, and every later job
(destroy, pause, redeploy) checks out exactly that commit. So a tag that is
moved afterwards neither sneaks unreviewed code into new deployments (the
version is unapproved again until someone submits and an admin approves it)
nor changes what runs against an existing deployment's state. Public apps
deploy approved commits only; a private app is its owner's test bench and
deploys any tag.

## How a job runs

There is no message broker: the `tasks` table is the queue.

1. The API inserts a `PENDING` task with the job's payload (app, release,
   variables, teams, the caller's OpenStack credential envelope), encrypted,
   in the same transaction as whatever the request changed. Committing is the
   hand-over.
2. A worker claims the oldest pending task with `SELECT … FOR UPDATE SKIP
   LOCKED`, removes the payload from the row and holds a lease on it, renewed
   while the job runs.
3. The job appends progress and log lines to `task_events`; the API's
   `/deployments/{id}/stream` serves them as Server-Sent Events, from any
   replica, resumable via `Last-Event-ID`.
4. OpenTofu keeps the deployment's state in the API, through its `http`
   backend (`/internal/tfstate/{deployment}`, forced by an override file
   whatever the app declares). The state is stored Fernet-encrypted; the
   credentials are a random token that came with the task and opens only
   that deployment's state, only while the task runs.
5. The worker stores the result (logs, outputs) and a terminal event.
6. The API's finalizer loop does the follow-up once per task — access mails
   after a deploy, soft-delete and dropping the state after a destroy — and
   fails `RUNNING` tasks whose lease ran out (worker died). Nothing is
   retried automatically.

An app's OpenTofu code is untrusted (a `local-exec` provisioner runs anything),
so the tools never run with the worker's own environment. Each gets `PATH`,
`HOME`, the job's OpenStack credential and the state token, nothing else; the
image runs them as a separate user per worker slot (`WORKER_JOB_UID_BASE`), so
a job can neither read the worker's database URL and key from `/proc` nor the
files of the job next to it. `WORKER_JOB_TIMEOUT_SECONDS` bounds a whole job.

Packer builds of the same image are serialised with a Postgres advisory lock,
which the database releases by itself if the holding worker dies.

## Development

```sh
make build        # uv sync: all three packages plus dev tools into .venv
make test-db      # throwaway Postgres on :55433 for the tests
make check        # lint + typecheck + tests + migrations-check + openapi-check — what CI runs
make dev          # API on :8086 (reload) + simulated worker + Postgres, with example data
make image        # both images
```

**Without a cloud.** `make dev` needs Docker and nothing else: no identity
provider, no role-provider-service, no OpenStack. It starts a Postgres of its
own (`appstore-dev-pg`, kept between runs; `make dev-db-down` removes it),
migrates and seeds it (`appstore_api/dev_seed.py`: three approved example apps
and a simulated credential for `faculty@cs.example`), then runs the API with
`--reload` and a worker. `OPENSTACK_SIMULATE` accepts credentials without
Keystone and answers the resource picker, quota and live server view from
fixed data; `WORKER_SIMULATE` plays every job through with real phases, logs,
outputs (`team_vms`, `user_accounts`) and state, a few seconds per phase. A
deploy with the Terraform variable `simulate_failure: true` fails in the apply
phase. Both switches refuse to matter outside development: the API rejects
`OPENSTACK_SIMULATE` unless `API_MODE=development`, and the worker logs a
warning at start.

```sh
curl -H 'X-Dummy-Auth-User: faculty@cs.example' localhost:8086/me/courses
```

The backend tests need their own database because they truncate every table
between tests; `make test-db` starts one in Docker. The worker and shared tests
need nothing.

**Migrations.** There is a single initial migration. Models and migrations must
agree — `make migrations-check` upgrades a scratch database, runs `alembic check`,
downgrades and upgrades again. Declare indexes on the models (`__table_args__`),
never only in a migration: the original project lost its "one active task per
deployment" index to an autogenerated migration that way. Until the first release
the initial migration may be regenerated instead of stacking new ones.

**Local sign-in.** With `API_MODE=development` and `API_DUMMY_AUTH=true` the API
takes the caller's e-mail from the `X-Dummy-Auth-User` header, like the other
platform services; with `ROLE_PROVIDER=mock` the tokens come from the same
example identities role-provider-service seeds (`faculty@cs.example` teaches
`wwi23seb`, `cs-student@cs.com` studies in it, `root.admin@uni.example` is in
`group:root_uni`).

## Sign-in and rights

Callers present an OIDC bearer token, checked like openstack-management-api
does it: issuer and audience (`OIDC_CLIENT_ID`) must match, the caller is the
`email` claim (else `preferred_username`, else `sub`). The identity provider is
not a start-up dependency — keys are fetched with the first token — and a token
that cannot be checked because the provider is down gets **503**, not 401, so
the browser does not loop through a login that cannot work. The public
`/config.json` says `sign_in_available: false` meanwhile.

Rights come from tokens, resolved by role-provider-service on every request:
`user:<email>`, `group:<id>` and `group:<id>#<relation>`. A token in
`APPSTORE_ADMIN_GROUPS` makes an admin; `group:<course>#dozent` makes a teacher of
that course. If the lookup fails, the caller keeps only `user:<email>` for that
request. There are no roles stored in the AppStore.

## Courses, teams and access

A deployment belongs to a course, one the owner teaches (`GET /me/courses`).
Its teams are lists of e-mail addresses, and every address must be a
`#studierende` of that course (`GET /courses/{course}/students`), each in one
team only; the API checks this against role-provider-service when the
deployment is created and when a team changes, so a request cannot pull in
arbitrary addresses. The browser never talks to role-provider-service.

Mails carry no credentials. After a deploy, every member is told that their
access is ready, with a link to "Meine Zugänge" in the UI; the owner gets the
teams and VM addresses. The access data itself is shown after sign-in
(`GET /me/access`, `GET /deployments/{id}/my-access`), each member seeing only
their own account.

## OpenStack credentials

`/me/openstack-credentials` lists, adds (`POST`, or `POST /from-yaml`),
re-checks (`/{id}/test`) and deletes the caller's credentials. Adding one for a
project that already has one replaces it, which is how a secret is rotated;
deleting is refused while the caller owns live deployments in the project. A
deploy names one of the caller's credentials (`credentialId`); the deployment
keeps its project, not the credential. Pause, resume, destroy and redeploy use
the credential of whoever triggers them for that project, and answer 403
`openstack_credentials_missing_for_project` without one. The wizard's resource
picker (`/me/openstack-credentials/{id}/resources/…`) and the quota
(`/me/openstack-credentials/{id}/quota`) read the chosen credential's project.

## API description and client

The API describes itself at `/swagger.json` (OpenAPI 3.1, public, like the Go
services); the internal OpenTofu state endpoints are not part of it. Operation
ids are the route functions' names in camelCase (`listMyCourses`), so a client
function only changes name when the Python function does. The description is
committed as `openapi.json`: `make openapi` rewrites it, `make openapi-check`
(part of `make check` and CI) fails when it is stale, and `make bump` updates
it with the version.

The UI uses the generated TypeScript client `@dhbw-cloud/appstore-client`,
built the same way as `@dhbw-cloud/os-mgt-client`: `make npm-package`
(hey-api, into `client-npm/`), `make npm-pack` to try it in a consumer,
`make npm-publish` to publish (a prerelease goes to the `next` dist-tag).

## Deployment (Helm)

`helm-chart/` installs two Deployments, `api` and `worker`, and one Service;
it is meant to run as a dependency of the cloud-self-service umbrella chart.
Values follow the other services' charts (`values.schema.json` with
`additionalProperties: false`, `existingSecret`, `enabled`).

- **One database, no other state.** `appstore.databaseUrl` (or the
  `database-url` key of `existingSecret`) holds the catalogue, the job queue
  and the OpenTofu state. There is no Redis and no broker.
- **No Ingress.** Browsers reach the API through the self-service UI's proxy
  under `/api/appstore/`, which must not forward `/api/appstore/internal/`:
  that is the worker's OpenTofu state backend. The worker reaches the API by
  its Service.
- **Migrations** run in the API pod's init container; an advisory lock lets
  replicas take turns.
- **The worker runs as root** with only CHOWN, DAC_OVERRIDE, FOWNER, SETUID,
  SETGID and KILL, to run each job's tools as an unprivileged user per slot
  (app code is untrusted). A rollout lets running jobs finish:
  `terminationGracePeriodSeconds` stays above the job timeout.
- `appstore.simulate` with `api.mode: development` runs the whole thing
  without a cloud, as `make dev` does.

The chart is published with the images, to `oci://ghcr.io/<owner>/charts/appstore-api`,
at the version in `Chart.yaml` (kept equal to `VERSION`). `make chart-check`
lints and renders it.

## Configuration

Environment only. The API reads `.env` in its working directory as well.

### API (`appstore_api`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — (required) | Postgres, `postgresql://…` (driver: psycopg 3) |
| `CREDENTIAL_ENCRYPTION_KEY` | — (required) | Fernet key(s), shared with the worker; encrypts OpenStack credentials, job payloads, OpenTofu state and outputs. Comma-separated for rotation: the first encrypts, all decrypt |
| `API_MODE` | `production` | `development` permits dummy auth |
| `API_DUMMY_AUTH` | `false` | Dev-only bypass via `X-Dummy-Auth-User`; the service **refuses to start** with it unless `API_MODE=development` |
| `OIDC_ISSUER_URL` | — (required without dummy auth) | Issuer of the bearer tokens |
| `OIDC_CLIENT_ID` | — (required without dummy auth) | Audience the tokens must carry (the UI's client) |
| `OIDC_JWKS_URL` | *(empty)* | Key set URL; without it the issuer's discovery document is asked on the first token |
| `ROLE_PROVIDER` | `http` | `http` (role-provider-service) or `mock` (development only) |
| `ROLE_PROVIDER_URL` / `ROLE_PROVIDER_API_TOKEN` | — (required for `http`) | role-provider-service base URL and a read token |
| `ROLE_PROVIDER_TIMEOUT_SECONDS` | `5` | Per-request timeout |
| `APPSTORE_ADMIN_GROUPS` | *(empty)* | Comma-separated tokens whose holders are AppStore admins, e.g. `group:appstore_admins` |
| `OPENSTACK_SIMULATE` | `false` | Development only: fake OpenStack for credentials, resource picker, quota and live servers |
| `API_ROOT_PATH` | *(empty)* | Prefix the API is reached under behind a stripping proxy, e.g. `/api/appstore`; only the docs page's links use it |
| `CORS_ORIGINS` | `["http://localhost:3000","http://localhost:5173"]` | JSON list of allowed origins |
| `TEMP_REPO_BASE_PATH` | `/tmp/worker_repos` | Scratch space for sparse clones when reading an app's variables |
| `APP_GIT_ALLOWED_HOSTS` | `github.com,gitlab.dhbw.cloud` | Comma-separated hosts apps may be registered and read from (public repositories, anonymous HTTPS; nested GitLab groups work) |
| `SMTP_ENABLED` | `false` | Switch for the notification mails (they never carry credentials) |
| `SMTP_HOST` / `SMTP_PORT` | *(empty)* / `587` | Relay; without a host no mail is sent. 465 means implicit TLS |
| `SMTP_STARTTLS` | `true` | Upgrade with STARTTLS on ports other than 465 |
| `SMTP_USER` / `SMTP_PASSWORD` | *(empty)* | Relay login, only if the relay needs one |
| `SMTP_FROM_EMAIL` / `SMTP_FROM_NAME` | *(empty, falls back to `SMTP_USER`)* / `DHBW AppStore` | Sender |
| `APPSTORE_UI_URL` | `http://localhost:5173` | Self-service UI base URL, no trailing slash; mails link to `/appstore/my-access` and `/appstore/deployments/<id>` |
| `DISABLE_BACKGROUND_TASKS` | *(unset)* | Tests only: don't start the task finalizer loop |

### Worker (`appstore_worker`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — (required) | The API's database; it is also the job queue |
| `CREDENTIAL_ENCRYPTION_KEY` | — (required) | Same key(s) as the API |
| `WORKER_CONCURRENCY` | `4` | Jobs run in parallel per worker process |
| `WORKER_POLL_INTERVAL_SECONDS` | `2` | How often an idle worker looks for tasks |
| `WORKER_LEASE_SECONDS` | `120` | A task whose lease is not renewed for this long is failed by the API |
| `APPSTORE_API_URL` | — (required) | The API as jobs reach it, e.g. `http://appstore-api:8000`; OpenTofu's state backend |
| `WORKER_JOB_TIMEOUT_SECONDS` | `7200` | A job running longer is stopped and fails |
| `WORKER_JOB_UID_BASE` | *(unset; image: `20000`)* | Slot *n* runs its tools as UID/GID base+*n*; needs the worker to run as root |
| `WORKER_JOB_HOME_BASE` | `/var/lib/appstore-worker` | Home directories of those users (plugin caches) |
| `TEMP_REPO_BASE_PATH` | `/tmp/worker_repos` | Job working directories |
| `APP_GIT_ALLOWED_HOSTS` | `github.com,gitlab.dhbw.cloud` | Same list as the API's, checked again before cloning |
| `TOFU_PATH` / `PACKER_PATH` | `/usr/local/bin/tofu` / `/usr/local/bin/packer` | Tool binaries |
| `WORKER_TF_LOG` | *(empty)* | Passed to OpenTofu as `TF_LOG` when set |
| `WORKER_SIMULATE` | `false` | Development only: play jobs through without Git or OpenStack (`simulate.py`) |
| `WORKER_SIMULATE_STEP_SECONDS` | `1.5` | Duration of each simulated phase |
| `WORKER_LOG_CONSOLE` | `1` | `0` silences job output on the worker's console |

## Releases

`VERSION` is the source of truth; `make bump V=x.y.z` sets it and the chart
version, `make version-check` fails CI when they disagree. Every push to `main`
builds both images; a version that is already in the registry is built but not
pushed again. A stable version (no `-test.N`) is tagged and released.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE).
