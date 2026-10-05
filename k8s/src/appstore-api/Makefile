PROJECT_NAME := appstore-api
DOCKER_REPO  ?= ghcr.io/pfisterer
DOCKER_TAG   ?= $(shell cat VERSION)

# The tests need a Postgres of their own: they TRUNCATE every table between
# tests. `make test-db` starts a throwaway one on this port.
TEST_DB_PORT      ?= 55433
TEST_DB_CONTAINER ?= appstore-test-pg
TEST_DATABASE_URL ?= postgresql://test:test@localhost:$(TEST_DB_PORT)/test
MIGRATIONS_CHECK_URL := $(patsubst %/test,%/migrations_check,$(TEST_DATABASE_URL))
# A fresh Fernet key per make run: the tests need one, and a fixed key in the
# repository would be a committed secret for the scanners (and a habit).
TEST_FERNET_KEY   := $(shell python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")

TEST_ENV := DATABASE_URL=$(TEST_DATABASE_URL) TEST_DATABASE_URL=$(TEST_DATABASE_URL) \
	CREDENTIAL_ENCRYPTION_KEY=$(TEST_FERNET_KEY) DISABLE_BACKGROUND_TASKS=1 \
	APPSTORE_API_URL=http://appstore-api.invalid API_MODE=development ROLE_PROVIDER=mock \
	OIDC_ISSUER_URL=https://idp.invalid/realms/test OIDC_CLIENT_ID=appstore-test

.DEFAULT_GOAL := help

# `make dev`: a database of its own that survives restarts, the API on the
# port next to the other services' (8082–8085), everything simulated.
DEV_DB_PORT       ?= 55432
DEV_DB_CONTAINER  ?= appstore-dev-pg
DEV_PORT          ?= 8086
DEV_UI_URL        ?= http://localhost:8084
DEV_KEY_FILE      := .dev-fernet-key
DEV_ENV = DATABASE_URL=postgresql://dev:dev@localhost:$(DEV_DB_PORT)/appstore \
	CREDENTIAL_ENCRYPTION_KEY=$$(cat $(CURDIR)/$(DEV_KEY_FILE)) \
	API_MODE=development API_DUMMY_AUTH=true ROLE_PROVIDER=mock OPENSTACK_SIMULATE=true WORKER_SIMULATE=true \
	APPSTORE_ADMIN_GROUPS=group:root_uni APPSTORE_API_URL=http://localhost:$(DEV_PORT) \
	APPSTORE_UI_URL=$(DEV_UI_URL) CORS_ORIGINS='["$(DEV_UI_URL)","http://localhost:5173"]' \
	WORKER_CONCURRENCY=2 TEMP_REPO_BASE_PATH=/tmp/appstore-dev-repos

NPM_PKG_NAME   := @dhbw-cloud/appstore-client
OPENAPI_JSON   := openapi.json
CLIENT_DIR     := build/client-typescript
CLIENT_PKG_DIR := client-npm

.PHONY: help build bundle test test-shared test-backend test-worker test-db test-db-down \
	lint typecheck migrations-check audit check image image-api image-worker bump version-check \
	openapi openapi-check install-npm client npm-package npm-pack npm-publish \
	dev dev-db dev-db-down dev-api dev-worker chart-check

help:
	@echo "Usage: make <target>"
	@echo "  build             → install the workspace (uv sync, incl. dev tools)"
	@echo "  test              → all tests; needs a test database (make test-db)"
	@echo "  test-shared|test-backend|test-worker → one package's tests (PYTEST_ARGS narrows)"
	@echo "  test-db           → start a throwaway Postgres on port $(TEST_DB_PORT)"
	@echo "  test-db-down      → stop it"
	@echo "  lint              → ruff"
	@echo "  typecheck         → mypy"
	@echo "  migrations-check  → the migrations produce exactly the models' schema"
	@echo "  audit             → pip-audit against the lockfile"
	@echo "  check             → lint + typecheck + test + migrations-check + openapi-check (what CI runs)"
	@echo "  dev               → API on :$(DEV_PORT) (reload) + simulated worker + Postgres, with example data"
	@echo "  dev-api|dev-worker → only one of the two (each starts the dev Postgres)"
	@echo "  dev-db-down       → remove the dev Postgres container (and its data)"
	@echo "  openapi           → write openapi.json from the code (commit it)"
	@echo "  openapi-check     → fail if openapi.json is not what the code describes"
	@echo "  client            → generate the TS client from openapi.json into $(CLIENT_DIR)/"
	@echo "  npm-package       → build $(NPM_PKG_NAME) from openapi.json into $(CLIENT_PKG_DIR)/"
	@echo "  npm-publish       → publish it (prerelease → dist-tag next)"
	@echo "  bundle            → write build-time files (VERSION into the API package)"
	@echo "  image             → build both images"
	@echo "  bump V=x.y.z      → set VERSION and the chart version"
	@echo "  version-check     → fail if VERSION and Chart.yaml disagree"
	@echo "  chart-check       → helm lint + render with and without an existingSecret"

build:
	uv sync --frozen

# VERSION is the single source of truth; the API reports it on /health. Copied
# rather than read from the repository root, because an installed package has
# no repository root.
bundle:
	@cp VERSION backend/appstore_api/VERSION
	@echo "✅ VERSION $$(cat VERSION) bundled"

# ── Tests ───────────────────────────────────────────────────────────────────
# Per package: each has its own tests/ and conftest, and pytest would clash
# on three packages all called "tests" in one run.
test: test-shared test-backend test-worker

# PYTEST_ARGS narrows a run, e.g. make test-backend PYTEST_ARGS="tests/test_auth.py -k dummy"
test-shared:
	cd shared && uv run pytest -q $(PYTEST_ARGS)

test-backend:
	cd backend && $(TEST_ENV) uv run pytest -q $(PYTEST_ARGS)

test-worker:
	cd worker && $(TEST_ENV) uv run pytest -q $(PYTEST_ARGS)

test-db:
	@docker start $(TEST_DB_CONTAINER) >/dev/null 2>&1 || \
	docker run -d --rm --name $(TEST_DB_CONTAINER) \
		-e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -e POSTGRES_DB=test \
		-p $(TEST_DB_PORT):5432 postgres:16-alpine >/dev/null
	@until docker exec $(TEST_DB_CONTAINER) pg_isready -U test -q; do sleep 1; done
	@echo "✅ test database on $(TEST_DATABASE_URL)"

test-db-down:
	-docker stop $(TEST_DB_CONTAINER)

# ── Static checks ───────────────────────────────────────────────────────────
lint:
	uv run ruff check .

typecheck:
	uv run mypy shared/appstore_shared backend/appstore_api worker/appstore_worker

# The original project lost indexes to an autogenerated migration because
# they existed only in migrations. This fails when models and migrations
# disagree in either direction. Runs against a scratch database so it never
# touches the one the tests use.
migrations-check:
	cd backend && $(TEST_ENV) uv run python -c "import sqlalchemy as sa; \
		e = sa.create_engine('$(TEST_DATABASE_URL)', isolation_level='AUTOCOMMIT'); \
		c = e.connect(); c.exec_driver_sql('DROP DATABASE IF EXISTS migrations_check'); \
		c.exec_driver_sql('CREATE DATABASE migrations_check')"
	cd backend && $(TEST_ENV) DATABASE_URL=$(MIGRATIONS_CHECK_URL) \
		sh -c 'uv run alembic upgrade head && uv run alembic check && uv run alembic downgrade base && uv run alembic upgrade head'

# The runtime dependencies as locked, not whatever happens to be installed.
audit:
	uv export --frozen --no-dev --no-emit-workspace --no-hashes --quiet | uv run pip-audit --strict -r /dev/stdin

check: lint typecheck test migrations-check openapi-check

# ── Local development ──────────────────────────────────────────────────────
# No cloud, no identity provider, no role provider: callers name themselves
# with X-Dummy-Auth-User, the role-provider mock knows the course wwi23seb,
# OpenStack and the worker's jobs are simulated (OPENSTACK_SIMULATE,
# WORKER_SIMULATE). The dev key is kept in a file so encrypted rows survive a
# restart; it protects nothing but example data.
$(DEV_KEY_FILE):
	@python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" > $@

dev-db:
	@docker start $(DEV_DB_CONTAINER) >/dev/null 2>&1 || \
	docker run -d --name $(DEV_DB_CONTAINER) \
		-e POSTGRES_USER=dev -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=appstore \
		-p $(DEV_DB_PORT):5432 postgres:16-alpine >/dev/null
	@until docker exec $(DEV_DB_CONTAINER) pg_isready -U dev -q; do sleep 1; done

dev-db-down:
	-docker rm -f $(DEV_DB_CONTAINER)

dev-api: dev-db $(DEV_KEY_FILE) bundle
	cd backend && $(DEV_ENV) uv run alembic upgrade head
	cd backend && $(DEV_ENV) uv run python -m appstore_api.dev_seed
	cd backend && $(DEV_ENV) uv run uvicorn appstore_api.main:app --reload --port $(DEV_PORT)

dev-worker: dev-db $(DEV_KEY_FILE)
	cd worker && $(DEV_ENV) uv run python -m appstore_worker

# Both in one terminal; Ctrl-C stops both.
dev: dev-db $(DEV_KEY_FILE)
	@trap 'kill 0' INT TERM EXIT; \
	$(MAKE) --no-print-directory dev-api & \
	sleep 8; $(MAKE) --no-print-directory dev-worker & \
	wait

# ── API contract and TypeScript client ─────────────────────────────────────
# openapi.json is committed: the UI's client is generated from it, and a
# change to the API shows up in review as a change to this file. The
# description carries the version, so `make bump` rewrites it too.
openapi: bundle
	@cd backend && $(TEST_ENV) uv run python -m appstore_api.openapi > ../$(OPENAPI_JSON).tmp
	@mv $(OPENAPI_JSON).tmp $(OPENAPI_JSON)
	@echo "✅ $(OPENAPI_JSON) written"

openapi-check: bundle
	@cd backend && $(TEST_ENV) uv run python -m appstore_api.openapi > ../$(OPENAPI_JSON).tmp
	@diff -u $(OPENAPI_JSON) $(OPENAPI_JSON).tmp > /dev/null || { \
		diff -u $(OPENAPI_JSON) $(OPENAPI_JSON).tmp | head -40; rm -f $(OPENAPI_JSON).tmp; \
		echo "✗ $(OPENAPI_JSON) does not match the code: run 'make openapi' and commit it"; exit 1; }
	@rm -f $(OPENAPI_JSON).tmp
	@echo "✅ $(OPENAPI_JSON) matches the code"

install-npm:
	@npm ci --silent

# Straight from the committed OpenAPI 3.1 description; no swagger2openapi step
# as in the Go services, FastAPI writes OpenAPI 3 itself.
client: install-npm
	@rm -rf $(CLIENT_DIR)
	@npx openapi-ts -i "$(OPENAPI_JSON)" -o "$(CLIENT_DIR)" -c @hey-api/client-fetch
	@echo "✅ TS client generated in $(CLIENT_DIR)"

# Same package layout as @dhbw-cloud/os-mgt-client, so the UI configures both
# the same way.
npm-package: client
	@rm -rf $(CLIENT_PKG_DIR)
	@mkdir -p $(CLIENT_PKG_DIR)/src
	@cp -R $(CLIENT_DIR)/. $(CLIENT_PKG_DIR)/src/
	@# The generated index.ts exports every operation and type, but not the
	@# client instance itself — and that is what the consumer configures.
	@printf '%s\n' \
		"export * from './index';" \
		"export { client } from './client.gen';" \
		> $(CLIENT_PKG_DIR)/src/entry.ts
	@VERSION=$$(cat VERSION | tr -d '\n'); printf '%s\n' \
		'{' \
		'  "name": "$(NPM_PKG_NAME)",' \
		"  \"version\": \"$$VERSION\"," \
		'  "description": "Generated TypeScript client for the DHBW Cloud $(PROJECT_NAME).",' \
		'  "license": "Apache-2.0",' \
		'  "type": "module",' \
		'  "exports": { ".": { "types": "./dist/entry.d.ts", "default": "./dist/index.mjs" } },' \
		'  "types": "./dist/entry.d.ts",' \
		'  "files": ["dist"],' \
		'  "publishConfig": { "access": "public" },' \
		'  "repository": { "type": "git", "url": "git+https://github.com/pfisterer/$(PROJECT_NAME).git" }' \
		'}' \
		> $(CLIENT_PKG_DIR)/package.json
	@# Bundled rather than compiled file-by-file: the generated sources import
	@# each other without file extensions, which plain Node does not accept.
	@npx esbuild $(CLIENT_PKG_DIR)/src/entry.ts --bundle --format=esm --log-level=warning \
		--outfile=$(CLIENT_PKG_DIR)/dist/index.mjs
	@npx tsc $(CLIENT_PKG_DIR)/src/entry.ts --declaration --emitDeclarationOnly \
		--outDir $(CLIENT_PKG_DIR)/dist --module esnext --moduleResolution bundler \
		--target es2022 --skipLibCheck
	@echo "✅ Package assembled in $(CLIENT_PKG_DIR)"

npm-pack: npm-package
	@cd $(CLIENT_PKG_DIR) && npm pack

# A prerelease goes to the `next` dist-tag, so a plain `npm install` never
# hands out a -test.N build. Deliberately not a CI step: publishing is rare
# and the login is interactive.
npm-publish: npm-package
	@npm whoami >/dev/null 2>&1 || npm login
	@VERSION=$$(cat VERSION | tr -d '\n'); \
	case "$$VERSION" in \
		*-*) TAG=next ;; \
		*)   TAG=latest ;; \
	esac; \
	echo "📤 Publishing $(NPM_PKG_NAME)@$$VERSION (dist-tag: $$TAG)"; \
	cd $(CLIENT_PKG_DIR) && npm publish --tag "$$TAG"

# ── Images ──────────────────────────────────────────────────────────────────
# Build context is the repository root for both, so they share the lockfile
# and the shared package.
image: image-api image-worker

image-api: bundle
	docker build -f backend/Dockerfile -t $(DOCKER_REPO)/appstore-api:$(DOCKER_TAG) .

image-worker:
	docker build -f worker/Dockerfile -t $(DOCKER_REPO)/appstore-worker:$(DOCKER_TAG) .

# ── Versioning ──────────────────────────────────────────────────────────────
# VERSION is the source of truth and Chart.yaml has to agree with it: once the
# chart is published, its version IS the artifact's identity. version-check
# fails rather than rewriting, so a forgotten bump is caught, not hidden.
bump:
	@test -n "$(V)" || { echo "usage: make bump V=<x.y.z>"; exit 1; }
	@printf '%s' "$(V)" > VERSION
	@sed -e "s/^version: .*/version: $(V)/" -e "s/^appVersion: .*/appVersion: \"$(V)\"/" \
		helm-chart/Chart.yaml > helm-chart/Chart.yaml.tmp && mv helm-chart/Chart.yaml.tmp helm-chart/Chart.yaml
	@$(MAKE) --no-print-directory openapi
	@echo "✅ VERSION, helm-chart/Chart.yaml and $(OPENAPI_JSON) set to $(V)"

# The schema (additionalProperties: false) is what catches a typo in the
# umbrella's values; rendering both Secret variants catches template errors.
chart-check:
	@helm lint helm-chart --set appstore.databaseUrl=postgresql://x --set appstore.credentialEncryptionKey=k >/dev/null
	@helm template t helm-chart --set appstore.databaseUrl=postgresql://x --set appstore.credentialEncryptionKey=k >/dev/null
	@helm template t helm-chart --set appstore.existingSecret=s --set appstore.simulate=true \
		--set appstore.api.mode=development >/dev/null
	@echo "✅ chart lints and renders"

version-check:
	@v=$$(cat VERSION | tr -d '\n'); \
	cv=$$(awk '/^version:/{print $$2}' helm-chart/Chart.yaml); \
	av=$$(awk '/^appVersion:/{gsub(/"/,"",$$2); print $$2}' helm-chart/Chart.yaml); \
	if [ "$$v" != "$$cv" ] || [ "$$v" != "$$av" ]; then \
		echo "✗ VERSION is $$v, Chart.yaml says version=$$cv appVersion=$$av"; \
		echo "  fix with: make bump V=$$v"; \
		exit 1; \
	fi; \
	echo "✅ version $$v is consistent"
