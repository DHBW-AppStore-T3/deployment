# appstore-api — notes for Claude Code

Read `README.md` first ("Why" and "Development"). This file lists the rules that
are easy to get wrong.

## Commands

- `make build` once, `make test-db` before backend tests, `make check` before
  every commit (lint + typecheck + tests + migrations-check). Single tests with the right
  environment: `make test-backend PYTEST_ARGS="tests/test_auth.py -k dummy"`
  (likewise `test-worker`, `test-shared`).
- Never run `ruff format` over the repository: the imported code is not
  formatter-clean and would turn every commit into noise. `make lint` runs
  `ruff check` only; `ruff check --fix` on the files you touched is fine.
- Never add a dependency with pip. `uv add --package appstore-api <pkg>` (or
  `appstore-worker` / `appstore-shared`), then commit `uv.lock` with it.

## Conventions

- Comments explain *why*, not what. Match the density of the surrounding code.
- Configuration only through environment variables (pydantic settings in each
  package's `config.py`); document every new one in the README table.
- Rights come from tokens, never from a stored role: `user.is_admin` and
  `user.is_dozent` are set per request by `auth.py`. Every rule lives in
  `utils/capabilities.py` (`require_*` dependencies, `can_*`/`ensure_*`
  helpers); routers never compare tokens or owner ids themselves. Admins read
  and review, they do not operate other people's deployments.
- Code used by both the API and the worker goes into `shared/`, not into two copies.
- Models live in `shared/appstore_shared/models.py` (typed `Mapped[...]`), because
  the worker writes to the same tables. Indexes and constraints are declared
  there; `make migrations-check` fails when models and migrations disagree.
  Before the first release, change migration `0001` in place (regenerate it)
  instead of adding new ones.
- Tests: `tests/roles.py` gives `Role.STUDENT/DOZENT/ADMIN`, `make_user`,
  `stub_user`. No real secrets in tests — generate keys (`Fernet.generate_key()`).
- Commits: `area: lowercase imperative summary` (e.g. `auth: accept oidc bearer
  tokens`), no co-author trailers.

## Not yet done (see the workspace plan)

Check the plan's progress section before building on a part of the AppStore
that is still listed as open there.

## Jobs

- App code is untrusted. Every tool the worker starts goes through
  `job_context` (minimal env, slot user, deadline): use `_stream_subprocess` /
  `_run_buffered` from `terraform_executor.py`, never a bare `subprocess.run`
  with `os.environ`.
- OpenTofu state lives in the API (`terraform_states`, `/internal/tfstate`);
  read it with `services/tf_state_store.read`, don't copy it onto task rows.
