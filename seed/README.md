# Seed-Daten

`seed_sim.py` füllt den lokalen Stack (`make seed-dev`, Teil von `make init`). Es kopiert sich per `docker compose cp` in den Backend-Container und ruft `app.cli` des Backends auf. Idempotent.

## Inhalt

- **Nutzer:** alle Nutzer des Keycloak-Realms `dhbw` mit ihren Keycloak-IDs in die Datenbank (`dozent.demo`, `admin.demo`, `student1.demo` … `student4.demo`, `test-teacher`), dazu die Konten für den `X-Dev-User`-Header: `prof@dhbw.de` (Lehrender), `student@dhbw.de`, `admin@dhbw.de`.
- **Kurs:** `WI SE B 23`, alle Lehrenden und Studierenden zugeordnet.
- **Apps** (registriert, eingereicht und freigegeben, Runtime `kubernetes`, Repositories unter `github.com/DHBW-AppStore-T3`):

| App | Version |
|---|---|
| Online-IDE | v2.2.0 |
| Web-LaTeX | v2.0.5 |
| Jupyter-Notebook | v2.0.2 |
| pgAdmin | v2.0.3 |
| template-app | v2.0.2 |

Passwörter der Keycloak-Nutzer stehen in `keycloak/dhbw-realm.json` (`DevLocal1234!`, `test-teacher`: `TestTeacher12`).

## Voraussetzungen

Laufender Stack (`make dev-up`), Internetzugang zu `github.com` (das Backend liest die App-Repositories beim Registrieren), Migrationen angewendet.

## Staging

Auf Staging legt der Helm-Hook-Job `charts/appstore/templates/seed-job.yaml` nach jedem Sync dieselbe Art Demo-Daten an (`python -m app.cli seed`, Werte `appstore.seed.*` in `k8s/environments/staging.yaml`). Auf Produktion ist er aus.
