# Handover — Deployment

Lebendes Übergabedokument (Harness-Konzept: [HARNESS.md](https://github.com/DHBW-AppStore-T3/.github/blob/main/docs/HARNESS.md)). Beschreibt den Ist-Zustand von `dev`; Stand wird mit jeder Änderung angepasst.

## 1. Zustand

- **Plattform:** k3s-Cluster im OpenStack-Projekt `ma_wwi_24sea_appstore_g3` (ein Node, nur IPv6/VPN), Argo CD, CloudNativePG (Datenbanken `appstore_t3`, `keycloak`, `moodle`), Keycloak (Realms `dhbw`, `appstore`), Traefik, cert-manager mit Wildcard-Zertifikat `*.<zone>`.
- **Umgebungen:** Staging = Branch `dev` (Namespace `appstore-staging`), Produktion = Branch `main` (Namespace `appstore-prod`). Beide Umgebungen teilen den Node. Aufbau, Komponenten, Rechte, Netzwerk-Policies, Admission-Policy: [k8s/README.md](../k8s/README.md).
- **Komponenten je Umgebung** (`k8s/charts/appstore`): `api`, `pod-deployer`, `frontend`, `self-service-ui`, `migrate` (Hook), `orphans` (stündlich), optional `clamav`, `seed` (nur Staging). Dazu `appstore-mcp` und `moodle` als eigene Anwendungen.
- **Images:** `ghcr.io/dhbw-appstore-t3/…`, Digests in `k8s/images/{staging,prod}.yaml` (Schlüssel `backend`, `workerPods`, `frontend`, `appstoreMcp`, `selfServiceUi`, `moodle`); geschrieben ausschließlich von `k8s-bump.yml`.
- **App-Runtimes:** `kubernetes` (Pods) und `kubevirt-vm` (Windows-Desktop als KubeVirt-VM, Golden Image im Namespace `vm-poc`, Speicher Cinder) laufen über den `pod-deployer`. Den OpenStack-VM-Pfad (`vm-executor`) gibt es nicht mehr.
- **Lokaler Stack:** Lokaler `k3d`-Kubernetes-Cluster (`k3d-appstore-local`, Namespace `appstore-local`) mit denselben Helm-Charts (`k8s/local/up.sh` + `Makefile`, Anleitung `docs/dev-setup.md`).
- **MCP für Agenten:** `appstore-mcp` (nur lesend), Skill `/verify-staging`.

## 2. Abläufe

- **Image ausrollen:** Push auf `dev` oder `main` in backend/worker/frontend/self-service-ui/appstore-mcp/moodle_appstore → deren CI baut, scannt, pusht und startet `k8s-bump.yml` mit dem Digest → Digest-Datei der Umgebung → Argo CD.
- **Chart, Policy, Realm ändern:** PR auf `dev` (Staging), danach `k8s/promote.sh` (PR `dev` → `main`).
- **Rollback eines Images:** Digest in `k8s/images/<env>.yaml` zurücksetzen (Commit auf `dev` bzw. PR auf `main`). Alles andere: Commit zurücknehmen.
- **Neue Umgebung / neue Secret-Schlüssel:** `GHCR_PULL_TOKEN_FILE=<datei> k8s/bootstrap.sh staging|prod` (rotiert nichts, ergänzt Fehlendes). Zugangsdaten: `k8s/show-credentials.sh <env>`.
- **Prüfen:** `kubectl -n argocd get applications | grep <env>`.

## 3. CI (`.github/workflows/`)

`k8s-bump.yml`, `k8s-chart.yml` (Render, Schemas, Admission-Policy-Auswertung, kind-Cluster für RBAC), `novnc-proxy.yml`, `secret-scan.yml` (Gitleaks). `dev` nimmt Änderungen nur über Pull Requests an.

## 4. Regeln

1. Keine Secrets im Repository; `bootstrap.sh` legt alle Secrets im Cluster an.
2. Ein bestehender Keycloak-Realm wird nicht neu importiert. Änderungen an `dhbw-realm.json` gelten nur für neue Realms; für laufende Realms Admin-Konsole oder `k8s/keycloak-self-service-client.sh`. Der Login-Theme-Eintrag wird nach jedem Sync gesetzt.
3. App-Hosts liegen eine Ebene unter der Zone (`<workload>-<deployment>.<zone>`), weil das Wildcard-Zertifikat nur `*.<zone>` deckt.
4. Der Cluster ist IPv6-primär: Server im Container binden `::`.
5. Pod-, Service- und Node-Netze stehen in `podApps.extraEgressExcept`, damit Student-Pods sie nicht erreichen.
6. Neue Rechte des Pod-Deployers gehören in dessen ClusterRole und in die Admission-Policy (`k8s/charts/appstore/templates/admission-policy*.yaml`), Fälle in `k8s/tests/policy/make_cases.py`.
7. Der Pod-Deployer darf VirtualMachineInstances nur lesen, nicht anlegen oder löschen.
8. `.claude/hooks/appstore-prod-guardrail.py` blockiert zustandsändernde Docker-Aufrufe über SSH auf den stillgelegten Host `appstore-prod-01`.

## 5. Offen

- Backups des CNPG-Clusters, der Student-Volumes, des Moodle-Datenverzeichnisses und der Moodle-Datenbank.
- Eigene Nodes für Student-Pods (`podApps.studentNodeSelector`, `studentTolerations`).
- Image-Signaturen (cosign), vollständiger End-to-End-Job in kind, Netzwerk-Policy-Prüfung in CI (kind erzwingt sie nicht; Prüfung auf Staging).
- Moodle: SMTP-Einstellungen.
- Produktion: `selfServiceUi.enabled: false`, bis der Client `appstore-self-service` im laufenden Realm existiert.
- [x] **KubeVirt-VM-Pfad (Windows-Matlab v2.1.0, 2026-10-25):** läuft auf Staging (`dep-01d72eac`, bleibt als Test stehen). Chart: Rolle `vnc-proxy`, Admission-Policy für ServiceAccount `vnc-proxy` und `ReferenceGrant`s (`admission-policy-clone-grants.yaml`, Testfälle in `k8s/tests/policy/make_cases.py`), Wert `podApps.vmImageNamespaces`. Proxy: `docker/novnc-proxy` (aiohttp, VNC über die Subresource `virtualmachineinstances/vnc`, Basic-Auth, IPv4+IPv6). Cluster-Seite: `scripts/enable-cross-namespace-clone.sh` (k3s-Feature-Gate + CSI-Provisioner; nach `helm upgrade` von cinder-csi erneut ausführen). **Nur eine Windows-VM gleichzeitig** (Cinder-Quota 256 GB, Golden 90 + VM 90).
- [ ] **E2E-Kette auf Staging (`e2e/`, `.github/workflows/e2e-staging.yml`, PR #158):** Playwright, Pod-App und VM-App: Admin legt an/reicht ein/genehmigt, Dozent deployt, API/Live-Ansicht/Link geprüft, Aufräumen auch nach Fehlern (`sweepStale` entfernt `e2e-*`-Reste). Lokal: `E2E_CHANNEL=chrome E2E_ADMIN_PASSWORD=… E2E_DOZENT_PASSWORD=… E2E_VM=0 npx playwright test`. **Offen:** erster vollständiger Lauf (Selektoren ab `deploys`-Schritt ungeprüft), Repo-Secrets `E2E_ADMIN_PASSWORD`/`E2E_DOZENT_PASSWORD` setzen, VM-Kette erst aktivieren wenn kein Hand-Deployment die Windows-Quota hält.
- Bekannte Falle: parallele Backend-Builds überschreiben sich in `k8s/images/staging.yaml` (langsamerer älterer Lauf setzt den Digest zurück) — `gh run rerun` des neuesten Laufs behebt es.
