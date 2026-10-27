# Deployment

Alles, was die Plattform zum Laufen braucht: Helm-Charts und Argo-CD-Anwendungen für Staging und Produktion sowie die lokale Entwicklung im `k3d`-Cluster (`k8s/`, `Makefile`).

Die Anwendung liegt in eigenen Repositories: `backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`. Hier werden ihre Images zusammengesetzt, konfiguriert und ausgerollt.

## Umgebungen

| Umgebung | Branch | Ausrollen |
|---|---|---|
| lokal | – | Kubernetes (`k3d-appstore-local`) mit denselben Helm-Charts via `make init` / `make dev-up` (`k8s/local/up.sh`) |
| Staging | `dev` | Kubernetes (k3s), Argo CD `staging-root` verfolgt `dev` |
| Produktion | `main` | Kubernetes (k3s), Argo CD `prod-root` verfolgt `main` |

Details zu Staging/Produktion: [k8s/README.md](k8s/README.md).

## Lokal starten

Komplette Anleitung: [docs/dev-setup.md](docs/dev-setup.md).

Kurzfassung:

```bash
cd deployment
make init       # Lokale Images bauen, k3d-Cluster starten & Helm-Charts ausrollen
make urls       # Alle Dev-URLs und Zugangsdaten auf einen Blick
make health     # AppStore, Self-Service-UI, Moodle, Keycloak und k3d-Cluster prüfen
```

AppStore <https://appstore.localhost> · Self-Service UI <https://self-service.localhost> · Moodle <https://moodle.localhost> · Keycloak <https://sso.localhost> · Login `admin.demo`, `dozent.demo`, `student1.demo`, `student2.demo` mit `DevLocal1234!`.

| Befehl | Wirkung |
|---|---|
| `make dev-up` / `make dev-down` | Lokalen k3d-Cluster + Helm-Charts starten / stoppen (Volumes bleiben) |
| `make dev-build` | Lokale Images neu bauen, in k3d importieren und Deployments neu starten |
| `make dev-logs-backend` (`-frontend`, `-worker`, `-keycloak`, `-moodle`) | Logs verfolgen |
| `make shell-backend` (`-worker`, `-db`) | Shell im Pod / `psql` |
| `make dev-restart` (`-backend`, `-worker`, `-frontend`, `-moodle`) | Deployments neu starten |
| `make migrate-dev` | Alembic-Migrationen im API-Pod anwenden |
| `make seed-dev` | Demo-Daten im API-Pod laden (idempotent) |
| `make trust-cert` | Lokale `*.localhost`-Root-CA im macOS-Schlüsselbund registrieren (passiert bei `make init` / `make dev-up` automatisch) |
| `make help` | alle Targets |

## Aufbau

```text
deployment/
├── Makefile                  lokaler Einstieg (k3d + Helm)
├── docs/dev-setup.md         lokales Kubernetes-Setup (k3d + Moodle)
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
