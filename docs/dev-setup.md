# Lokales Entwicklungs-Setup

Die lokale Umgebung läuft in einem **`k3d`-Kubernetes-Cluster** (`appstore-local`, Namespace `appstore-local`) mit denselben Helm-Charts wie Staging und Produktion (`k8s/manifests/platform`, `k8s/charts/appstore`, `k8s/charts/moodle`).

## 1. Voraussetzungen

1. **Container-Engine:** Docker Desktop oder Podman (mit `docker`-CLI-Alias), mind. **4 CPUs** und **6 GiB RAM**. Freie Ports `80` und `443`.
2. **CLI-Tools:** `k3d`, `kubectl`, `helm` (v3), `openssl`, `python3`, `git`, `make`, `curl` (z. B. via `brew install k3d kubectl helm openssl python3 git make curl` oder Paketmanager; unter Windows in WSL2 ausführen).
3. **Verzeichnisstruktur:** Alle 6 Repositories liegen als Geschwister-Ordner im selben Oberverzeichnis:
   ```text
   MoodleAppStore/
   ├── backend/
   ├── worker/
   ├── frontend/
   ├── self-service-ui/
   ├── moodle_appstore/
   └── deployment/
   ```

## 2. Starten

```bash
cd deployment
make init
```

[`k8s/local/up.sh`](../k8s/local/up.sh) erstellt den Cluster `k3d-appstore-local`, baut und importiert die lokalen Images, richtet ein lokales `*.localhost`-TLS-Zertifikat samt Root-CA ein und rollt CloudNativePG, Keycloak, AppStore und Moodle per Helm aus.

## 3. URLs & Zugangsdaten

| Dienst | URL |
|---|---|
| **AppStore** | <https://appstore.localhost> |
| **Moodle LMS** | <https://moodle.localhost> |
| **Self-Service UI** | <https://self-service.localhost> |
| **Keycloak SSO** | <https://sso.localhost> |
| **Bereitgestellte Pod-Apps** | `https://<workload>-<deployment>.apps.localhost` |

Standardpasswort für alle lokalen Accounts (überschreibbar via `DEV_DEMO_PASSWORD`): **`DevLocal1234!`**

| Benutzer | E-Mail | Keycloak (`dhbw`) | Moodle (*LTI Klicktest*) |
|---|---|---|---|
| `admin.demo` (Moodle-Admin: `admin`) | `admin.demo@appstore.example` | `admin` | Site-Admin (`admin`) |
| `dozent.demo` | `dozent.demo@appstore.example` | `teacher` | Trainer/in (`editingteacher`) |
| `student1.demo`, `student2.demo` | `student1.demo@appstore.example` | `student` | Teilnehmer/in (`student`) |

## 4. Befehle

```bash
make init                          # Images bauen, Cluster starten & Charts ausrollen
make up                            # Cluster starten & Charts anwenden (ohne Image-Rebuild)
make down                          # Cluster stoppen (Zustand bleibt erhalten)
make build                         # Images neu bauen, importieren & Deployments neu starten
make status                        # Pods, Services und Ingresses anzeigen
make health                        # HTTPS-Erreichbarkeit aller Dienste prüfen
make logs                          # Logs der API (oder z. B. make logs SERVICE=moodle-web / SERVICE=all)
make shell                         # Shell im Pod (oder make shell SERVICE=db für psql)
make restart                       # Alle Deployments neu starten
make migrate                       # Alembic-Migrationen im API-Pod ausführen
make seed                          # Seed-Daten erneut laden
make clean                         # Lokalen k3d-Cluster komplett löschen
```
