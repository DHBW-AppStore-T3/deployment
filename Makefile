# ================================================================
# Makefile for Multi-Repo Deployment
# Manages frontend, backend, worker services
#
# This Makefile drives the LOCAL development environment
# (docker-compose.dev.yml). Staging and prod run on Kubernetes
# (k8s/, rolled out by Argo CD).
# ================================================================
#
# Conventions:
# - All recipes that produce no file are listed in .PHONY below.
# - Compose-file paths live in $(DC_DEV) so we never
#   re-spell "docker-compose.dev.yml" in two recipes.
# - Help is generated from `## comments` on the target line — keep
#   them short, they are shown in the `make help` overview.
#
# Default goal is `help`, so a bare `make` is always safe.

# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------
DC_DEV  := docker compose -f docker-compose.dev.yml

# Host-Ports (müssen mit den ${...:-default} Werten in den compose-
# Dateien übereinstimmen, sonst zeigt `make urls` falsche Links).
FRONTEND_PORT_DEV  ?= 5173
BACKEND_PORT       ?= 8000
KEYCLOAK_PORT      ?= 8080
PGADMIN_PORT       ?= 5050

.DEFAULT_GOAL := help

.PHONY: help \
        env secret \
        init quickstart urls \
        dev-up dev-down dev-stop dev-restart dev-restart-backend dev-restart-frontend dev-restart-worker \
        dev-logs dev-logs-backend dev-logs-frontend dev-logs-worker dev-logs-keycloak \
        dev-build dev-build-backend dev-build-frontend dev-build-worker dev-rebuild dev-ps \
        shell-backend shell-worker shell-frontend \
        shell-db shell-keycloak shell-keycloak-db \
        keycloak-up keycloak-down keycloak-restart keycloak-logs keycloak-ps keycloak-reset keycloak-wait \
        keycloak-export keycloak-token keycloak-userinfo keycloak-url keycloak-disable-ssl \
        seed-data seed-reset \
        migrate-dev migration-create migration-history migration-current migration-downgrade \
        db-reset-dev \
        health status stats watch-dev top \
        clean-dev clean-all prune \
        test-backend test-backend-cov lint-backend lint-backend-fix format-backend \
        up down logs build

# ----------------------------------------------------------------
# Help
# ----------------------------------------------------------------
help: ## Show this help message
	@echo "🚀 Click-n-Deploy – Available Commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Services (dev): frontend, backend, worker, keycloak, postgres,"
	@echo "                postgres-test, postgres-tfstate, keycloak-postgres,"
	@echo "                pgadmin"
	@echo ""
	@echo "Bootstrap a fresh checkout:  make init"
	@echo "Show URLs:                   make urls"
	@echo ""

# ----------------------------------------------------------------
# Environment Setup
# ----------------------------------------------------------------
env: ## Create .env from template
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✓ .env file created from template"; \
		echo "⚠️  Please edit .env with your actual values"; \
	else \
		echo ".env file already exists"; \
	fi

secret: ## Generate a new secret key (prints SECRET_KEY=...)
	@python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"

# ----------------------------------------------------------------
# Bootstrap (Top-Level Helper)
# ----------------------------------------------------------------
# Bringt eine frische Arbeitskopie in einen lauffähigen Zustand.
# Reihenfolge: .env anlegen → Services hochfahren → DB-Schema
# applizieren → Beispiel-Daten einseeden. Wenn das .env-File schon
# existiert, lässt env es in Ruhe, also auch zum "auf den neuesten
# Stand bringen" verwendbar.
init: quickstart ## Alias for `quickstart`
quickstart: ## One-shot: env + dev-up + migrate-dev + seed-data
	@$(MAKE) --no-print-directory env
	@$(MAKE) --no-print-directory dev-up
	@echo "⏳ Warte 10s bis Backend/Postgres bereit sind..."
	@sleep 10
	@$(MAKE) --no-print-directory migrate-dev
	@$(MAKE) --no-print-directory seed-data
	@echo ""
	@echo "✓ Quickstart abgeschlossen."
	@$(MAKE) --no-print-directory urls

urls: ## Show all dev URLs in one place
	@echo "🌐 Dev URLs:"
	@echo ""
	@echo "  Frontend:           http://localhost:$(FRONTEND_PORT_DEV)"
	@echo "  Backend API:        http://localhost:$(BACKEND_PORT)"
	@echo "  Backend API Docs:   http://localhost:$(BACKEND_PORT)/docs"
	@echo "  Keycloak Admin:     http://localhost:$(KEYCLOAK_PORT)/admin   (admin / admin)"
	@echo "  Keycloak Realm:     http://localhost:$(KEYCLOAK_PORT)/realms/dhbw"
	@echo "  pgAdmin:            http://localhost:$(PGADMIN_PORT)            (admin@admin.com / admin)"
	@echo ""

# ----------------------------------------------------------------
# Development Environment
# ----------------------------------------------------------------
dev-up: ## Start development environment
	$(DC_DEV) up -d
	@echo ""
	@echo "✓ Development environment started"
	@$(MAKE) --no-print-directory urls

dev-down: ## Stop dev environment (keeps volumes)
	$(DC_DEV) down

dev-stop: ## Stop dev containers without removing them
	$(DC_DEV) stop

dev-restart: ## Restart dev environment
	$(DC_DEV) restart

dev-restart-backend: ## Restart backend only (e.g. after editing celery_app.py)
	$(DC_DEV) restart backend

dev-restart-frontend: ## Restart frontend only
	$(DC_DEV) restart frontend

dev-restart-worker: ## Restart worker only (after editing worker/app/tasks.py)
	$(DC_DEV) restart worker

dev-logs: ## Follow dev logs (all services)
	$(DC_DEV) logs -f

dev-logs-backend: ## Follow backend logs
	$(DC_DEV) logs -f backend

dev-logs-frontend: ## Follow frontend logs
	$(DC_DEV) logs -f frontend

dev-logs-worker: ## Follow worker logs
	$(DC_DEV) logs -f worker

dev-logs-keycloak: ## Follow Keycloak logs
	$(DC_DEV) logs -f keycloak

dev-build: ## Build all dev images
	$(DC_DEV) build

dev-build-backend: ## Build backend dev image only
	$(DC_DEV) build backend

dev-build-frontend: ## Build frontend dev image only
	$(DC_DEV) build frontend

dev-build-worker: ## Build worker dev image only
	$(DC_DEV) build worker

dev-rebuild: ## Rebuild from scratch and restart dev
	$(DC_DEV) down
	$(DC_DEV) build --no-cache
	$(DC_DEV) up -d

dev-ps: ## List dev containers
	$(DC_DEV) ps

# ----------------------------------------------------------------
# Shell Access
# ----------------------------------------------------------------
shell-backend: ## Open bash in backend container (dev)
	$(DC_DEV) exec backend bash

shell-worker: ## Open bash in worker container (dev)
	$(DC_DEV) exec worker bash

shell-frontend: ## Open sh in frontend container (dev)
	$(DC_DEV) exec frontend sh

shell-db: ## Open psql in dev Postgres (backend_dev)
	$(DC_DEV) exec postgres psql -U postgres -d backend_dev

shell-keycloak: ## Open bash in Keycloak container (dev)
	$(DC_DEV) exec keycloak bash

shell-keycloak-db: ## Open psql in Keycloak Postgres (dev)
	$(DC_DEV) exec keycloak-postgres psql -U keycloak -d keycloak

# ----------------------------------------------------------------
# Keycloak Management
# ----------------------------------------------------------------
keycloak-up: ## Start Keycloak + its Postgres only
	$(DC_DEV) up -d keycloak-postgres keycloak
	@echo "✓ Keycloak: http://localhost:$(KEYCLOAK_PORT)/admin   (admin / admin)"

keycloak-down: ## Stop Keycloak only
	$(DC_DEV) stop keycloak keycloak-postgres

keycloak-restart: ## Restart Keycloak only
	$(DC_DEV) restart keycloak

keycloak-logs: ## Follow Keycloak logs
	$(DC_DEV) logs -f keycloak

keycloak-ps: ## Show Keycloak container status
	$(DC_DEV) ps keycloak keycloak-postgres

keycloak-reset: ## ⚠️  Reset Keycloak (DROPS realm + users)
	@echo "⚠️  WARNING: This will delete all Keycloak data (realms, users, clients)!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(DC_DEV) stop keycloak keycloak-postgres; \
		$(DC_DEV) rm -f keycloak keycloak-postgres; \
		docker volume rm deployment_keycloak_postgres_data 2>/dev/null || true; \
		$(DC_DEV) up -d keycloak-postgres; \
		sleep 5; \
		$(DC_DEV) up -d keycloak; \
		$(MAKE) --no-print-directory keycloak-wait; \
		echo "✓ Keycloak reset complete"; \
		echo "  Login: admin / admin"; \
	fi

keycloak-wait: ## Block until Keycloak's HTTP listener answers (60s timeout)
	@# After a fresh `up -d keycloak`, the process boots Quarkus, imports
	@# the realm from data/import, and only THEN starts the HTTP listener.
	@# A subsequent `seed-data` racing against that startup explodes with
	@# `Connection refused` because nothing answers port 8080 yet.
	@#
	@# We can't use `curl -sf /realms/master/.well-known/openid-configuration`
	@# as the probe — Keycloak answers that endpoint with HTTP 403 by
	@# default (it's only available to authenticated callers), and curl
	@# -f treats 403 as a failure. The right signal is "any HTTP status
	@# came back", because that means the listener is bound. We probe
	@# /realms/master and accept anything that starts with a digit
	@# (2xx / 3xx / 4xx) — only a refused / hung connection produces
	@# an empty status code.
	@printf "⏳ Warte auf Keycloak (max 60s)"; \
	for i in $$(seq 1 60); do \
	  code=$$(curl -s -o /dev/null -w "%{http_code}" -m 2 "http://localhost:$(KEYCLOAK_PORT)/realms/master" 2>/dev/null); \
	  case "$$code" in \
	    [234]*) echo " ✓ ready (nach $${i}s, HTTP $$code)"; exit 0 ;; \
	  esac; \
	  printf "."; \
	  sleep 1; \
	done; \
	echo ""; \
	echo "❌ Keycloak antwortet nach 60s nicht — siehe \`make dev-logs-keycloak\`"; \
	exit 1

keycloak-export: ## Export the dhbw realm to keycloak/keycloak-export.json
	@echo "Exporting Keycloak realm 'dhbw'..."
	$(DC_DEV) exec keycloak /opt/keycloak/bin/kc.sh export --dir /tmp --realm dhbw
	$(DC_DEV) cp keycloak:/tmp/dhbw-realm.json ./keycloak/keycloak-export.json
	@echo "✓ Realm exported → keycloak/keycloak-export.json"

keycloak-disable-ssl: ## Allow plain-HTTP admin login on localhost (UPDATE realm SET ssl_required=NONE + restart)
	@echo "Disabling HTTPS requirement on the master realm..."
	$(DC_DEV) exec keycloak-postgres psql -U $${KEYCLOAK_DB_USER:-keycloak} -d $${KEYCLOAK_DB_NAME:-keycloak} \
		-c "UPDATE realm SET ssl_required = 'NONE' WHERE name = 'master';"
	@echo "Restarting Keycloak so it re-reads the realm settings..."
	$(DC_DEV) restart keycloak
	@echo "✓ master realm now accepts HTTP — Admin Console reachable at http://localhost:$(KEYCLOAK_PORT)/admin"

keycloak-token: ## Get a token (usage: make keycloak-token USER=luca.baeck PASS=1234)
	@curl -s -X POST http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/protocol/openid-connect/token \
		-H "Content-Type: application/x-www-form-urlencoded" \
		-d "client_id=appstore-frontend" \
		-d "username=$(USER)" \
		-d "password=$(PASS)" \
		-d "grant_type=password" | jq -r '.access_token' | head -c 50; echo "..."

keycloak-userinfo: ## Decode userinfo (usage: make keycloak-userinfo TOKEN=xxx)
	@curl -s http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/protocol/openid-connect/userinfo \
		-H "Authorization: Bearer $(TOKEN)" | jq

keycloak-url: ## Print Keycloak URLs
	@echo "🔐 Keycloak URLs:"
	@echo ""
	@echo "  Admin Console:   http://localhost:$(KEYCLOAK_PORT)/admin"
	@echo "  Realm dhbw:      http://localhost:$(KEYCLOAK_PORT)/realms/dhbw"
	@echo "  OIDC Config:     http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/.well-known/openid-configuration"
	@echo "  Token Endpoint:  http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/protocol/openid-connect/token"
	@echo "  User Info:       http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/protocol/openid-connect/userinfo"
	@echo ""

# ----------------------------------------------------------------
# Seed Data
# ----------------------------------------------------------------
# Lädt Profs/Studenten/Admin in Keycloak (Realm ``dhbw``) und Kurse,
# Apps + Approval-Records in die Backend-DB. Idempotent — beliebig oft
# wiederholbar; Passwörter werden bei jedem Lauf auf den Default
# zurückgesetzt. Standardpasswort: 1234. Login: <vorname>.<nachname>@dhbw.de
#
# Voraussetzung: ``make dev-up`` lief (Backend + Keycloak gesund).
seed-data: ## Seed Keycloak users + DB (courses, apps, approvals)
	@echo "📥 Kopiere Seed-Skript + Realm-Export in den Backend-Container..."
	$(DC_DEV) cp ./seed/seed_data.py backend:/tmp/seed_data.py
	$(DC_DEV) cp ./seed/app_descriptions backend:/tmp/app_descriptions
	$(DC_DEV) cp ./keycloak/realm-export.json backend:/tmp/realm-export.json
	@echo "🌱 Führe Seed aus..."
	$(DC_DEV) exec -T \
		-e KEYCLOAK_ADMIN_USER=$${KEYCLOAK_ADMIN_USER:-admin} \
		-e KEYCLOAK_ADMIN_PASSWORD=$${KEYCLOAK_ADMIN_PASSWORD:-admin} \
		-e REALM_EXPORT_PATH=/tmp/realm-export.json \
		backend poetry run python /tmp/seed_data.py

seed-reset: ## ⚠️  Reset DB + Keycloak realm, then seed
	@echo "⚠️  WARNING: This will reset the dev DB AND the Keycloak realm!"
	@read -p "Continue? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(MAKE) --no-print-directory db-reset-dev REPLY=y; \
		$(MAKE) --no-print-directory keycloak-reset REPLY=y; \
		$(MAKE) --no-print-directory seed-data; \
	fi

# ----------------------------------------------------------------
# Database Migrations
# ----------------------------------------------------------------
# Migrations on staging/prod run automatically in the backend chart.
migrate-dev: ## Run database migrations (dev), then give the worker's DB role its login
	$(DC_DEV) exec backend poetry run alembic upgrade head
	$(DC_DEV) exec backend poetry run python -m app.worker_db_role
	$(DC_DEV) restart worker

migration-create: ## Autogenerate migration (usage: make migration-create MSG="message")
	@if [ -z "$(MSG)" ]; then \
		echo "Error: Please provide a message. Usage: make migration-create MSG='Your message'"; \
		exit 1; \
	fi
	$(DC_DEV) exec backend poetry run alembic revision --autogenerate -m "$(MSG)"

migration-history: ## Show migration history (dev)
	$(DC_DEV) exec backend poetry run alembic history

migration-current: ## Show current migration (dev)
	$(DC_DEV) exec backend poetry run alembic current

migration-downgrade: ## Downgrade by one revision (dev)
	$(DC_DEV) exec backend poetry run alembic downgrade -1

# ----------------------------------------------------------------
# Database Management
# ----------------------------------------------------------------
db-reset-dev: ## ⚠️  Wipe + re-create dev DB (DROPS ALL DATA, runs migrations)
	@echo "⚠️  WARNING: This will delete all development database data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		$(DC_DEV) down -v; \
		$(DC_DEV) up -d; \
		sleep 8; \
		$(MAKE) --no-print-directory migrate-dev; \
		echo "✓ Development database reset complete"; \
	fi

# ----------------------------------------------------------------
# Health & Status
# ----------------------------------------------------------------
health: ## Check service health (dev)
	@echo "🏥 Checking service health..."
	@echo ""
	@printf "  Backend:   "; curl -sf http://localhost:$(BACKEND_PORT)/health > /dev/null && echo "✓ healthy" || echo "❌ not healthy"
	@printf "  Frontend:  "; curl -sf http://localhost:$(FRONTEND_PORT_DEV) > /dev/null && echo "✓ healthy" || echo "❌ not healthy"
	@printf "  Keycloak:  "; curl -sf http://localhost:$(KEYCLOAK_PORT)/realms/dhbw/.well-known/openid-configuration > /dev/null && echo "✓ healthy" || echo "❌ not healthy"
	@echo ""

status: ## Show container status (dev)
	$(DC_DEV) ps

# ----------------------------------------------------------------
# Monitoring
# ----------------------------------------------------------------
stats: ## docker stats (all containers)
	docker stats

watch-dev: ## Watch dev container status every 2s
	watch -n 2 '$(DC_DEV) ps'

top: ## Show top processes per dev container
	$(DC_DEV) top

# ----------------------------------------------------------------
# Cleanup
# ----------------------------------------------------------------
clean-dev: ## ⚠️  down -v on dev (removes ALL volumes/data)
	$(DC_DEV) down -v
	@echo "✓ Development cleanup complete"

clean-all: ## ⚠️  Wipe dev (DROPS ALL DATA)
	$(DC_DEV) down -v --rmi local
	@echo "✓ Complete cleanup done"

prune: ## ⚠️  docker system prune -af --volumes (system-wide)
	docker system prune -af --volumes
	@echo "✓ Docker system pruned"

# ----------------------------------------------------------------
# Testing & Quality (Backend)
# ----------------------------------------------------------------
test-backend: ## Run backend pytest
	$(DC_DEV) exec backend pytest

test-backend-cov: ## Run backend pytest with HTML coverage
	$(DC_DEV) exec backend pytest --cov=. --cov-report=html

lint-backend: ## Run backend linter (ruff check)
	$(DC_DEV) exec backend ruff check .

lint-backend-fix: ## ruff check --fix
	$(DC_DEV) exec backend ruff check --fix .

format-backend: ## ruff format
	$(DC_DEV) exec backend ruff format .

# ----------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------
up: dev-up ## Alias for dev-up
down: dev-down ## Alias for dev-down
logs: dev-logs ## Alias for dev-logs
build: dev-build ## Alias for dev-build
