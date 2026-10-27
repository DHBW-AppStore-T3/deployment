# ================================================================
# Makefile for Multi-Repo Deployment (Kubernetes-First)
#
# Local development, staging, and production all run on Kubernetes
# using the same Helm charts:
#   - k8s/manifests/platform (PostgreSQL + Keycloak realm `dhbw`)
#   - k8s/charts/appstore    (API, Pod-Deployer, Frontend, Self-Service-UI,
#                             Migrate, Seed, RBAC, ValidatingAdmissionPolicy)
#   - k8s/charts/moodle      (Moodle LMS + LTI 1.3 integration)
#
# Locally, everything runs inside the k3d cluster `appstore-local`
# (namespace `appstore-local`) behind Traefik on `*.localhost`.
# ================================================================

K3D_CLUSTER ?= appstore-local
KUBE_CTX    := k3d-$(K3D_CLUSTER)
NS          ?= appstore-local
KUBE        := kubectl --context $(KUBE_CTX) -n $(NS)

.DEFAULT_GOAL := help

.PHONY: help \
        init dev dev-up dev-down dev-build dev-rebuild dev-ps \
        dev-restart dev-restart-backend dev-restart-frontend dev-restart-worker dev-restart-moodle \
        dev-logs dev-logs-backend dev-logs-frontend dev-logs-worker dev-logs-keycloak dev-logs-moodle \
        shell-backend shell-worker shell-db \
        seed-dev migrate-dev \
        health urls status trust-cert clean-dev clean-all clean \
        up down logs build

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-28s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Bootstrap (builds local images + deploys Helm charts into k3d): make init"

# ----------------------------------------------------------------
# Bootstrap & Lifecycle (Kubernetes in k3d)
# ----------------------------------------------------------------
init: ## Build all local images and deploy Platform + AppStore + Moodle into k3d
	./k8s/local/up.sh

dev-up: ## Start k3d cluster and apply Helm charts without rebuilding images
	SKIP_BUILD=1 ./k8s/local/up.sh

dev-build: ## Rebuild local images, import into k3d, and roll out
	./k8s/local/up.sh
	$(KUBE) rollout restart deployment/appstore-t3-api deployment/appstore-t3-pod-deployer deployment/appstore-t3-frontend deployment/appstore-t3-self-service-ui deployment/moodle-web

dev-rebuild: dev-build ## Alias for dev-build

dev-down: ## Stop the local k3d cluster (preserves state)
	k3d cluster stop "$(K3D_CLUSTER)"

dev-restart: ## Restart all application deployments in k3d
	$(KUBE) rollout restart deployment/appstore-t3-api deployment/appstore-t3-pod-deployer deployment/appstore-t3-frontend deployment/appstore-t3-self-service-ui deployment/moodle-web

dev-restart-backend: ## Restart API deployment in k3d
	$(KUBE) rollout restart deployment/appstore-t3-api

dev-restart-frontend: ## Restart Frontend deployment in k3d
	$(KUBE) rollout restart deployment/appstore-t3-frontend

dev-restart-worker: ## Restart Pod-Deployer deployment in k3d
	$(KUBE) rollout restart deployment/appstore-t3-pod-deployer

dev-restart-moodle: ## Restart Moodle web deployment in k3d
	$(KUBE) rollout restart deployment/moodle-web

dev-ps: ## List all pods, services, and ingresses in appstore-local
	$(KUBE) get pods,svc,ingress

# ----------------------------------------------------------------
# Logs & Shell Access
# ----------------------------------------------------------------
dev-logs: ## Follow logs of API and Pod-Deployer
	$(KUBE) logs -f -l app.kubernetes.io/part-of=appstore --all-containers=true --max-log-requests=10

dev-logs-backend: ## Follow API logs
	$(KUBE) logs -f deployment/appstore-t3-api

dev-logs-worker: ## Follow Pod-Deployer logs
	$(KUBE) logs -f deployment/appstore-t3-pod-deployer

dev-logs-frontend: ## Follow Frontend logs
	$(KUBE) logs -f deployment/appstore-t3-frontend

dev-logs-keycloak: ## Follow Keycloak logs
	$(KUBE) logs -f deployment/keycloak

dev-logs-moodle: ## Follow Moodle web logs
	$(KUBE) logs -f deployment/moodle-web

shell-backend: ## sh in API pod
	$(KUBE) exec -it deployment/appstore-t3-api -- sh

shell-worker: ## sh in Pod-Deployer pod
	$(KUBE) exec -it deployment/appstore-t3-pod-deployer -- sh

shell-db: ## psql in CloudNativePG primary pod (appstore_t3 database)
	$(KUBE) exec -it svc/postgres-cluster-rw -- psql -U postgres -d appstore_t3

# ----------------------------------------------------------------
# Seed & Migrations
# ----------------------------------------------------------------
seed-dev: ## Re-run the AppStore seed inside the API pod
	$(KUBE) exec deployment/appstore-t3-api -- python -m app.cli seed

migrate-dev: ## Run Alembic migrations inside the API pod
	$(KUBE) exec deployment/appstore-t3-api -- alembic upgrade head

# ----------------------------------------------------------------
# Health & Cleanup
# ----------------------------------------------------------------
health: ## Check HTTPS health of AppStore, Self-Service UI, Moodle, Keycloak, and k3d
	@printf "  AppStore API:    "; curl -skf --resolve appstore.localhost:443:127.0.0.1 https://appstore.localhost/api/health > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  AppStore UI:     "; curl -skf --resolve appstore.localhost:443:127.0.0.1 https://appstore.localhost/ > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Self-Service UI: "; curl -skf --resolve self-service.localhost:443:127.0.0.1 https://self-service.localhost/ping > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Moodle LMS:      "; curl -skf --resolve moodle.localhost:443:127.0.0.1 https://moodle.localhost/login/index.php > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Keycloak SSO:    "; curl -skf --resolve sso.localhost:443:127.0.0.1 https://sso.localhost/realms/dhbw/.well-known/openid-configuration > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  K8s Cluster:     "; kubectl --context "$(KUBE_CTX)" get nodes > /dev/null 2>&1 && echo "healthy" || echo "not healthy"

urls: ## Show all local HTTPS URLs and demo credentials
	@echo "  AppStore UI:      https://appstore.localhost"
	@echo "  Self-Service UI:  https://self-service.localhost"
	@echo "  Moodle LMS:       https://moodle.localhost"
	@echo "  Keycloak SSO:     https://sso.localhost"
	@echo "  Demo Users:       admin.demo, dozent.demo, student1.demo, student2.demo (Moodle Site-Admin: admin)"
	@echo "  Demo Password:    $${DEV_DEMO_PASSWORD:-DevLocal1234!}"

status: dev-ps ## Alias for dev-ps

trust-cert: ## Trust the local *.localhost Root CA in macOS Keychain (avoids browser TLS warnings)
	security add-trusted-cert -r trustRoot -k ~/Library/Keychains/login.keychain-db k8s/local/.certs/local-ca.crt

clean-dev: ## ⚠️  Delete the local k3d cluster completely (wipes all K8s volumes/state)
	docker rm -f "k3d-$(K3D_CLUSTER)-ingress" >/dev/null 2>&1 || true
	k3d cluster delete "$(K3D_CLUSTER)"

clean-all: clean-dev ## ⚠️  Delete k3d cluster AND wipe all local Docker/Podman images & build cache
	docker rmi -f \
		ghcr.io/dhbw-appstore-t3/backend:dev \
		ghcr.io/dhbw-appstore-t3/worker-pods:dev \
		ghcr.io/dhbw-appstore-t3/frontend:dev \
		ghcr.io/dhbw-appstore-t3/self-service-ui:dev \
		ghcr.io/dhbw-appstore-t3/moodle_appstore:dev >/dev/null 2>&1 || true
	docker builder prune -af >/dev/null 2>&1 || true
	docker image prune -af >/dev/null 2>&1 || true

clean: clean-dev ## Alias for clean-dev

# ----------------------------------------------------------------
# Aliases
# ----------------------------------------------------------------
up: dev-up ## Alias for dev-up
down: dev-down ## Alias for dev-down
logs: dev-logs ## Alias for dev-logs
build: dev-build ## Alias for dev-build
dev: init ## Alias for init
