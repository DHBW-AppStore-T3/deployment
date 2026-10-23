# Deployment

Dieses Repository hält alles zusammen, was die Plattform zum Laufen braucht: die
Kubernetes-Manifeste und Helm-Charts (`k8s/`, ausgerollt per Argo CD für Staging
und Prod), die lokale Dev-Compose-Datei, den Makefile, den Keycloak-Realm und die
Seed-Daten.

Die Anwendung selbst liegt in eigenen Repositories (`backend`, `frontend`,
`worker`). Hier wird nichts gebaut, was dort entsteht — hier wird es
zusammengesetzt, konfiguriert und ausgerollt.

## Setup-Anleitungen

- [Lokales Dev Setup](docs/dev-setup.md)

## Schnellstart

Kein Dienst wird einzeln gestartet. Alles läuft über den Makefile in diesem
Verzeichnis:

```bash
cd deployment
make init      # .env anlegen, Stack starten, migrieren, Seed-Daten laden
make urls      # alle Dev-URLs auf einen Blick
make help      # sämtliche Targets mit Beschreibung
```

Die wichtigsten im Alltag:

| Befehl | Wirkung |
|---|---|
| `make dev-up` / `make dev-down` | Stack starten und stoppen (Volumes bleiben) |
| `make dev-logs-backend` | Logs verfolgen; auch `-frontend`, `-worker`, `-keycloak` |
| `make shell-backend` | Shell im Container; auch `shell-worker`, `shell-frontend`, `shell-db` |
| `make dev-restart-worker` | Neustart, wenn der Hot-Reload nicht greift — etwa bei Celery-Tasks |
| `make migrate-dev` | Alembic-Migrationen anwenden |
| `make migration-create MSG="..."` | Neue Migration erzeugen |
| `make seed-data` | Seed-Daten laden; idempotent, gefahrlos wiederholbar |
| `make health` | Backend, Frontend und Keycloak anpingen |

## Umgebungen

| Umgebung | Wie sie ausgerollt wird |
|---|---|
| dev (lokal) | `docker-compose.dev.yml` via `make dev-up` |
| staging | Kubernetes, Argo CD verfolgt Branch `dev` |
| prod | Kubernetes, Argo CD verfolgt Branch `main` |

## Aufbau

```text
deployment/
├── k8s/                      # Charts, Argo-CD-Apps, Umgebungswerte, Image-Digests
├── Makefile                  # Einstiegspunkt für alles Lokale
├── docker-compose.dev.yml    # lokaler Dev-Stack
├── keycloak/                 # Realm-Export und dessen Template
├── seed/                     # Seed-Skript, Kurse, App-Beschreibungen
├── docs/                     # Dev-Setup
└── .github/workflows/        # k8s-bump, k8s-chart, secret-scan
```
