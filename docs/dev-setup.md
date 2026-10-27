# Lokales Entwicklungs-Setup (100 % Kubernetes + Moodle)

Die lokale Entwicklungsumgebung läuft **identisch zu Staging und Produktion** vollständig in einem lokalen **k3d-Kubernetes-Cluster** (`appstore-local`, Namespace `appstore-local`) und nutzt dieselben Helm-Charts wie das echte Cluster:

- **CloudNativePG Operator ([`k8s/argocd/cluster/cnpg.yaml`](../k8s/argocd/cluster/cnpg.yaml))**: Verwaltet den PostgreSQL-Cluster und die Datenbank-Rollen exakt wie auf Staging und Prod
- **Platform ([`k8s/manifests/platform/`](../k8s/manifests/platform))**: CloudNativePG-Cluster `postgres-cluster` (`postgres-cluster-rw` mit TLS, Datenbanken `keycloak`, `appstore_t3`, `moodle` & verwalteten Rollen) + Keycloak 26.4 mit dem produktiven Realm `dhbw` und den Demo-Usern (`admin.demo`, `dozent.demo`, `student1.demo`..`student4.demo`)
- **AppStore ([`k8s/charts/appstore/`](../k8s/charts/appstore))**: `appstore-t3-api`, `appstore-t3-pod-deployer`, `appstore-t3-frontend`, `appstore-t3-self-service-ui`, `appstore-t3-migrate`, `appstore-t3-seed`, produktive `ClusterRole`s und `ValidatingAdmissionPolicy`
- **Moodle ([`k8s/charts/moodle/`](../k8s/charts/moodle))**: `moodle-web` (inkl. Init-Containern `init` & `configure`) und `moodle-cron` mit vorkonfiguriertem **LTI-1.3-Tool (`DHBW AppStore`)** und Beispielkurs *„LTI Klicktest“* (`AppStore Beispiel-App`)

---

## 1. Voraussetzungen

- **Docker Desktop** oder **Podman** (`podman machine` mit mind. 4 CPUs / 4 GiB RAM)
- **`k3d`**, **`kubectl`**, **`helm`**, **`openssl`**, **`python3`**:
  ```bash
  brew install k3d kubectl helm
  ```
- Alle Repositories liegen als Geschwister-Ordner nebeneinander:
  ```text
  MoodleAppStore/
  ├── backend/
  ├── worker/
  ├── frontend/
  ├── self-service-ui/
  ├── moodle_appstore/
  └── deployment/
  ```

---

## 2. Starten mit einem Befehl

Im Ordner `deployment/`:

```bash
make init
```

`make init` führt [`k8s/local/up.sh`](../k8s/local/up.sh) aus:
1. Erstellt (falls noch nicht vorhanden) den lokalen Cluster `k3d-appstore-local` mit Port-Forwarding `80 -> Traefik` und `443 -> Traefik` (inkl. automatischer Podman-VM-Konfiguration falls Podman statt Docker Desktop genutzt wird).
2. Baut die 5 lokalen Container-Images (`backend`, `worker --target pod-deployer`, `frontend`, `self-service-ui`, `moodle_appstore`) und importiert sie direkt in `k3d`.
3. Erzeugt eine lokale Root-CA (`k8s/local/.certs/local-ca.crt`) samt `*.localhost`-Wildcard-Zertifikat für Traefik und trägt die Root-CA unter macOS automatisch in den Login-Schlüsselbund ein (einmalige TouchID-/Passwort-Abfrage; jederzeit auch einzeln per `make trust-cert` ausführbar). Dadurch funktionieren Cross-Subdomain-Aufrufe im Browser (z. B. `https://appstore.localhost` → `https://sso.localhost`) ohne Zertifikatswarnungen.
4. Erstellt den Namespace `appstore-local` und alle benötigten Kubernetes-Secrets (`kubernetes.io/basic-auth` für die CNPG-Rollen sowie AppStore-/Keycloak-/Moodle-Secrets) idempotent.
5. Installiert den CloudNativePG-Operator (`cnpg-system`) und rollt ohne eigene Dev-Manifeste oder separate Values-Dateien direkt die produktiven Charts [`k8s/manifests/platform`](../k8s/manifests/platform), [`k8s/charts/appstore`](../k8s/charts/appstore) und [`k8s/charts/moodle`](../k8s/charts/moodle) mit `*.localhost`-Hostnamen aus.

---

## 3. URLs & Zugangsdaten

Alle Dienste laufen über den `k3d`-Traefik-Ingress-Controller unter `*.localhost` (HTTPS mit lokalem `*.localhost`-Wildcard-Zertifikat):

| Dienst | URL | Beschreibung |
|---|---|---|
| **AppStore Frontend** | <https://appstore.localhost> | React-UI + FastAPI (`/api/*`) |
| **Moodle LMS** | <https://moodle.localhost> | Moodle mit Kurs *„LTI Klicktest“* & LTI-1.3-Aktivität *„AppStore Beispiel-App“* |
| **Self-Service UI** | <https://self-service.localhost> | Zweite UI hinter `oauth2-proxy` |
| **Keycloak SSO** | <https://sso.localhost> | Realm `dhbw` + Admin-Konsole (`/admin`) |
| **Studenten-Pod-Apps** | `https://<workload>-<deployment>.apps.localhost` | Vom `pod-deployer` in eigenen `dep-*`-Namespaces ausgerollte Katalog-Apps |

### Demo-Accounts (Keycloak SSO & Moodle LMS)

Standardpasswort für **alle** lokalen Demo- und Admin-Accounts (überschreibbar via `DEV_DEMO_PASSWORD`):

```text
DevLocal1234!
```

| Benutzername | E-Mail | Rolle in Keycloak (`dhbw`) | Rolle in Moodle (*LTI Klicktest*) |
|---|---|---|---|
| `admin.demo` (Moodle-Admin: `admin`) | `admin.demo@appstore.example` | `admin` | Site-Administrator (`admin`) |
| `dozent.demo` | `dozent.demo@appstore.example` | `teacher` | Trainer/in (`editingteacher`) |
| `student1.demo` | `student1.demo@appstore.example` | `student` | Teilnehmer/in (`student`) |
| `student2.demo` | `student2.demo@appstore.example` | `student` | Teilnehmer/in (`student`) |

Da die E-Mail-Adressen in Moodle und im Keycloak-Realm `dhbw` übereinstimmen, landen LTI-1.3-Starts aus Moodle und direkte SSO-Logins im AppStore beim selben Benutzerkonto.

---

## 4. Häufige Befehle

```bash
make urls            # Zeigt alle lokalen URLs und Demo-Zugangsdaten
make health          # Prüft HTTPS-Erreichbarkeit aller Dienste + Cluster-Status
make status          # Zeigt alle Pods, Services und Ingresses in appstore-local
make trust-cert      # Vertraut der lokalen *.localhost Root-CA im macOS-Schlüsselbund (passiert bei make init/dev-up automatisch)
make dev-up          # Startet k3d und wendet Helm-Charts an (ohne Image-Rebuild)
make dev-build       # Baut lokale Images neu, importiert sie in k3d und startet Pods neu
make dev-down        # Stoppt den lokalen k3d-Cluster (Zustand bleibt erhalten)
make clean-dev       # Löscht den lokalen k3d-Cluster komplett
make dev-logs        # Zeigt Live-Logs von API und Pod-Deployer
make dev-logs-moodle # Zeigt Live-Logs von Moodle
```
