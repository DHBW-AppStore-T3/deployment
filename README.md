# Deployment

Helm-Charts, Argo-CD-Anwendungen, Umgebungswerte und Image-Digests für Staging und Produktion (`k8s/`) sowie das lokale `k3d`-Setup (`Makefile`, `k8s/local/up.sh`).

Die Anwendung besteht aus sechs Repositories: `backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`. Hier werden ihre Images referenziert, konfiguriert und ausgerollt.

## Umgebungen

| Umgebung | Branch | Namespace | Ausrollen | Dokumentation |
|---|---|---|---|---|
| Produktion | `main` | `appstore-prod` | Kubernetes (`k3s`), Argo CD `prod-root` verfolgt `main` | [k8s/README.md](k8s/README.md) |
| Staging | `dev` | `appstore-staging` | Kubernetes (`k3s`), Argo CD `staging-root` verfolgt `dev` | [k8s/README.md](k8s/README.md) |
| Lokal | – | `appstore-local` | Kubernetes (`k3d-appstore-local`) per `make init` (`k8s/local/up.sh`) | [docs/dev-setup.md](docs/dev-setup.md) |

## Aufbau

```text
deployment/
├── Makefile                  Befehle für den lokalen k3d-Cluster
├── docs/dev-setup.md         Anleitung für das lokale Setup
├── k8s/                      Charts, Argo-CD-Anwendungen, Umgebungswerte, Image-Digests, Policy-Tests
│   ├── README.md             Staging & Produktion (k3s, Argo CD, RBAC, Network- & Admission-Policies)
│   ├── charts/{appstore,appstore-mcp,moodle}
│   ├── manifests/platform    Postgres (CloudNativePG) + Keycloak
│   ├── local/up.sh           Rollt CNPG, platform, appstore und moodle lokal in k3d aus
│   ├── argocd/               Cluster-Operator, App-of-Apps, Roots je Umgebung
│   ├── environments/         staging.yaml, prod.yaml
│   ├── images/               Image-Digests (nur von CI geschrieben)
│   ├── cinder/               StorageClass für Cinder-Volumes
│   ├── tests/                Chart-Render, Admission-Policy-Tests, RBAC-Probes
│   └── bootstrap.sh, promote.sh, show-credentials.sh, keycloak-self-service-client.sh
├── scripts/                  KubeVirt-Windows-Apps: install-cinder-csi.sh, migrate-golden-image.sh, enable-cross-namespace-clone.sh
├── docker/novnc-proxy/       noVNC-Proxy-Image für KubeVirt-VMs
├── examples/                 Beispiel-appstore.yaml einer Windows-VM (kubevirt-vm)
├── e2e/                      Playwright-Tests gegen Staging
└── .github/workflows/        k8s-bump, k8s-chart, image-provenance, novnc-proxy, e2e-staging, secret-scan
```

## CI

| Workflow | Auslöser | Aufgabe |
|---|---|---|
| `k8s-bump.yml` | von `backend`/`worker`/`frontend`/`self-service-ui`/`appstore-mcp`/`moodle_appstore` nach Image-Push | schreibt den Digest in `k8s/images/<staging\|prod>.yaml`: `dev` per sofort gemergtem PR, `main` per PR |
| `k8s-chart.yml` | Änderungen in `k8s/**` | rendert Staging und Prod wie Argo CD, prüft gegen Kubernetes-Schemas, wertet die Admission-Policy aus, prüft RBAC in `kind` |
| `image-provenance.yml` | PRs mit Änderungen an `k8s/images/*.yaml` | prüft die CI-Herkunftssignatur gepinnter Images |
| `novnc-proxy.yml` | Änderungen in `docker/novnc-proxy/**` | baut, testet, scannt und pusht das Proxy-Image |
| `e2e-staging.yml` | `workflow_dispatch` | Playwright-E2E-Lauf gegen Staging |
| `secret-scan.yml` | PRs und Pushes auf `main`/`dev` | Gitleaks |

Promotion von Charts/Policy/Realm nach Produktion: `k8s/promote.sh` (PR `dev` → `main`).
