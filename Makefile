# ================================================================
# Makefile for Multi-Repo Deployment
# Manages frontend, backend, worker, keycloak, postgres services
#
# Local dev runs via docker-compose.dev.yml (simulate mode for
# Kubernetes, local Keycloak on :8081 — .github#6).
#
# Staging and production run on Kubernetes (k8s/, rolled out by
# Argo CD).
# ================================================================

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
DC_DEV := docker compose -f docker-compose.dev.yml

# Host-Ports (must match ${...:-default} values in docker-compose.dev.yml)
FRONTEND_PORT_DEV ?= 5173
BACKEND_PORT      ?= 8000
KEYCLOAK_PORT     ?= 8081

.DEFAULT_GOAL := help

.PHONY: help \
        env secret \
        init dev dev-up dev-down dev-logs dev-build dev-rebuild dev-ps \
        dev-restart dev-restart-backend dev-restart-frontend dev-restart-worker \
        dev-logs-backend dev-logs-frontend dev-logs-worker dev-logs-keycloak \
        shell-backend shell-worker shell-frontend shell-db \
        seed-dev migrate-dev migration-create migration-history migration-current migration-downgrade \
        db-reset-dev \
        health status stats watch-dev top \
        clean-dev clean-all prune \
        test-backend test-backend-cov lint-backend lint-backend-fix format-backend \
        up down logs build

# ----------------------------------------------------------------
# Help
# ----------------------------------------------------------------
help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Bootstrap: make init"

# ----------------------------------------------------------------
# Environment Setup
# ----------------------------------------------------------------
env: ## Create .env from template (auto-generates CREDENTIAL_ENCRYPTION_KEY if empty)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		KEY=$$(python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"); \
		python3 -c "from pathlib import Path; p = Path('.env'); p.write_text(p.read_text().replace('CREDENTIAL_ENCRYPTION_KEY=\n', f'CREDENTIAL_ENCRYPTION_KEY={\"$$KEY\"}\n', 1))"; \
		echo "✓ .env created from template (CREDENTIAL_ENCRYPTION_KEY auto-generated)"; \
	else \
		echo ".env already exists"; \
	fi

secret: ## Generate a new Fernet key (for CREDENTIAL_ENCRYPTION_KEY)
	@python3 -c "import base64, os; print('CREDENTIAL_ENCRYPTION_KEY=' + base64.urlsafe_b64encode(os.urandom(32)).decode())"

# ----------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------
init: ## First start: env + up --build + migrate + seed
	@$(MAKE) --no-print-directory env
	$(DC_DEV) up -d --build
	@echo "Warte auf Postgres..."
	@$(DC_DEV) exec -T postgres sh -c 'until pg_isready -U postgres; do sleep 1; done'
	@$(MAKE) --no-print-directory migrate-dev
	@$(MAKE) --no-print-directory seed-dev
	@echo ""
	@echo "✓ Dev stack bereit."
	@echo "  Frontend:         http://localhost:$(FRONTEND_PORT_DEV)"
	@echo "  Backend API Docs: http://localhost:$(BACKEND_PORT)/docs"
	@echo "  Keycloak Admin:   http://localhost:$(KEYCLOAK_PORT)  (admin / admin)"
	@echo ""
	@echo "  Keycloak Logins:  dozent.demo / admin.demo / student1.demo (Passwort: DevLocal1234!)"
	@echo "  API Header-Auth:  X-Dev-User: prof@dhbw.de / student@dhbw.de / admin@dhbw.de"

# ----------------------------------------------------------------
# Development Environment
# ----------------------------------------------------------------
dev-up: ## Start dev stack (no rebuild/migrate/seed)
	$(DC_DEV) up -d

dev-down: ## Stop dev stack (keeps volumes)
	$(DC_DEV) down

dev-restart: ## Restart all dev containers
	$(DC_DEV) restart

dev-restart-backend: ## Restart backend only
	$(DC_DEV) restart backend

dev-restart-frontend: ## Restart frontend only
	$(DC_DEV) restart frontend

dev-restart-worker: ## Restart worker only
	$(DC_DEV) restart worker

dev-logs: ## Follow all dev logs
	$(DC_DEV) logs -f

dev-logs-backend: ## Follow backend logs
	$(DC_DEV) logs -f backend

dev-logs-frontend: ## Follow frontend logs
	$(DC_DEV) logs -f frontend

dev-logs-worker: ## Follow worker logs
	$(DC_DEV) logs -f worker

dev-logs-keycloak: ## Follow keycloak logs
	$(DC_DEV) logs -f keycloak

dev-build: ## Build all dev images
	$(DC_DEV) build

dev-rebuild: ## Rebuild from scratch and restart
	$(DC_DEV) down
	$(DC_DEV) build --no-cache
	$(DC_DEV) up -d

dev-ps: ## List dev containers
	$(DC_DEV) ps

# ----------------------------------------------------------------
# Shell Access
# ----------------------------------------------------------------
shell-backend: ## bash in backend container
	$(DC_DEV) exec backend bash

shell-worker: ## bash in worker container
	$(DC_DEV) exec worker bash

shell-frontend: ## sh in frontend container
	$(DC_DEV) exec frontend sh

shell-db: ## psql in dev Postgres
	$(DC_DEV) exec postgres psql -U postgres -d backend_dev

# ----------------------------------------------------------------
# Seed & Migrations
# ----------------------------------------------------------------
seed-dev: ## Re-run the dev seed (idempotent: Keycloak users + course + catalog apps)
	$(DC_DEV) cp ./seed/seed_sim.py backend:/tmp/seed_sim.py
	$(DC_DEV) exec -T backend poetry run python /tmp/seed_sim.py

migrate-dev: ## Run Alembic migrations (dev) and configure appstore_worker DB role
	$(DC_DEV) exec -T backend poetry run alembic upgrade head
	$(DC_DEV) exec -T backend poetry run python -m app.worker_db_role
	$(DC_DEV) restart worker

migration-create: ## Autogenerate migration (usage: make migration-create MSG="...")
	@if [ -z "$(MSG)" ]; then \
		echo "Usage: make migration-create MSG='your message'"; exit 1; \
	fi
	$(DC_DEV) exec backend poetry run alembic revision --autogenerate -m "$(MSG)"

migration-history: ## Show migration history
	$(DC_DEV) exec backend poetry run alembic history

migration-current: ## Show current revision
	$(DC_DEV) exec backend poetry run alembic current

migration-downgrade: ## Downgrade one revision
	$(DC_DEV) exec backend poetry run alembic downgrade -1

# ----------------------------------------------------------------
# Database Management
# ----------------------------------------------------------------
db-reset-dev: ## ⚠️  Wipe dev DB (DROPS ALL DATA, re-runs migrations)
	@echo "⚠️  This deletes all dev database data!"
	@read -p "Continue? [y/N] " -n 1 -r; echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(DC_DEV) down -v; \
		$(DC_DEV) up -d; \
		sleep 5; \
		$(MAKE) --no-print-directory migrate-dev; \
		echo "✓ Dev DB reset complete"; \
	fi

# ----------------------------------------------------------------
# Health & Status
# ----------------------------------------------------------------
health: ## Check backend + frontend + keycloak health
	@printf "  Backend:   "; curl -sf http://localhost:$(BACKEND_PORT)/health > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Frontend:  "; curl -sf http://localhost:$(FRONTEND_PORT_DEV) > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Keycloak:  "; curl -sf http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/.well-known/openid-configuration > /dev/null && echo "healthy" || echo "not healthy"

status: ## Show container status
	$(DC_DEV) ps

stats: ## docker stats (all containers)
	docker stats

watch-dev: ## Watch dev container status every 2s
	watch -n 2 '$(DC_DEV) ps'

top: ## Show top processes per dev container
	$(DC_DEV) top

# ----------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------
clean-dev: ## ⚠️  down -v on dev (removes ALL volumes)
	$(DC_DEV) down -v

clean-all: ## ⚠️  down -v + remove local images
	$(DC_DEV) down -v --rmi local

prune: ## ⚠️  docker system prune -af --volumes
	docker system prune -af --volumes

# ----------------------------------------------------------------
# Testing & Quality (Backend)
# ----------------------------------------------------------------
# Own database `backend_test` and the environment of CI (the container's own
# environment breaks the settings tests; the tests TRUNCATE their database).
# test_migrations sets the password of the cluster-wide role appstore_worker: the
# targets restore the dev login afterwards, or the dev worker cannot connect.
BACKEND_TEST_ENV := env -i HOME=/root PATH=/root/.local/bin:/usr/local/bin:/usr/bin:/bin \
	DATABASE_URL=postgresql://postgres:postgres@postgres:5432/backend_test \
	CREDENTIAL_ENCRYPTION_KEY=Q1PNlFd4It9oQPtjCcXcmB7wGDkY4w8KwpIRNSF4u7U= DISABLE_BACKGROUND_TASKS=1

test-backend: ## Run backend pytest (unit + integration) against its own database backend_test
	@$(DC_DEV) exec -T postgres psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='backend_test'" | grep -q 1 \
		|| $(DC_DEV) exec -T postgres psql -U postgres -c "CREATE DATABASE backend_test"
	$(DC_DEV) exec -T backend $(BACKEND_TEST_ENV) poetry run pytest -m "unit or integration" -q --no-cov; rc=$$?; \
		$(DC_DEV) exec -T backend poetry run python -m app.worker_db_role; exit $$rc

test-backend-cov: ## Run backend pytest with HTML coverage (htmlcov/ in backend/)
	@$(DC_DEV) exec -T postgres psql -U postgres -tc "SELECT 1 FROM pg_database WHERE datname='backend_test'" | grep -q 1 \
		|| $(DC_DEV) exec -T postgres psql -U postgres -c "CREATE DATABASE backend_test"
	$(DC_DEV) exec -T backend $(BACKEND_TEST_ENV) poetry run pytest -m "unit or integration" -q --cov=. --cov-report=html; rc=$$?; \
		$(DC_DEV) exec -T backend poetry run python -m app.worker_db_role; exit $$rc

lint-backend: ## ruff check
	$(DC_DEV) exec backend poetry run ruff check .

lint-backend-fix: ## ruff check --fix
	$(DC_DEV) exec backend poetry run ruff check --fix .

format-backend: ## ruff format
	$(DC_DEV) exec backend poetry run ruff format .

# ----------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------
up: dev-up ## Alias for dev-up
down: dev-down ## Alias for dev-down
logs: dev-logs ## Alias for dev-logs
build: dev-build ## Alias for dev-build
dev: init ## Alias for init
