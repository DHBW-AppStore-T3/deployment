# ================================================================
# Makefile for Multi-Repo Deployment
# Manages frontend, backend, worker services
#
# Local dev runs via docker-compose.dev.yml (simulate mode, no
# OpenStack / Keycloak / cluster needed — .github#6).
#
# Production (docker-compose.prod.yml) is bootstrapped manually on
# the prod VM only; see docs/prod-setup.md.
# Staging is rolled out exclusively via the Ansible CD pipeline
# (infrastructure/ansible/), not from a developer laptop.
# ================================================================

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
DC_DEV  := docker compose -f docker-compose.dev.yml
DC_PROD := docker compose -f docker-compose.prod.yml

DC_RUNNER := docker compose -f docker-compose.prod.yml -f docker-compose.runner.yml

# Host-Ports (must match ${...:-default} values in compose files)
FRONTEND_PORT_DEV  ?= 5173
BACKEND_PORT       ?= 8000

.DEFAULT_GOAL := help

.PHONY: help \
        env secret \
        init dev dev-up dev-down dev-logs dev-build dev-rebuild dev-ps \
        dev-restart dev-restart-backend dev-restart-frontend dev-restart-worker \
        dev-logs-backend dev-logs-frontend dev-logs-worker \
        shell-backend shell-worker shell-frontend shell-db \
        seed-dev migrate-dev migration-create migration-history migration-current migration-downgrade \
        db-reset-dev \
        health status stats watch-dev top \
        clean-dev clean-all prune \
        test-backend test-backend-cov lint-backend lint-backend-fix format-backend \
        prod-up prod-down prod-stop prod-restart prod-pull prod-logs prod-ps \
        prod-migrate prod-seed prod-reset \
        runner-up runner-down runner-logs runner-ps \
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
env: ## Create .env from template
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ .env created from template — set CREDENTIAL_ENCRYPTION_KEY"; \
	else \
		echo ".env already exists"; \
	fi

secret: ## Generate a new Fernet key (for CREDENTIAL_ENCRYPTION_KEY)
	@python3 -c "from cryptography.fernet import Fernet; print('CREDENTIAL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())"

# ----------------------------------------------------------------
# Bootstrap
# ----------------------------------------------------------------
init: ## First start: env + up --build + migrate + seed
	@$(MAKE) --no-print-directory env
	$(DC_DEV) up -d --build
	@echo "Warte auf Postgres..."
	@$(DC_DEV) exec -T postgres sh -c 'until pg_isready -U postgres; do sleep 1; done'
	$(DC_DEV) exec -T backend poetry run alembic upgrade head
	$(DC_DEV) cp ./seed/seed_sim.py backend:/tmp/seed_sim.py
	$(DC_DEV) exec -T backend poetry run python /tmp/seed_sim.py
	@echo ""
	@echo "✓ Dev stack bereit."
	@echo "  Backend API Docs: http://localhost:$(BACKEND_PORT)/docs"
	@echo "  Frontend:         http://localhost:$(FRONTEND_PORT_DEV)"
	@echo ""
	@echo "  Auth: X-Dev-User Header — prof@dhbw.de / student@dhbw.de / admin@dhbw.de"

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
seed-dev: ## Re-run the dev seed (idempotent)
	$(DC_DEV) cp ./seed/seed_sim.py backend:/tmp/seed_sim.py
	$(DC_DEV) exec -T backend poetry run python /tmp/seed_sim.py

migrate-dev: ## Run Alembic migrations (dev)
	$(DC_DEV) exec -T backend poetry run alembic upgrade head

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
health: ## Check backend + frontend health
	@printf "  Backend:   "; curl -sf http://localhost:$(BACKEND_PORT)/health > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Frontend:  "; curl -sf http://localhost:$(FRONTEND_PORT_DEV) > /dev/null && echo "healthy" || echo "not healthy"

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
test-backend: ## Run backend pytest
	$(DC_DEV) exec backend pytest

test-backend-cov: ## Run backend pytest with HTML coverage
	$(DC_DEV) exec backend pytest --cov=. --cov-report=html

lint-backend: ## ruff check
	$(DC_DEV) exec backend ruff check .

lint-backend-fix: ## ruff check --fix
	$(DC_DEV) exec backend ruff check --fix .

format-backend: ## ruff format
	$(DC_DEV) exec backend ruff format .

# ----------------------------------------------------------------
# Production (manual VM bootstrap — see docs/prod-setup.md)
# ----------------------------------------------------------------
prod-up: ## Start the prod stack
	$(DC_PROD) up -d --pull always

prod-down: ## Stop and remove prod containers (volumes kept)
	$(DC_PROD) down

prod-stop: ## Stop prod containers without removing them
	$(DC_PROD) stop

prod-restart: ## Restart one prod service (usage: make prod-restart SVC=backend)
	@if [ -z "$(SVC)" ]; then echo "Usage: make prod-restart SVC=backend"; exit 1; fi
	$(DC_PROD) up -d --force-recreate $(SVC)

prod-pull: ## Re-pull all prod images and recreate changed containers
	$(DC_PROD) pull
	$(DC_PROD) up -d

prod-logs: ## Follow prod logs (or SVC=backend for one service)
	$(DC_PROD) logs -f $(SVC)

prod-ps: ## List prod containers + health
	$(DC_PROD) ps

prod-migrate: ## Apply Alembic migrations on the running prod backend
	docker exec backend-prod python -m alembic upgrade head

prod-seed: ## Seed DB on the running prod backend
	$(DC_PROD) cp ./seed/seed_sim.py backend:/tmp/seed_sim.py
	$(DC_PROD) exec -T backend python /tmp/seed_sim.py

prod-reset: ## ⚠️  Stop prod + DELETE all volumes. Irreversible.
	@echo "⚠️  This wipes ALL prod data."
	@read -p "Type 'yes' to continue: " -r REPLY; \
	if [ "$$REPLY" = "yes" ]; then \
		$(DC_PROD) down -v; \
		echo "✓ Prod stack and all volumes removed."; \
	else \
		echo "Aborted."; \
	fi

# ----------------------------------------------------------------
# Self-hosted GitHub Actions runner
# ----------------------------------------------------------------
runner-up: ## Start the self-hosted runner (needs GITHUB_ACCESS_TOKEN in .env)
	$(DC_RUNNER) up -d --pull always staging-runner

runner-down: ## Stop and remove the runner container
	$(DC_RUNNER) rm -sf staging-runner

runner-logs: ## Follow runner logs
	$(DC_RUNNER) logs -f staging-runner

runner-ps: ## Show runner container status
	$(DC_RUNNER) ps staging-runner

# ----------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------
up: dev-up ## Alias for dev-up
down: dev-down ## Alias for dev-down
logs: dev-logs ## Alias for dev-logs
build: dev-build ## Alias for dev-build
dev: init ## Alias for init
