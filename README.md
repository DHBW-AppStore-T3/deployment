# Deployment

Alles, was die Plattform zum Laufen braucht: Helm-Charts und Argo-CD-Anwendungen für Staging und Produktion sowie die lokale Entwicklung im `k3d`-Kubernetes-Cluster (`k8s/`, `Makefile`).

Die Anwendung liegt in eigenen Repositories: `backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`. Hier werden ihre Images zusammengesetzt, konfiguriert und ausgerollt.

## Umgebungen

| Umgebung | Branch | Ausrollen |
|---|---|---|
| lokal | – | Kubernetes (`k3d-appstore-local`, Namespace `appstore-local`) mit denselben produktiven Helm-Charts via `make init` / `make dev-up` (`k8s/local/up.sh`) |
| Staging | `dev` | Kubernetes (k3s), Argo CD `staging-root` verfolgt `dev` |
| Produktion | `main` | Kubernetes (k3s), Argo CD `prod-root` verfolgt `main` |

Details zu Staging/Produktion: [k8s/README.md](k8s/README.md).

## Lokal starten (Kubernetes via k3d)

Die komplette Plattform (CloudNativePG PostgreSQL, Keycloak mit `dhbw`-Realm, AppStore API + Pod-Deployer + Frontend + Self-Service-UI sowie Moodle LMS inkl. LTI 1.3) lässt sich unter **macOS**, **Windows (WSL2)** und **Linux** lokal in einem `k3d`-Cluster bereitstellen. Komplette Anleitung: [docs/dev-setup.md](docs/dev-setup.md).

### Voraussetzungen & Abhängigkeiten

| Abhängigkeit | Zweck | Hinweise (macOS & Windows / WSL2) |
|---|---|---|
| **Docker Desktop** *oder* **Podman** | Container-Engine für Image-Builds & `k3d`-Nodes | Mind. **4 CPUs** und **6–8 GiB RAM**. Bei Podman muss der `docker`-CLI-Alias aktiv sein (`podman-docker` / Podman Desktop Docker-Kompatibilität). Unter Windows WSL2-Integration aktivieren. |
| **`k3d`** | Erstellt den lokalen k3s-Cluster `k3d-appstore-local` | Bindet Ports `80` und `443` an den Traefik-Ingress-Controller |
| **`kubectl`** | Kubernetes-CLI für Rollouts, Logs, Exec & Secrets | Nutzt automatisch den Kontext `k3d-appstore-local` |
| **`helm`** (v3) | Rollt CloudNativePG, `platform`, `appstore` und `moodle` aus | Verwendet exakt die produktiven Charts unter `k8s/` |
| **`openssl`** & **`python3`** | Lokale `*.localhost`-Root-CA + TLS-Zertifikate & Secret-Generierung | Werden von `k8s/local/up.sh` beim Bootstrap genutzt |
| **`git`**, **`make`**, **`curl`** | Repo-Hash-Prüfung, `Makefile`-Targets & `make health` | Unter Windows über **WSL2 (Ubuntu)** ausführen |

Installation der CLI-Abhängigkeiten:
- **macOS (Homebrew):** `brew install k3d kubectl helm openssl python3 git make curl`
- **Windows (in WSL2 Ubuntu):** `sudo apt-get update && sudo apt-get install -y git make curl openssl python3` sowie `k3d`, `kubectl` und `helm` (z. B. via Homebrew on Linux oder offizielle Installer — siehe [docs/dev-setup.md](docs/dev-setup.md)).

### Schnellstart

Alle Teil-Repositories (`backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `deployment`) müssen als Geschwister-Ordner im selben Oberverzeichnis liegen:

```bash
cd deployment
make init       # Lokale Images bauen, k3d-Cluster starten & Helm-Charts ausrollen
make urls       # Alle Dev-URLs und Zugangsdaten auf einen Blick
make health     # AppStore, Self-Service-UI, Moodle, Keycloak und k3d-Cluster prüfen
```

AppStore <https://appstore.localhost> · Self-Service UI <https://self-service.localhost> · Moodle <https://moodle.localhost> · Keycloak <https://sso.localhost> · Login `admin.demo`, `dozent.demo`, `student1.demo`, `student2.demo` mit `DevLocal1234!`.

| Befehl | Wirkung |
|---|---|
| `make init` (`make dev`) | Baut lokale Images, erstellt `k3d-appstore-local` und rollt alle Helm-Charts aus |
| `make dev-up` / `make dev-down` | Lokalen k3d-Cluster + Helm-Charts starten (ohne Image-Rebuild) / stoppen (Volumes bleiben) |
| `make dev-build` (`make dev-rebuild`) | Lokale Images neu bauen, in k3d importieren und Deployments neu starten |
| `make dev-ps` (`make status`) | Zeigt alle Pods, Services und Ingresses im Namespace `appstore-local` |
| `make dev-logs` | Live-Logs aller AppStore-Pods (`api`, `pod-deployer`, `frontend`, `self-service-ui`) |
| `make dev-logs-backend` (`-frontend`, `-self-service`, `-worker`, `-keycloak`, `-moodle`) | Logs eines einzelnen Dienstes verfolgen |
| `make shell-backend` (`-worker`, `-frontend`, `-moodle`, `-db`) | Interaktive Shell im jeweiligen Pod bzw. `psql` in CloudNativePG |
| `make dev-restart` (`-backend`, `-worker`, `-frontend`, `-self-service`, `-moodle`) | Deployments neu starten |
| `make migrate-dev` | Alembic-Migrationen im API-Pod anwenden |
| `make seed-dev` | Demo-Daten aus der `appstore-t3-seed`-ConfigMap im API-Pod laden (idempotent) |
| `make trust-cert` | Lokale `*.localhost`-Root-CA im Betriebssystem registrieren (macOS Keychain / Windows Root-Store / Linux CA-Store; passiert bei `make init` & `make dev-up` automatisch) |
| `make clean-dev` / `make clean-all` | Löscht den lokalen k3d-Cluster (bzw. zusätzlich alle lokalen `:dev`-Images & Build-Caches) |
| `make help` | Zeigt alle verfügbaren `Makefile`-Targets |

## Aufbau

```text
deployment/
├── Makefile                  lokaler Einstieg (k3d + Helm)
├── docs/dev-setup.md         lokales Kubernetes-Setup (k3d + Moodle für macOS & Windows/WSL2)
├── k8s/                      Charts, Argo-CD-Anwendungen, Umgebungswerte, Image-Digests, Policy-Tests
│   ├── charts/{appstore,appstore-mcp,moodle}
│   ├── manifests/platform    Postgres (CloudNativePG) + Keycloak (Realm dhbw + DHBW-Theme)
│   ├── local/up.sh           rollt CNPG + platform + appstore + moodle in k3d aus
│   ├── argocd/               Cluster-Operator, App-of-Apps, Roots je Umgebung
│   ├── environments/         staging.yaml, prod.yaml
│   ├── images/               Image-Digests (nur von CI geschrieben)
│   └── bootstrap.sh, promote.sh, show-credentials.sh, keycloak-self-service-client.sh
├── scripts/                  KubeVirt-Windows-Apps: install-cinder-csi.sh, migrate-golden-image.sh, enable-cross-namespace-clone.sh
├── docker/novnc-proxy/       noVNC-Proxy-Image für KubeVirt-VMs
├── examples/                 Beispiel-appstore.yaml einer Windows-VM (kubevirt-vm)
└── .github/workflows/        k8s-bump, k8s-chart, novnc-proxy, secret-scan
```

## CI

| Workflow | Auslöser | Aufgabe |
|---|---|---|
| `k8s-bump.yml` | von backend/worker/frontend/self-service-ui/appstore-mcp/moodle_appstore nach deren Image-Push | schreibt den Digest in `k8s/images/<staging\|prod>.yaml`: Branch `dev` per sofort gemergtem PR, `main` per PR zum Prüfen |
| `k8s-chart.yml` | Änderungen in `k8s/**` | rendert Staging und Prod wie Argo CD, prüft gegen Kubernetes-Schemas, wertet die Admission-Policy aus, prüft RBAC in einem kind-Cluster |
| `novnc-proxy.yml` | Änderungen in `docker/novnc-proxy/**` | baut und pusht das Proxy-Image |
| `secret-scan.yml` | PRs und Pushes auf `main`/`dev` | Gitleaks |

Promotion von Charts/Policy/Realm nach Produktion: `k8s/promote.sh` (PR `dev` → `main`).
