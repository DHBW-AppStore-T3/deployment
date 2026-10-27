# Deployment

Zentrales Deployment-Repository der DHBW-AppStore-Plattform: Helm-Charts, Argo-CD-Anwendungen, Umgebungs- und Image-Konfigurationen für Staging und Produktion sowie das lokale Kubernetes-Entwicklungssetup (`k3d`).

Die Komponenten liegen in sechs eigenständigen Repositories (`backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`). Hier werden ihre Images referenziert, konfiguriert und auf Kubernetes ausgerollt.

## Umgebungen

| Umgebung | Branch | Namespace | Ausrollen | Dokumentation |
|---|---|---|---|---|
| **Produktion** | `main` | `appstore-prod` | Kubernetes (`k3s` auf OpenStack), Argo CD `prod-root` verfolgt `main` | [k8s/README.md](k8s/README.md) |
| **Staging** | `dev` | `appstore-staging` | Kubernetes (`k3s` auf OpenStack), Argo CD `staging-root` verfolgt `dev` | [k8s/README.md](k8s/README.md) |
| **Lokal** | – | `appstore-local` | Lokales Kubernetes (`k3d-appstore-local`) mit denselben Helm-Charts via `make init` | [docs/dev-setup.md](docs/dev-setup.md) |

## Aufbau

```text
deployment/
├── k8s/                      Helm-Charts, Argo-CD-Anwendungen, Umgebungswerte, Image-Digests, Policy-Tests
│   ├── README.md             Architektur & Betrieb von Staging und Produktion (k3s, Argo CD, RBAC, Policies)
│   ├── charts/               Helm-Charts: appstore, appstore-mcp, moodle
│   ├── manifests/platform/   Postgres (CloudNativePG) + Keycloak + Realm & Theme
│   ├── argocd/               Cluster-Operator (CNPG), App-of-Apps, Roots je Umgebung
│   ├── environments/         Umgebungswerte: staging.yaml, prod.yaml
│   ├── images/               Gepinnte Image-Digests: staging.yaml, prod.yaml (nur von CI geschrieben)
│   ├── cinder/               Cinder-CSI StorageClass für persistente Volumes & KubeVirt-VMs
│   ├── tests/                Chart-Rendering, Admission-Policy-Tests (CEL) & RBAC-Cluster-Probes
│   ├── local/up.sh           Rollt CNPG, Platform, AppStore und Moodle lokal in k3d aus
│   └── bootstrap.sh, promote.sh, show-credentials.sh, keycloak-self-service-client.sh
├── docs/dev-setup.md         Schritt-für-Schritt-Anleitung für das lokale Setup (ab Null inkl. git clone)
├── Makefile                  Steuerung des lokalen k3d-Entwicklungs-Clusters
├── scripts/                  KubeVirt-Windows-Apps: install-cinder-csi.sh, migrate-golden-image.sh, enable-cross-namespace-clone.sh
├── docker/novnc-proxy/       noVNC-Proxy-Image für KubeVirt-VMs
├── examples/                 Beispiel-appstore.yaml einer Windows-VM (kubevirt-vm)
├── e2e/                      Playwright End-to-End-Tests gegen Staging
└── .github/workflows/        CI/CD-Pipelines (k8s-bump, k8s-chart, image-provenance, novnc-proxy, e2e-staging, secret-scan)
```

## Dokumentation & Einstiegspunkte

- **Staging & Produktion (k3s / Argo CD / Architektur / Betrieb):** [k8s/README.md](k8s/README.md)
  - Neue Umgebung initialisieren: `GHCR_PULL_TOKEN_FILE=<datei> k8s/bootstrap.sh staging|prod`
  - Zugangsdaten anzeigen: `k8s/show-credentials.sh staging|prod`
  - Charts/Policies von Staging (`dev`) nach Produktion (`main`) promoten: `k8s/promote.sh`
- **Lokale Entwicklung (von Null zum laufenden Stack):** [docs/dev-setup.md](docs/dev-setup.md)
  - Kurzstart (sofern alle 6 Repos geklont und Docker, `k3d`, `kubectl`, `helm` installiert sind): `make init` (Übersicht aller lokalen Befehle: `make help`)
- **Übergabedokument & Architekturentscheidungen (ADRs):** [claude_docs/HANDOVER.md](claude_docs/HANDOVER.md) · `claude_docs/decisions/`

## CI / CD Workflows

| Workflow | Auslöser | Aufgabe |
|---|---|---|
| `k8s-bump.yml` | Nach erfolgreichem Image-Push von `backend`, `worker`, `frontend`, `self-service-ui`, `appstore-mcp`, `moodle_appstore` | Prüft die Image-Provenance (Signatur) und schreibt den neuen Digest in `k8s/images/<staging\|prod>.yaml` (`dev`: automatischer Merge, `main`: Pull Request zur Freigabe) |
| `k8s-chart.yml` | Änderungen in `k8s/**` | Rendert Staging und Prod wie Argo CD, validiert gegen Kubernetes-Schemas (`kubeconform`), prüft die Admission-Policy (CEL) und testet RBAC in einem `kind`-Cluster |
| `image-provenance.yml` | PRs mit Änderungen an `k8s/images/*.yaml` | Verifiziert per GitHub Attestation, dass gepinnte Images aus der offiziellen Komponenten-CI stammen |
| `novnc-proxy.yml` | Änderungen in `docker/novnc-proxy/**` | Baut, testet, scannt (Trivy) und pusht das noVNC-Proxy-Image für KubeVirt-VMs |
| `e2e-staging.yml` | Manuell (`workflow_dispatch`) | Führt die komplette Playwright-E2E-Kette (Pod-App & KubeVirt-VM) auf Staging aus |
| `secret-scan.yml` | PRs und Pushes auf `main`/`dev` | Prüft das Repository mit Gitleaks auf versehentlich committete Geheimnisse |
