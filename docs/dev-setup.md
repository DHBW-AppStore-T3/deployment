# Lokales Dev Setup

Der AppStore läuft lokal mit echtem Keycloak (Realm `dhbw`) und echter OIDC-Authentifizierung — so nah wie möglich an Prod. OpenStack-Aufrufe werden simuliert (Dummy-Daten), Kubernetes-Deployments laufen über FakeKube (In-Memory).

## Voraussetzungen

| Werkzeug | Version | Anmerkung |
|---|---|---|
| Docker Desktop (oder Docker Engine + Compose Plugin) | 24.x oder neuer | Compose v2 (`docker compose`) ist enthalten |
| Git | 2.x | |
| Python 3 | 3.11+ | Einmalig zum Generieren des Fernet-Keys |
| GNU Make | beliebig | Alle Schritte sind als `make`-Targets ausgelegt |
| Freie Ports | 5173, 8000, 5432, 8081 | Bei Konflikt in `.env` überschreiben |

## Schritt 1: Repos klonen

```bash
mkdir appstore && cd appstore
git clone https://github.com/DHBW-AppStore-T3/frontend
git clone https://github.com/DHBW-AppStore-T3/backend
git clone https://github.com/DHBW-AppStore-T3/worker
git clone https://github.com/DHBW-AppStore-T3/deployment
cd deployment
```

Alle weiteren Befehle werden aus `deployment/` ausgeführt.

Verzeichnislayout nach dem Klonen:

```
appstore/
├── frontend/     # React + Vite
├── backend/      # FastAPI + Alembic
├── worker/       # Celery + FakeKube
└── deployment/   # docker-compose.dev.yml, Makefile, .env.example, seed/
```

## Schritt 2: `.env` anlegen und Key generieren

```bash
make env
```

Das kopiert `.env.example` nach `.env`. Danach den Pflicht-Key eintragen:

```bash
make secret
```

Die Ausgabe (`CREDENTIAL_ENCRYPTION_KEY=...`) in die `.env` kopieren. Ohne diesen Key startet der Stack nicht.

## Schritt 3: Erster Start

```bash
make init
```

`make init` macht alles auf einmal:
1. Baut alle Images
2. Startet die 5 Container (postgres, keycloak, backend, worker, frontend)
3. Wartet bis Postgres und Keycloak bereit sind
4. Führt Alembic-Migrationen aus
5. Spielt Seed-Daten ein (1 Kurs, 3 Apps)

Beim ersten Start dauert das 3–5 Minuten (Image-Build + Keycloak-Start). Danach:

```
✓ Dev stack bereit.
  Frontend:         http://localhost:5173
  Backend API Docs: http://localhost:8000/docs
  Keycloak Admin:   http://localhost:8081  (admin / admin)
```

## Danach: Stack starten und stoppen

Nach dem ersten `make init` reicht für den normalen Alltag:

```bash
make dev-up     # Stack starten
make dev-down   # Stack stoppen (Daten bleiben)
```

## Login

Authentifizierung läuft über echtes Keycloak (Realm `dhbw`, Port 8081). Im Browser auf „Mit DHBW anmelden" klicken — Keycloak-Loginseite erscheint.

| Username | Rolle | Passwort |
|---|---|---|
| `test-teacher` | teacher | `TestTeacher12` |
| `dozent.demo` | teacher | `DevLocal1234!` |
| `admin.demo` | admin | `DevLocal1234!` |
| `student1.demo` | student | `DevLocal1234!` |
| `student2.demo` | student | `DevLocal1234!` |
| `student3.demo` | student | `DevLocal1234!` |
| `student4.demo` | student | `DevLocal1234!` |

### Keycloak Admin Console

Über `http://localhost:8081` erreichbar (admin / admin). Neue User anlegen: Realm `dhbw` → Users → Add user. Passwort muss mind. 12 Zeichen haben und darf nicht gleich Username oder E-Mail sein (Policy wie Prod).

## Verifikation

```bash
make health
```

Oder im Browser:

| Dienst | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API Docs | http://localhost:8000/docs |
| Backend Health | http://localhost:8000/health |
| Keycloak | http://localhost:8081 |

## Alle verfügbaren Make-Targets

### Bootstrap

| Befehl | Beschreibung |
|---|---|
| `make init` | **Erster Start:** Build + Migrate + Seed (einmalig) |
| `make env` | `.env` aus `.env.example` anlegen |
| `make secret` | Neuen Fernet-Key für `CREDENTIAL_ENCRYPTION_KEY` generieren |

### Normalbetrieb

| Befehl | Beschreibung |
|---|---|
| `make dev-up` | Stack starten (ohne Rebuild/Migrate/Seed) |
| `make dev-down` | Stack stoppen (Volumes bleiben) |
| `make dev-restart` | Alle Container neu starten |
| `make dev-restart-backend` | Nur Backend neu starten |
| `make dev-restart-worker` | Nur Worker neu starten |
| `make dev-restart-frontend` | Nur Frontend neu starten |
| `make dev-build` | Images neu bauen |
| `make dev-rebuild` | Kompletter Rebuild (`down` + `build --no-cache` + `up`) |
| `make dev-ps` | Container-Status anzeigen |

### Logs

| Befehl | Beschreibung |
|---|---|
| `make dev-logs` | Alle Logs verfolgen |
| `make dev-logs-backend` | Nur Backend |
| `make dev-logs-worker` | Nur Worker |
| `make dev-logs-frontend` | Nur Frontend |

### Shell-Zugriff

| Befehl | Beschreibung |
|---|---|
| `make shell-backend` | bash im Backend-Container |
| `make shell-worker` | bash im Worker-Container |
| `make shell-frontend` | sh im Frontend-Container |
| `make shell-db` | psql direkt in Postgres |

### Datenbank & Seed

| Befehl | Beschreibung |
|---|---|
| `make seed-dev` | Seed nochmal einspielen (idempotent) |
| `make migrate-dev` | Alembic-Migrationen ausführen |
| `make migration-create MSG="..."` | Neue Migration erstellen |
| `make migration-history` | Migrations-Historie anzeigen |
| `make migration-current` | Aktuelle Revision anzeigen |
| `make migration-downgrade` | Eine Revision zurück |
| `make db-reset-dev` | ⚠️ DB komplett löschen und neu migrieren |

### Status & Monitoring

| Befehl | Beschreibung |
|---|---|
| `make health` | Backend + Frontend per curl prüfen |
| `make status` | Container-Status (`docker compose ps`) |
| `make stats` | `docker stats` für alle Container |
| `make watch-dev` | Container-Status alle 2s aktualisieren |
| `make top` | Prozesse je Container anzeigen |

### Qualität (Backend)

| Befehl | Beschreibung |
|---|---|
| `make test-backend` | pytest |
| `make test-backend-cov` | pytest mit HTML-Coverage |
| `make lint-backend` | ruff check |
| `make lint-backend-fix` | ruff check --fix |
| `make format-backend` | ruff format |

### Aufräumen

| Befehl | Beschreibung |
|---|---|
| `make clean-dev` | ⚠️ `down -v` — entfernt alle Volumes |
| `make clean-all` | ⚠️ `down -v` + lokale Images löschen |
| `make prune` | ⚠️ `docker system prune -af --volumes` |

### Produktion (manuelle VM-Bootstrap — nur auf appstore-prod-01)

> Staging läuft ausschließlich über die Ansible CD-Pipeline (`infrastructure/ansible/`), nicht vom Developer-Laptop.

| Befehl | Beschreibung |
|---|---|
| `make prod-up` | Prod-Stack starten |
| `make prod-down` | Prod-Stack stoppen (Volumes bleiben) |
| `make prod-stop` | Container stoppen ohne entfernen |
| `make prod-restart SVC=backend` | Einen Prod-Service neu starten |
| `make prod-pull` | Images neu pullen + geänderte Container neu starten |
| `make prod-logs` | Prod-Logs verfolgen (oder `SVC=backend` für einen Dienst) |
| `make prod-ps` | Prod-Container + Health anzeigen |
| `make prod-migrate` | Alembic-Migrationen auf laufendem Prod-Backend |
| `make prod-seed` | Seed auf laufendem Prod-Backend |
| `make prod-reset` | ⚠️ Prod-Stack + alle Volumes löschen (irreversibel) |

### Self-hosted GitHub Actions Runner

| Befehl | Beschreibung |
|---|---|
| `make runner-up` | Runner starten (benötigt `GITHUB_ACCESS_TOKEN` in `.env`) |
| `make runner-down` | Runner-Container entfernen |
| `make runner-logs` | Runner-Logs verfolgen |
| `make runner-ps` | Runner-Container-Status |

## Was ist Simulation Mode?

Lokal laufen zwei Subsysteme als Fake — Keycloak läuft jetzt echt:

| Produktions-Dienst | Lokal |
|---|---|
| Keycloak (JWT-Auth) | **Echter Keycloak** auf Port 8081, Realm `dhbw` |
| OpenStack (Credential-Validierung + Ressourcen) | Statische Dummy-Daten |
| Kubernetes-Cluster (Pod-Deployments) | `FakeKube` (In-Memory) |

Der komplette Code-Pfad von HTTP-Request bis zum Worker-Task läuft durch — nur die letzten Netzwerkaufrufe gegen OpenStack und Kubernetes werden abgefangen.

Pod-Deployments über `FakeKube` generieren echte `terraform_outputs` mit Zugangsdaten, sodass „Meine Zugänge" im Frontend auch lokal funktioniert. Der In-Memory-State von FakeKube ist nach einem Worker-Neustart weg.

## Keycloak Realm — Hinweise

Der Realm wird beim allerersten Start aus `keycloak/dhbw-realm.json` importiert (Strategy: `IGNORE_EXISTING`). Änderungen an der Datei greifen erst nach `make clean-dev && make init`, da Keycloak einen vorhandenen Realm nicht überschreibt.

Wer den Realm manuell geändert hat (z.B. neuen User über die Admin Console angelegt) und den Stand in die JSON-Datei zurückschreiben will:

```bash
# Realm aus laufendem Keycloak exportieren
docker exec keycloak-sim /opt/keycloak/bin/kc.sh export \
  --file /tmp/dhbw-realm-export.json --realm dhbw
docker cp keycloak-sim:/tmp/dhbw-realm-export.json keycloak/dhbw-realm.json
```
