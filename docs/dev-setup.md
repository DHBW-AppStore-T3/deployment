# Lokales Setup — von Null bis zum laufenden AppStore

Ergebnis: Frontend, Backend, Worker, Keycloak und Postgres laufen auf deinem Rechner in Docker-Containern, mit Demo-Nutzern und Demo-Apps.

Geprüft: `make init` auf macOS (Apple Silicon, zsh, Docker 29) aus einem frischen Stand von `dev`, danach `make health`, Seed der fünf Demo-Apps, Deployment der Demo-App pgAdmin bis `success`, `my-access` als Student, Destroy angenommen (HTTP 202). Linux und Windows (WSL2) sind aus Compose-Datei und Makefile abgeleitet, nicht ausgeführt.

## 1. Terminal

Alle Befehle unten tippst du in einem Terminal. Eine Zeile = ein Befehl, Enter führt ihn aus. Das führende `$` gehört nicht zum Befehl und steht hier nicht. Zeilen mit `#` sind Kommentare.

| System | Terminal öffnen |
|---|---|
| macOS | Programm „Terminal“ (Standard-Shell: zsh) |
| Linux | Terminal des Desktops (meist bash) |
| Windows | WSL2 mit Ubuntu installieren (`wsl --install` in PowerShell als Administrator, Neustart), dann „Ubuntu“ öffnen. Alle Befehle laufen in Ubuntu, nicht in PowerShell. Repos in das Linux-Home (`~`) klonen, nicht nach `/mnt/c`. |

bash und zsh verstehen alle Befehle hier identisch.

Die vier Befehle, die du brauchst:

```bash
pwd          # zeigt, in welchem Ordner du bist
ls           # listet den Ordner
cd ordner    # wechselt in einen Ordner (cd .. geht eins hoch, cd ~ ins Home)
# Strg+C     # bricht einen laufenden Befehl ab
```

## 2. Werkzeuge installieren

Benötigt: Git, make, Python 3, Docker mit Compose v2.

| Werkzeug | macOS | Linux (Debian/Ubuntu, auch WSL2) |
|---|---|---|
| Git, make | `xcode-select --install` (Dialog bestätigen) | `sudo apt update && sudo apt install -y git make` |
| Python 3 | in den Command Line Tools enthalten; sonst `brew install python` | `sudo apt install -y python3` |
| Docker | [Docker Desktop](https://www.docker.com/products/docker-desktop/) installieren und **starten** (Wal-Symbol in der Menüleiste ruhig) | Docker Engine mit Compose-Plugin nach [docs.docker.com/engine/install](https://docs.docker.com/engine/install/); Benutzer in Gruppe `docker` (`sudo usermod -aG docker $USER`, neu anmelden) |
| WSL2 | – | Docker Desktop for Windows installieren, in den Einstellungen „Use the WSL 2 based engine“ und die Ubuntu-Distribution unter Resources → WSL integration aktivieren |

Python wird nur von `make env` benötigt (erzeugt den Verschlüsselungsschlüssel, nur Standardbibliothek).

Prüfen — jeder Befehl muss eine Versionsnummer ausgeben, keinen Fehler:

```bash
git --version
make --version
python3 --version
docker --version
docker compose version
docker run --rm hello-world     # „Hello from Docker!“ = Docker läuft und lädt Images
```

`Cannot connect to the Docker daemon`: Docker Desktop ist nicht gestartet (Linux: `sudo systemctl start docker`).

## 3. Freie Ports

Der Stack belegt diese Ports auf deinem Rechner:

| Port | Dienst |
|---|---|
| 5173 | Frontend |
| 8000 | Backend |
| 5432 | Postgres |
| 8081 | Keycloak |

Belegt prüfen (keine Ausgabe = frei):

```bash
lsof -iTCP:5173 -iTCP:8000 -iTCP:5432 -iTCP:8081 -sTCP:LISTEN      # macOS
ss -ltn | grep -E ':(5173|8000|5432|8081) '                         # Linux / WSL2
```

Ist einer belegt, Port beim Start überschreiben (Beispiel Backend auf 8010; das Frontend muss die neue API-Adresse kennen):

```bash
BACKEND_PORT=8010 VITE_API_URL=http://localhost:8010 make init
```

Weitere Überschreibungen: `FRONTEND_PORT`, `KEYCLOAK_PORT`, `DB_PORT`. Dieselben Variablen bei jedem späteren `make`-Aufruf setzen (`make health` kennt sie nur so).

## 4. Repositories klonen

Vier Repositories **nebeneinander** in einem Ordner, Branch `dev`, Ordnernamen unverändert (`docker-compose.dev.yml` baut aus `../backend`, `../worker`, `../frontend`):

```bash
mkdir appstore && cd appstore
for r in deployment backend worker frontend; do git clone -b dev https://github.com/DHBW-AppStore-T3/$r.git; done
cd deployment
```

Ergebnis:

```
appstore/
├── deployment/   docker-compose.dev.yml, Makefile, .env.example, seed/, keycloak/
├── backend/      FastAPI
├── worker/       Celery-Worker
└── frontend/     React 19 + Vite
```

Alle weiteren Befehle laufen in `appstore/deployment/`. Die Repositories sind öffentlich; der Klon braucht keine Anmeldung.

## 5. Erster Start

```bash
make init
```

`make init` führt nacheinander aus:

1. `make env`: legt `.env` aus `.env.example` an und trägt einen frisch erzeugten `CREDENTIAL_ENCRYPTION_KEY` ein (existiert `.env`, bleibt sie unverändert).
2. `docker compose -f docker-compose.dev.yml up -d --build`: baut und startet fünf Container: `postgres-sim`, `keycloak-sim`, `backend-sim`, `worker-sim`, `frontend-sim`.
3. wartet auf Postgres.
4. `make migrate-dev`: Datenbankschema (`alembic upgrade head`), Login der Datenbankrolle `appstore_worker`, Worker-Neustart.
5. `make seed-dev`: Keycloak-Nutzer in die Datenbank, Kurs `WI SE B 23`, fünf Demo-Apps. Liest die App-Repositories von `github.com`: dafür muss Internet erreichbar sein. Ohne Internet bleibt der Katalog leer; später `make seed-dev` wiederholen.

Erster Lauf: einige Minuten (Images bauen, Keycloak-Start). Am Ende:

```
✓ Dev stack bereit.
  Frontend:         http://localhost:5173
  Backend API Docs: http://localhost:8000/docs
  Keycloak Admin:   http://localhost:8081  (admin / admin)
```

## 6. Prüfen

```bash
make health     # Backend, Frontend, Keycloak: je „healthy“
make dev-ps     # fünf Container „Up“, postgres und keycloak „healthy“
```

Im Browser http://localhost:5173 öffnen → „Mit DHBW anmelden“ → Keycloak-Login.

| Nutzer | Rolle | Passwort |
|---|---|---|
| `dozent.demo` | teacher | `DevLocal1234!` |
| `admin.demo` | admin | `DevLocal1234!` |
| `student1.demo` … `student4.demo` | student | `DevLocal1234!` |
| `test-teacher` | teacher | `TestTeacher12` |

Ohne Browser gegen die API (nur lokal, `APP_ENV=development`): Header `X-Dev-User` mit der E-Mail eines Seed-Nutzers (`prof@dhbw.de` Lehrender, `student@dhbw.de`, `admin@dhbw.de`):

```bash
curl -H 'X-Dev-User: prof@dhbw.de' http://localhost:8000/apps/
```

Keycloak-Admin-Konsole: http://localhost:8081, Benutzer `admin`, Passwort `admin`, Realm `dhbw`.

## 7. Alltag

| Befehl | Wirkung |
|---|---|
| `make dev-up` / `make dev-down` | Stack starten / stoppen (Daten bleiben) |
| `make dev-ps` | Container-Status |
| `make dev-logs` | alle Logs (Strg+C beendet das Verfolgen); `dev-logs-backend`, `-worker`, `-frontend`, `-keycloak` |
| `make dev-restart-backend` / `-worker` / `-frontend` / `dev-restart` | Neustart. Backend und Frontend laden Code-Änderungen selbst nach, **der Worker nicht** |
| `make shell-backend` / `shell-worker` / `shell-frontend` | Shell im Container |
| `make shell-db` | `psql` in der Datenbank `backend_dev` |
| `make migrate-dev` | Migrationen anwenden (nach `git pull` im Backend) |
| `make migration-create MSG="text"` | neue Migration aus den Models |
| `make migration-current` / `migration-history` / `migration-downgrade` | Revision / Historie / eine zurück |
| `make seed-dev` | Demo-Daten (idempotent) |
| `make dev-build` / `make dev-rebuild` | Images bauen / kompletter Neubau ohne Cache |
| `make status` / `stats` / `watch-dev` / `top` | Container-Status, Ressourcen, Beobachtung, Prozesse |
| `make help` | alle Targets |

Nach einem `git pull` in einem der Repos: `make dev-up`; bei Änderungen an Abhängigkeiten oder Dockerfiles `make dev-build && make dev-up`; bei neuen Migrationen zusätzlich `make migrate-dev`.

## 8. Tests und Lint

Die Tests liegen in den Repos `backend` und `worker`; Befehle und Test-Datenbanken stehen in deren `README.md`.

| Befehl | Wirkung |
|---|---|
| `make lint-backend` / `lint-backend-fix` / `format-backend` | ruff check / check --fix / format im Backend-Container |
| `make test-backend` | Unit- und Integrationstests des Backends, mit der Umgebung von CI gegen die eigene Datenbank `backend_test` (wird angelegt); die Dev-Datenbank bleibt unberührt |
| `make test-backend-cov` | dasselbe mit HTML-Coverage (`backend/htmlcov/`) |

Worker-Tests: Rezept in `worker/README.md`, Abschnitt Tests.

## 9. Was echt ist und was simuliert

| Bereich | Lokal |
|---|---|
| Anmeldung | echter Keycloak 26.4, Realm `dhbw` (Import aus `keycloak/dhbw-realm.json`) |
| Datenbank, Queue | echtes Postgres 16; die Queue ist die Tabelle `celery_queue` (kein RabbitMQ, kein Redis) |
| Pod-Apps (`runtime: kubernetes`) | Worker mit `WORKER_SIMULATE=true`: Kubernetes-Objekte gegen In-Memory-`FakeKube`, kein Cluster. Zugangsdaten und Live-Status funktionieren; der Zustand ist nach einem Worker-Neustart weg |
| KubeVirt-VMs | nicht lokal |
| E-Mail, ClamAV, LTI/Moodle | nicht im lokalen Stack |

Der Weg vom Klick bis zum Worker-Job läuft vollständig durch; nur die letzten Aufrufe gegen Kubernetes sind ersetzt.

## 10. Konfiguration

`.env` (aus `.env.example`) enthält nur `CREDENTIAL_ENCRYPTION_KEY` (Pflicht, `make env` füllt ihn) und optional `KEYCLOAK_CLIENT_SECRET` (Standard `dev-local-secret`). Alle anderen Werte stehen mit Standardwerten in `docker-compose.dev.yml`.

Neuen Schlüssel erzeugen: `make secret` (gibt die Zeile aus; in `.env` eintragen; bereits gespeicherte Task-Ergebnisse sind danach nicht mehr lesbar).

Kein `.env`, kein Schlüssel: Compose bricht mit `CREDENTIAL_ENCRYPTION_KEY is required` ab.

## 11. Zurücksetzen

| Ziel | Befehl |
|---|---|
| Datenbank leeren und neu migrieren, danach neu seeden | `make db-reset-dev`, dann `make seed-dev` |
| Alles löschen (Container, Volumes, Datenbank, Keycloak-Zustand) | `make clean-dev`, danach `make init` |
| Zusätzlich lokale Images löschen | `make clean-all` |
| Docker insgesamt aufräumen (auch fremde Images/Volumes) | `make prune` |

`.env` bleibt bei allen erhalten. Der Realm wird nur beim ersten Start importiert; Änderungen an `keycloak/dhbw-realm.json` greifen erst nach `make clean-dev && make init`.

Stand eines manuell geänderten Realms zurückschreiben:

```bash
docker exec keycloak-sim /opt/keycloak/bin/kc.sh export --file /tmp/dhbw-realm-export.json --realm dhbw
docker cp keycloak-sim:/tmp/dhbw-realm-export.json keycloak/dhbw-realm.json
```

## 12. Fehlerbilder

| Meldung / Symptom | Ursache | Lösung |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker nicht gestartet | Docker Desktop starten |
| `CREDENTIAL_ENCRYPTION_KEY is required` | `.env` fehlt oder Schlüssel leer | `make env`; existiert `.env` mit leerem Wert, `make secret` und eintragen |
| `Bind for 0.0.0.0:8000 failed: port is already allocated` / `address already in use` | Port belegt | Abschnitt 3 |
| `make: *** No rule to make target` oder `docker-compose.dev.yml: no such file` | falscher Ordner | `cd appstore/deployment` |
| `unable to prepare context: path "…/backend" not found` | Repo fehlt oder anders benannt | Abschnitt 4 |
| Login-Seite lädt nicht | Keycloak noch nicht bereit | `make health`, `make dev-logs-keycloak` |
| Katalog leer | Seed ohne Internet gelaufen | `make seed-dev` |
| API antwortet 401 `Dev user … not found` | `X-Dev-User` ohne Seed-Nutzer | `make seed-dev` |
| Deployment bleibt `pending` | Worker nicht gestartet oder Rolle `appstore_worker` ohne Login | `make dev-logs-worker`; `make migrate-dev` |
| Worker nimmt Code-Änderung nicht an | kein Hot-Reload | `make dev-restart-worker` |
| Container-Build bricht mit Netzwerkfehler ab | Registry/Proxy nicht erreichbar | erneut `make init`; hinter Proxy Docker-Proxy-Einstellungen prüfen |
| WSL2: sehr langsam | Repos unter `/mnt/c` | in das Linux-Home klonen |

Logs lesen: `make dev-logs-<dienst>`; Container-Status: `make dev-ps`.
