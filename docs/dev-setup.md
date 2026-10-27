# Lokales Setup

Der lokale Stack läuft in einem `k3d`-Cluster (`k3d-appstore-local`, Namespace `appstore-local`) auf Docker und nutzt dieselben Operator- und Helm-Charts wie Staging und Produktion (`k8s/argocd/cluster/cnpg.yaml`, `k8s/manifests/platform`, `k8s/charts/appstore`, `k8s/charts/moodle`).

Unterstützte Architekturen: `arm64` und `amd64` auf macOS, Linux und Windows (WSL2). `k8s/local/up.sh` fragt die Architektur des `k3d`-Nodes ab und baut alle Images mit `--platform linux/<arch>`.

## 1. Werkzeuge installieren

Benötigt: Docker (mind. 4 CPUs, 6 GiB RAM; Ports `80` und `443` auf dem Host frei), `git`, `make`, `python3`, `openssl`, `curl`, `kubectl`, `helm` (v3), `k3d`.

| System | Installation |
|---|---|
| macOS | [Docker Desktop](https://www.docker.com/products/docker-desktop/) starten, dann:<br>`brew install git make python openssl curl kubernetes-cli helm k3d` |
| Linux (Debian/Ubuntu) | [Docker Engine](https://docs.docker.com/engine/install/) installieren (`sudo usermod -aG docker $USER`), dann:<br>`sudo apt update && sudo apt install -y git make python3 openssl curl ca-certificates`<br>`curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/$(dpkg --print-architecture)/kubectl" && sudo install -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl`<br>`curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 \| bash`<br>`curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh \| bash` |
| Windows (WSL2) | WSL2 mit Ubuntu installieren (`wsl --install`), Docker Desktop for Windows mit WSL2-Integration starten. Alle Befehle im Ubuntu-Terminal im Linux-Home (`~`, nicht `/mnt/c`) ausführen; Werkzeuge wie unter Linux installieren. |

Prüfen:

```bash
docker info >/dev/null && echo "docker: ok"
for c in git make python3 openssl curl kubectl helm k3d; do command -v "$c" >/dev/null || echo "fehlt: $c"; done
lsof -iTCP:80 -iTCP:443 -sTCP:LISTEN   # macOS (keine Ausgabe = Ports 80/443 frei)
ss -ltn | grep -E ':(80|443) '         # Linux / WSL2
```

## 2. Repositories klonen

`k8s/local/up.sh` baut die `:dev`-Images aus den Geschwister-Verzeichnissen. Alle sechs Repositories müssen nebeneinander im selben Ordner liegen (Branch `dev`, Ordnernamen unverändert):

```bash
mkdir appstore && cd appstore
for r in deployment backend worker frontend self-service-ui moodle_appstore; do
  git clone -b dev https://github.com/DHBW-AppStore-T3/$r.git
done
cd deployment
```

Verzeichnisstruktur:

```text
appstore/
├── deployment/        Makefile, k8s/
├── backend/           FastAPI
├── worker/            Pod-Deployer (Celery)
├── frontend/          React + Nginx
├── self-service-ui/   Self-Service UI (oauth2-proxy + Caddy)
└── moodle_appstore/   Moodle (Apache + PHP 8.3)
```

## 3. Starten

In `appstore/deployment/`:

```bash
make init
```

Ablauf von `make init` (`k8s/local/up.sh`):

1. Erstellt den Cluster `k3d-appstore-local` (Ports `80` und `443` auf Traefik).
2. Baut `backend`, `worker-pods`, `frontend`, `self-service-ui` und `moodle_appstore` als `:dev`-Images und importiert sie per `ctr` in den `k3d`-Node (`moodle_appstore` wird per Git-Tree-Hash gecacht und nur bei Änderungen neu gebaut).
3. Erzeugt unter `k8s/local/.certs/` eine lokale Root-CA und ein TLS-Zertifikat für `*.localhost` / `*.apps.localhost`, setzt es als Traefik-Default-Zertifikat und trägt die CA in den System-Trust-Store ein (`SKIP_TRUST_CERT=1` überspringt den Eintrag).
4. Legt die Secrets im Namespace `appstore-local` an, installiert den CloudNativePG-Operator und startet den Postgres-Cluster (`keycloak`, `appstore_t3`, `moodle`).
5. Rollt `k8s/manifests/platform` (Keycloak + Realm `dhbw` + Demo-User), `k8s/charts/appstore` (Migrationen, API, Pod-Deployer, Frontend, Self-Service-UI, Seed-Job) und `k8s/charts/moodle` (inkl. LTI-1.3-Tool und Kurs *LTI Klicktest*) aus.

Prüfen:

```bash
make health
make status
```

## 4. URLs und Zugangsdaten

| Dienst | URL |
|---|---|
| AppStore | <https://appstore.localhost> |
| Self-Service UI | <https://self-service.localhost> |
| Moodle | <https://moodle.localhost> |
| Keycloak | <https://sso.localhost> (Admin-Konsole: `/admin/`, Login `admin` / `DevLocal1234!`) |
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
| `make up` | Cluster starten und Charts anwenden (ohne Image-Build, `SKIP_BUILD=1`) |
| `make down` | Cluster stoppen (Volumes bleiben erhalten) |
| `make build` | Images neu bauen, importieren und Deployments neu starten (`REBUILD_MOODLE=1 make build` baut auch Moodle neu) |
| `make status` | Pods, Services und Ingresses in `appstore-local` |
| `make health` | HTTPS-Check gegen AppStore, Self-Service UI, Moodle, Keycloak und Cluster |
| `make logs` | Logs von `appstore-t3-api` (oder `SERVICE=appstore-t3-pod-deployer`, `moodle-web`, `keycloak`, `all`) |
| `make shell` | Shell im Pod (`SERVICE=moodle-web` oder `SERVICE=db` für `psql`) |
| `make restart` | Deployments neu starten |
| `make migrate` | `alembic upgrade head` im API-Pod |
| `make seed` | Seed-Daten im API-Pod laden |
| `make clean` | Cluster `appstore-local` löschen |

## 6. Fehlerbilder

| Symptom | Ursache | Lösung |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker läuft nicht | Docker starten |
| `Sibling repository '.../backend' not found` | Eines der 6 Repos fehlt im Oberverzeichnis | Abschnitt 2: fehlendes Repo klonen |
| `port is already allocated` (`:80` / `:443`) | Port 80 oder 443 auf dem Host belegt | Dienst auf Port 80/443 beenden |
| Zertifikatswarnung im Browser | Browser nutzt eigenen Trust-Store (z. B. Firefox) | `k8s/local/.certs/local-ca.crt` im Browser importieren oder Browser neu starten |
| Katalog im AppStore leer | Seed-Job lief ohne Verbindung zu `github.com` | `make seed` |
| Realm-Änderung in `dhbw-realm.json` greift nicht | Keycloak importiert den Realm nur in eine leere DB | `make clean && make init` |
