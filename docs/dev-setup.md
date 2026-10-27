# Lokales Entwicklungs-Setup — von Null bis zum laufenden Stack

Die lokale Umgebung läuft in einem leichtgewichtigen **`k3d`-Kubernetes-Cluster** (`k3d-appstore-local`, Namespace `appstore-local`) direkt auf **Docker** und rollt exakt dieselben Operator- und Helm-Charts wie Staging und Produktion aus (`k8s/argocd/cluster/cnpg.yaml`, `k8s/manifests/platform`, `k8s/charts/appstore`, `k8s/charts/moodle`).

Unterstützte Architekturen: **`arm64` (Apple Silicon)** und **`amd64` (`x86_64`)** auf macOS, Linux und Windows (WSL2). [`k8s/local/up.sh`](../k8s/local/up.sh) erkennt die Architektur des `k3d`-Nodes automatisch und baut alle lokalen Images nativ für diese Zielplattform.

---

## 1. Voraussetzungen & Werkzeuge installieren

Benötigt werden **Docker** (mind. **4 CPUs** und **6 GiB RAM** zugewiesen; Ports **`80`** und **`443`** auf dem Host frei) sowie die CLI-Werkzeuge `git`, `make`, `python3`, `openssl`, `curl`, `kubectl`, `helm` (v3) und `k3d`.

### macOS (Apple Silicon `arm64` & Intel `amd64`)

1. [Docker Desktop für Mac](https://www.docker.com/products/docker-desktop/) installieren und **starten**.
2. Übrige Werkzeuge über [Homebrew](https://brew.sh/) installieren:
   ```bash
   brew install git make python openssl curl kubernetes-cli helm k3d
   ```

### Linux (`amd64` & `arm64`, z. B. Debian/Ubuntu)

1. [Docker Engine](https://docs.docker.com/engine/install/) installieren und den eigenen Benutzer zur Gruppe `docker` hinzufügen (`sudo usermod -aG docker $USER`, danach neu anmelden).
2. Basis-Pakete sowie `kubectl`, `helm` und `k3d` installieren:
   ```bash
   sudo apt update && sudo apt install -y git make python3 openssl curl ca-certificates
   curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/$(dpkg --print-architecture)/kubectl"
   sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && rm kubectl
   curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
   curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | bash
   ```

### Windows (via WSL2)

1. **WSL2 mit Ubuntu** installieren (`wsl --install` in PowerShell als Administrator, Neustart) und das Programm **Ubuntu** öffnen. Alle folgenden Befehle werden im **Ubuntu-Terminal (WSL2)** ausgeführt – und die Repositories müssen im Linux-Dateisystem (`~`), **nicht** unter `/mnt/c`, liegen.
2. **Docker Desktop for Windows** installieren, in den Einstellungen *Use the WSL 2 based engine* sowie unter *Resources → WSL integration* die Ubuntu-Distribution aktivieren.
3. Im Ubuntu-Terminal die Linux-Befehle von oben ausführen, um `git`, `make`, `python3`, `openssl`, `curl`, `kubectl`, `helm` und `k3d` zu installieren.

### Installation prüfen

Jeder dieser Befehle muss fehlerfrei durchlaufen:

```bash
docker info >/dev/null && echo "Docker läuft"
for cmd in git make python3 openssl curl kubectl helm k3d; do command -v "$cmd" >/dev/null && echo "$cmd: OK" || echo "$cmd: FEHLT"; done
```

Freie Ports `80` und `443` prüfen (keine Ausgabe = frei):

```bash
lsof -iTCP:80 -iTCP:443 -sTCP:LISTEN   # macOS
ss -ltn | grep -E ':(80|443) '         # Linux / WSL2
```

---

## 2. Von Null starten: Repositories klonen

Da [`k8s/local/up.sh`](../k8s/local/up.sh) die lokalen `:dev`-Images aus den Geschwister-Verzeichnissen baut, müssen alle **6 Repositories nebeneinander im selben Oberverzeichnis** auf dem Branch **`dev`** liegen. Die Ordnernamen dürfen nicht verändert werden:

```bash
mkdir MoodleAppStore && cd MoodleAppStore

for repo in deployment backend worker frontend self-service-ui moodle_appstore; do
  git clone -b dev "https://github.com/DHBW-AppStore-T3/${repo}.git"
done

cd deployment
```

Dadurch entsteht folgende Verzeichnisstruktur:

```text
MoodleAppStore/
├── deployment/        <-- Arbeitsverzeichnis für alle make-Befehle
├── backend/           (FastAPI)
├── worker/            (Kubernetes Pod-Deployer)
├── frontend/          (React + Vite + Nginx)
├── self-service-ui/   (Self-Service UI + oauth2-proxy + Caddy)
└── moodle_appstore/   (Moodle LMS Fork + Apache/PHP 8.3)
```

---

## 3. Cluster & Stack starten

Im Verzeichnis `MoodleAppStore/deployment/` ausführen:

```bash
make init
```

Was `make init` ([`k8s/local/up.sh`](../k8s/local/up.sh)) automatisch ausführt:

1. **Cluster erstellen:** Legt den `k3d`-Cluster `appstore-local` (`k3d-appstore-local`) an und verbindet die Host-Ports `80` und `443` direkt mit dem Traefik-LoadBalancer des Clusters.
2. **Lokale Images bauen & importieren:** Baut `backend`, `worker-pods`, `frontend`, `self-service-ui` und `moodle_appstore` für die Architektur des Clusters (`linux/arm64` bzw. `linux/amd64`) und importiert sie direkt in `containerd` von `k3d` (kein lokaler Registry-Container nötig). Das große Moodle-Image wird anhand seines Git-Tree-Hashes gecacht und nur bei Änderungen in `moodle_appstore` neu gebaut.
3. **Lokale Root-CA & TLS-Zertifikat:** Erzeugt unter `k8s/local/.certs/` eine lokale Root-CA sowie ein Wildcard-TLS-Zertifikat (`*.localhost`, `*.apps.localhost`), hinterlegt es als Traefik-Default-Zertifikat und registriert die Root-CA im Betriebssystem-Zertifikatsspeicher (macOS Keychain, Linux `ca-certificates`, Windows Certificate Store via WSL2; überspringbar mit `SKIP_TRUST_CERT=1`).
4. **Secrets & Datenbanken:** Generiert alle benötigten Kubernetes-Secrets im Namespace `appstore-local`, installiert den **CloudNativePG-Operator** und fährt den PostgreSQL-Cluster (`postgres-cluster`) mit den Datenbanken `keycloak`, `appstore_t3` und `moodle` hoch.
5. **Keycloak, AppStore & Moodle ausrollen:** Rollt das Platform-Chart (Keycloak + `dhbw`-Realm + Theme + Demo-User), das AppStore-Chart (Migrationen, API, Pod-Deployer, Frontend, Self-Service-UI, Admission-Policy, RBAC, Seed-Job mit den Katalog-Apps) und das Moodle-Chart (inkl. vorkonfiguriertem LTI-1.3-Tool und Demo-Kurs *LTI Klicktest*) mit den Standardwerten der Produktions-Charts aus.

Nach Abschluss prüfen, ob alle Dienste erreichbar sind:

```bash
make health
make status
```

---

## 4. URLs & Zugangsdaten

Moderne Browser und Betriebssysteme lösen `*.localhost` automatisch auf `127.0.0.1` / `::1` auf (kein `/etc/hosts`-Eintrag erforderlich):

| Dienst | URL | Beschreibung |
|---|---|---|
| **AppStore UI** | <https://appstore.localhost> | Hauptanwendung (Dozenten-, Admin- & Studierenden-Ansicht; API unter `/api`) |
| **Self-Service UI** | <https://self-service.localhost> | Zweite Oberfläche (Katalog, 1-Klick-Deploy, eigene Zugangsdaten) |
| **Moodle LMS** | <https://moodle.localhost> | Moodle mit vorkonfiguriertem Kurs *LTI Klicktest* und LTI-1.3-Anbindung an den AppStore |
| **Keycloak SSO** | <https://sso.localhost> | OIDC-Identity-Provider (Realm `dhbw` sowie Admin-Konsole unter `/admin/`) |
| **Bereitgestellte Pod-Apps** | `https://<workload>-<deployment>.apps.localhost` | Aus dem AppStore bereitgestellte Studierenden-Pods |

Standardpasswort für **alle** lokalen Konten (überschreibbar beim Start mit `DEV_DEMO_PASSWORD=...`): **`DevLocal1234!`**

| Benutzer | E-Mail | Rolle in Keycloak (`dhbw`) | Rolle in Moodle (*LTI Klicktest*) |
|---|---|---|---|
| `admin.demo` *(Moodle-Site-Admin: `admin`)* | `admin.demo@appstore.example` | `admin` | Site-Admin (`admin`) |
| `dozent.demo` | `dozent.demo@appstore.example` | `teacher` | Trainer/in (`editingteacher`) |
| `student1.demo` | `student1.demo@appstore.example` | `student` | Teilnehmer/in (`student`) |
| `student2.demo` | `student2.demo@appstore.example` | `student` | Teilnehmer/in (`student`) |

*(Keycloak-Master-Admin unter <https://sso.localhost/admin/>: Benutzer `admin`, Passwort `DevLocal1234!`)*

---

## 5. Wichtige Befehle im Entwicklungsalltag

Alle Befehle werden im Ordner `deployment/` ausgeführt (`make help` zeigt eine Kurzübersicht):

| Befehl | Wirkung |
|---|---|
| `make init` | Lokale Images bauen, `k3d`-Cluster starten und alle Helm-Charts ausrollen |
| `make up` | Cluster starten und Helm-Charts anwenden (**ohne** Image-Rebuild, `SKIP_BUILD=1`) |
| `make down` | `k3d`-Cluster stoppen (Daten und Volumes bleiben erhalten) |
| `make build` | Lokale Images nach Code-Änderungen neu bauen, in `k3d` importieren und Deployments neu starten (`REBUILD_MOODLE=1 make build` erzwingt auch einen Moodle-Rebuild) |
| `make status` | Alle Pods, Services und Ingresses im Namespace `appstore-local` anzeigen |
| `make health` | HTTPS-Erreichbarkeit von AppStore API/UI, Self-Service UI, Moodle, Keycloak und K8s-Cluster prüfen |
| `make logs` | Live-Logs der API verfolgen (andere Dienste: `make logs SERVICE=appstore-t3-pod-deployer`, `SERVICE=moodle-web`, `SERVICE=keycloak` oder `SERVICE=all`) |
| `make shell` | Interaktive Shell im Pod öffnen (`make shell SERVICE=moodle-web` oder `make shell SERVICE=db` für `psql` auf `appstore_t3`) |
| `make restart` | Alle Deployments im Cluster neu starten |
| `make migrate` | Alembic-Datenbankmigrationen im API-Pod ausführen |
| `make seed` | Seed-Daten (Demo-Kurs & Katalog-Apps) erneut in die Datenbank laden |
| `make clean` | Lokalen `k3d`-Cluster samt Datenbanken und Volumes komplett löschen |

---

## 6. Fehlerbehebung (Troubleshooting)

| Symptom / Fehlermeldung | Ursache | Lösung |
|---|---|---|
| `ERROR: Cannot connect to the Docker daemon` | Docker läuft nicht | Docker Desktop bzw. `docker.service` starten |
| `ERROR: Sibling repository '.../backend' not found` | Ein oder mehrere der 6 Repositories fehlen im Oberverzeichnis | Siehe [Abschnitt 2](#2-von-null-starten-repositories-klonen): alle 6 Repos nebeneinander klonen |
| `port is already allocated` (Port `80` oder `443`) | Lokaler Webserver (Apache/Nginx/Caddy) oder alter Container belegt Port 80/443 | Portbelegung mit `lsof -iTCP:80 -iTCP:443 -sTCP:LISTEN` prüfen und Dienst beenden |
| Browser warnt vor selbstsigniertem Zertifikat | Lokale Root-CA wurde noch nicht akzeptiert oder Browser nutzt eigenen Trust-Store (z. B. Firefox) | Zertifikat `k8s/local/.certs/local-ca.crt` im Browser importieren oder Browser nach dem ersten `make init` neu starten |
| App-Katalog im AppStore ist leer | Während des Seed-Jobs bestand keine Verbindung zu `github.com` | Sobald Internet verfügbar ist: `make seed` ausführen |
| Kompletter Reset nach größeren Chart-/Realm-Änderungen | Bestehender Keycloak-Realm oder Datenbankzustand soll frisch initialisiert werden | `make clean && make init` |
