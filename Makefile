# ================================================================
# Makefile – Lokales Kubernetes-Setup (k3d + Helm)
# ================================================================

K3D_CLUSTER ?= appstore-local
KUBE_CTX    := k3d-$(K3D_CLUSTER)
NS          ?= appstore-local
KUBE        := kubectl --context $(KUBE_CTX) -n $(NS)
SERVICE     ?= appstore-t3-api

.DEFAULT_GOAL := help

.PHONY: help init up down build status logs shell restart seed migrate health clean

help: ## Zeigt alle Befehle
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

init: ## Lokale Images bauen, k3d-Cluster starten & Helm-Charts ausrollen
	./k8s/local/up.sh

up: ## k3d-Cluster starten & Helm-Charts anwenden (ohne Image-Rebuild)
	SKIP_BUILD=1 ./k8s/local/up.sh

down: ## k3d-Cluster stoppen (Zustand bleibt erhalten)
	k3d cluster stop "$(K3D_CLUSTER)"

build: ## Lokale Images neu bauen, in k3d importieren & Deployments neu starten
	@if $(KUBE) get deployment appstore-t3-api >/dev/null 2>&1; then \
		BUILD_ONLY=1 ./k8s/local/up.sh && \
		$(KUBE) rollout restart deployment/appstore-t3-api deployment/appstore-t3-pod-deployer deployment/appstore-t3-frontend deployment/appstore-t3-self-service-ui deployment/moodle-web; \
	else \
		./k8s/local/up.sh; \
	fi

status: ## Pods, Services & Ingresses in appstore-local anzeigen
	$(KUBE) get pods,svc,ingress

logs: ## Live-Logs (optional: make logs SERVICE=moodle-web)
	@if [ "$(SERVICE)" = "all" ]; then \
		$(KUBE) logs -f -l app.kubernetes.io/part-of=appstore-t3 --all-containers=true --max-log-requests=10; \
	else \
		$(KUBE) logs -f deployment/$(SERVICE) --all-containers=true; \
	fi

shell: ## Shell im Pod öffnen (optional: make shell SERVICE=moodle-web, oder SERVICE=db für psql)
	@if [ "$(SERVICE)" = "db" ]; then \
		$(KUBE) exec -it svc/postgres-cluster-rw -- psql -U postgres -d appstore_t3; \
	else \
		$(KUBE) exec -it deployment/$(SERVICE) -- sh; \
	fi

restart: ## Alle Deployments im Cluster neu starten
	$(KUBE) rollout restart deployment/appstore-t3-api deployment/appstore-t3-pod-deployer deployment/appstore-t3-frontend deployment/appstore-t3-self-service-ui deployment/moodle-web

seed: ## Seed-Daten erneut in die Datenbank laden
	$(KUBE) get cm appstore-t3-seed -o jsonpath='{.data.seed\.json}' | $(KUBE) exec -i deployment/appstore-t3-api -- python -m app.cli seed --config /dev/stdin

migrate: ## Alembic-Migrationen im API-Pod ausführen
	$(KUBE) exec deployment/appstore-t3-api -- python -m alembic upgrade head

health: ## Prüft Erreichbarkeit von AppStore, Self-Service UI, Moodle, Keycloak & Cluster
	@printf "  AppStore API:    "; curl -skf --resolve appstore.localhost:443:127.0.0.1 https://appstore.localhost/api/health > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  AppStore UI:     "; curl -skf --resolve appstore.localhost:443:127.0.0.1 https://appstore.localhost/ > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Self-Service UI: "; curl -skf --resolve self-service.localhost:443:127.0.0.1 https://self-service.localhost/ping > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Moodle LMS:      "; curl -skf --resolve moodle.localhost:443:127.0.0.1 https://moodle.localhost/login/index.php > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  Keycloak SSO:    "; curl -skf --resolve sso.localhost:443:127.0.0.1 https://sso.localhost/realms/dhbw/.well-known/openid-configuration > /dev/null && echo "healthy" || echo "not healthy"
	@printf "  K8s Cluster:     "; kubectl --context "$(KUBE_CTX)" get nodes > /dev/null 2>&1 && echo "healthy" || echo "not healthy"

clean: ## ⚠️  Lokalen k3d-Cluster komplett löschen
	docker rm -f "k3d-$(K3D_CLUSTER)-ingress" >/dev/null 2>&1 || true
	k3d cluster delete "$(K3D_CLUSTER)"

