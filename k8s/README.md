# Prod- & Staging-Setup

Staging und Produktion laufen auf dem `k3s`-Cluster des OpenStack-Projekts `ma_wwi_24sea_appstore_g3` und werden per Argo CD aus diesem Repository ausgerollt.

## 1. Umgebungen & URLs

`<zone>` = `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`

| Umgebung | Branch | Namespace | Argo-CD-Root | Werte & Images |
|---|---|---|---|---|
| Produktion | `main` | `appstore-prod` | `prod-root` | `k8s/environments/prod.yaml`, `k8s/images/prod.yaml` |
| Staging | `dev` | `appstore-staging` | `staging-root` | `k8s/environments/staging.yaml`, `k8s/images/staging.yaml` |

| Dienst | Produktion | Staging |
|---|---|---|
| AppStore | `https://appstore.<zone>` | `https://appstore-staging.<zone>` |
| Self-Service UI | `https://self-service.<zone>` | `https://self-service-staging.<zone>` |
| Moodle | `https://moodle.<zone>` | `https://moodle-staging.<zone>` |
| Keycloak | `https://sso.<zone>` | `https://sso-staging.<zone>` |
| MCP-Server | `https://appstore-mcp.<zone>` | `https://appstore-mcp-staging.<zone>` |
| Pod- / VM-Apps (`dep-<id>`) | `https://<workload>-<deployment>.<zone>` | `https://<workload>-<deployment>.<zone>` |

## 2. Anwendungen im Cluster

Die Root-Application (`k8s/argocd/roots/<env>.yaml`) rendert über `k8s/argocd/apps-chart` vier Argo-CD-Anwendungen je Umgebung:

| Application | Pfad | Inhalt |
|---|---|---|
| `<env>-platform` (Wave 1) | `k8s/manifests/platform` | PostgreSQL (CloudNativePG: `appstore_t3`, `keycloak`, `moodle`), Keycloak (Realm `dhbw`) |
| `<env>-appstore` (Wave 3) | `k8s/charts/appstore` | `api`, `pod-deployer`, `frontend`, `self-service-ui`, `clamav`, `migrate` (PreSync-Hook), `orphans` (CronJob), `seed` (nur Staging), RBAC, NetworkPolicies, ValidatingAdmissionPolicy |
| `<env>-moodle` (Wave 3) | `k8s/charts/moodle` | `moodle-web`, `moodle-cron`, PVC `moodle-data` |
| `<env>-mcp` (Wave 3) | `k8s/charts/appstore-mcp` | Read-only MCP-Server (`appstore-mcp`) |

## 3. Umgebung einrichten

Voraussetzungen: `kubectl` (mit Cluster-`KUBECONFIG`), `python3`, GitHub-Token mit `read:packages` für `ghcr.io`.

```bash
export KUBECONFIG=/pfad/zur/kubeconfig.yaml
GHCR_PULL_TOKEN_FILE=/pfad/zum/token k8s/bootstrap.sh prod   # oder staging
```

`k8s/bootstrap.sh` legt den Namespace, alle Secrets (Datenbank-Logins, Fernet-Keys, Keycloak- und Moodle-Passwörter, `ghcr-pull`), den CloudNativePG-Operator (`k8s/argocd/cluster/cnpg.yaml`) und die Argo-CD-Root-Application an. Das Skript ist idempotent und überschreibt keine bestehenden Passwörter oder Schlüssel.

Für `appstore-mcp` einmalig die GitHub-OAuth-Credentials eintragen:

```bash
kubectl -n appstore-prod patch secret appstore-mcp --type merge \
  -p '{"stringData":{"github-client-id":"<ID>","github-client-secret":"<SECRET>"}}'
```

Für Windows-VMs (KubeVirt auf Cinder) einmalig im Cluster: `scripts/install-cinder-csi.sh`, `scripts/migrate-golden-image.sh`, `scripts/enable-cross-namespace-clone.sh`.

## 4. Rollout & Promotion

- **Images (`backend`, `worker`, `frontend`, `self-service-ui`, `moodle_appstore`, `appstore-mcp`):**
  Ein Push auf `dev` bzw. `main` im jeweiligen Komponenten-Repository baut und signiert das Image und startet `.github/workflows/k8s-bump.yml`. Nach erfolgreicher Provenance-Prüfung wird der Digest in `k8s/images/staging.yaml` (Auto-Merge auf `dev`) bzw. `k8s/images/prod.yaml` (PR auf `main`) eingetragen.
- **Charts, Policies & Umgebungswerte (`k8s/`):**
  Änderungen gehen per PR auf `dev` (Staging). Promotion nach Produktion erstellt einen PR `dev` → `main`:
  ```bash
  k8s/promote.sh
  ```
- **Rollback:**
  Image-Digest in `k8s/images/<staging|prod>.yaml` per PR auf den vorherigen Stand zurücksetzen; sonstige Änderungen per `git revert`.

## 5. Befehle

| Befehl | Wirkung |
|---|---|
| `kubectl -n argocd get applications \| grep <staging\|prod>` | Sync- und Health-Status der Argo-CD-Apps prüfen |
| `k8s/show-credentials.sh <staging\|prod>` | URLs sowie Keycloak-, Demo- und Moodle-Zugangsdaten aus den Cluster-Secrets ausgeben |
| `kubectl -n appstore-<staging\|prod> port-forward svc/keycloak 8080` | Keycloak-Admin-Konsole lokal unter <http://localhost:8080/admin/> bereitstellen |
| `k8s/keycloak-self-service-client.sh <staging\|prod>` | Client `appstore-self-service` im laufenden Keycloak-Realm `dhbw` anlegen/aktualisieren |
| `k8s/promote.sh` | PR `dev` → `main` für Chart- und Konfigurationsänderungen öffnen |
| `python3 k8s/tests/render_env.py <staging\|prod> /tmp/out.yaml` | Alle Charts einer Umgebung lokal wie Argo CD rendern |
