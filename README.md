# Deployment

Alles, was die Plattform zum Laufen braucht: Helm-Charts und Argo-CD-Anwendungen für Staging und Produktion (`k8s/`), der lokale Dev-Stack (`docker-compose.dev.yml`, `Makefile`), der Keycloak-Realm und die Seed-Daten.

Die Anwendung liegt in eigenen Repositories: `backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`. Hier werden ihre Images zusammengesetzt, konfiguriert und ausgerollt.

## Umgebungen

| Umgebung | Branch | Ausrollen |
|---|---|---|
| lokal | – | `docker-compose.dev.yml` per `make` (Postgres, Keycloak, Backend, Worker, Frontend; Kubernetes simuliert) |
| Staging | `dev` | Kubernetes (k3s), Argo CD `staging-root` verfolgt `dev` |
| Produktion | `main` | Kubernetes (k3s), Argo CD `prod-root` verfolgt `main` |

Details zu Staging/Produktion: [k8s/README.md](k8s/README.md).

## Lokal starten

Komplette Anleitung ab Null (Terminal, Git, Docker, make, Repos klonen, Fehlerbilder): [docs/dev-setup.md](docs/dev-setup.md).

Kurzfassung, wenn Git, make, Python 3 und Docker laufen:

```bash
mkdir appstore && cd appstore
for r in deployment backend worker frontend; do git clone -b dev https://github.com/DHBW-AppStore-T3/$r.git; done
cd deployment
make init       # .env anlegen, bauen, starten, migrieren, seeden
make health     # Backend, Frontend, Keycloak
```

Frontend http://localhost:5173 · API-Docs http://localhost:8000/docs · Keycloak http://localhost:8081 (`admin`/`admin`) · Login `dozent.demo`, `admin.demo`, `student1.demo` mit `DevLocal1234!`.

| Befehl | Wirkung |
|---|---|
| `make dev-up` / `make dev-down` | Stack starten / stoppen (Daten bleiben) |
| `make dev-logs-backend` (`-frontend`, `-worker`, `-keycloak`) | Logs verfolgen |
| `make shell-backend` (`-worker`, `-frontend`, `-db`) | Shell im Container / `psql` |
| `make dev-restart-worker` | Worker neu starten (kein Hot-Reload) |
| `make migrate-dev` | Migrationen anwenden |
| `make seed-dev` | Demo-Daten (idempotent) |
| `make help` | alle Targets |

## Aufbau

```text
deployment/
├── Makefile                  lokaler Einstieg
├── docker-compose.dev.yml    lokaler Stack
├── .env.example              Vorlage für .env (Schlüssel)
├── docs/dev-setup.md         lokales Setup ab Null
├── keycloak/dhbw-realm.json  Realm für den lokalen Keycloak (Staging/Prod: k8s/manifests/platform/files/dhbw-realm.json)
├── seed/seed_sim.py          Demo-Daten des lokalen Stacks (Staging: Job in charts/appstore)
├── k8s/                      Charts, Argo-CD-Anwendungen, Umgebungswerte, Image-Digests, Policy-Tests
│   ├── charts/{appstore,appstore-mcp,moodle}
│   ├── manifests/platform    Postgres (CloudNativePG) + Keycloak
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
