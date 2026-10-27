# Lokales Setup

Der lokale Stack läuft in einem `k3d`-Cluster (`k3d-appstore-local`, Namespace `appstore-local`) auf Docker und nutzt dieselben Operator- und Helm-Charts wie Staging und Produktion (`k8s/argocd/cluster/cnpg.yaml`, `k8s/manifests/platform`, `k8s/charts/appstore`, `k8s/charts/moodle`).

## 1. Voraussetzungen

- Docker (Ports `80` und `443` frei)
- `k3d`, `kubectl`, `helm` (v3), `git`, `make`, `openssl`, `python3`, `curl`

## 2. Repositories klonen

Alle sechs Repositories müssen nebeneinander im selben Oberverzeichnis liegen:

```bash
mkdir appstore && cd appstore
for r in deployment backend worker frontend self-service-ui moodle_appstore; do
  git clone -b dev https://github.com/DHBW-AppStore-T3/$r.git
done
cd deployment
```

```text
appstore/
├── deployment/
├── backend/
├── worker/
├── frontend/
├── self-service-ui/
└── moodle_appstore/
```

## 3. Starten

```bash
make init
```

`k8s/local/up.sh` erstellt den Cluster `k3d-appstore-local`, baut die lokalen `:dev`-Images, importiert sie in `k3d`, erzeugt ein lokales TLS-Zertifikat für `*.localhost` / `*.apps.localhost` und rollt CloudNativePG, Keycloak, AppStore und Moodle per Helm aus.

## 4. URLs und Zugangsdaten

| Dienst | URL |
|---|---|
| AppStore | <https://appstore.localhost> |
| Self-Service UI | <https://self-service.localhost> |
| Moodle | <https://moodle.localhost> |
| Keycloak | <https://sso.localhost> |
| Pod-Apps | `https://<workload>-<deployment>.apps.localhost` |

Passwort für alle lokalen Konten (`DEV_DEMO_PASSWORD`): **`DevLocal1234!`**

| Nutzer | E-Mail | Keycloak (`dhbw`) | Moodle (*LTI Klicktest*) |
|---|---|---|---|
| `admin.demo` (Moodle-Admin: `admin`) | `admin.demo@appstore.example` | `admin` | Site-Admin (`admin`) |
| `dozent.demo` | `dozent.demo@appstore.example` | `teacher` | `editingteacher` |
| `student1.demo`, `student2.demo` | `student1.demo@appstore.example` | `student` | `student` |

## 5. Befehle

| Befehl | Wirkung |
|---|---|
| `make init` | Images bauen, Cluster starten, Charts ausrollen |
| `make up` | Cluster starten und Charts anwenden (ohne Image-Build) |
| `make down` | Cluster stoppen |
| `make build` | Images neu bauen, importieren und Deployments neu starten |
| `make status` | Pods, Services und Ingresses anzeigen |
| `make health` | HTTPS-Check gegen alle Dienste |
| `make logs` | Logs von `appstore-t3-api` (oder `SERVICE=moodle-web`, `keycloak`, `all`) |
| `make shell` | Shell im Pod (`SERVICE=moodle-web` oder `SERVICE=db` für `psql`) |
| `make restart` | Deployments neu starten |
| `make migrate` | `alembic upgrade head` im API-Pod |
| `make seed` | Seed-Daten im API-Pod laden |
| `make clean` | Cluster `appstore-local` löschen |
