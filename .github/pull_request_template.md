## Zusammenfassung

<!-- Was ändert dieser PR und warum? 1–3 Sätze. -->

Closes #

**Art der Änderung:** <!-- feat | fix | infra | config | ci | docs | chore — bei Änderungen, die manuelle Schritte auf Staging/Produktion erfordern, zusätzlich "MANUELL" -->

**Betroffene Umgebungen:** <!-- dev | staging | prod | Hermes | Runner -->

## Prüfung

<!-- Wie wurde geprüft? Z. B. `make dev-up` + `make health`, `terraform plan`-Auszug, Staging-Lauf, Hermes-Report. -->

## Checkliste

<!--
Checkliste für Änderungs-PRs (Feature-/Fix-Branch → `dev`, Hotfix → `main`).
Release-PRs (`dev` oder `promote/*` → `main`) verwenden stattdessen
`.github/pull_request_template/release.md`.

Jeder Punkt wird abgehakt, bevor der PR gemergt werden kann. Der CI-Check
"PR Checklist" blockiert den Merge, solange hier noch ein offenes "- [ ]" steht.

Trifft ein Punkt nicht zu: mit "n/a" markieren UND abhaken, z. B.
- [x] n/a — Terraform: keine Änderung an infrastructure/terraform

Die reviewende Person prüft, dass die Häkchen stimmen, und bestätigt das mit
ihrem Approval. Terraform-Format und IaC-Scan laufen erst im Staging-Deploy
nach dem Merge; deshalb werden sie hier vorab lokal bestätigt.
-->

**Funktionale Eignung**

- [ ] Vollständigkeit: Alle Akzeptanzkriterien des verlinkten Issues sind umgesetzt; Abweichungen oder offene Punkte sind oben begründet
- [ ] Lokal verifiziert: Betroffener Stack startet (`make dev-up` bzw. passende Compose-Datei), alle Container sind healthy (`make health`) und der geänderte Ablauf funktioniert
- [ ] Terraform/Ansible: `terraform fmt -check -recursive` und `terraform validate` lokal grün; `terraform plan` geprüft, keine unbeabsichtigten `destroy`/`replace`

**Betrieb & Konfiguration**

- [ ] Konfiguration: Neue/geänderte Variablen in `.env.example`, `.env.staging.example` und `.secrets.template` sowie in `docs/*-setup.md` nachgezogen
- [ ] Konsistenz: Änderung in allen betroffenen Compose-Dateien (dev, staging, prod, moodle, hermes) konsistent; Image-Tags passen zur Umgebung
- [ ] Daten & Rollback: Keine Änderung löscht Volumes oder Daten ohne Migrations-/Backup-Plan; Rollback-Weg ist bekannt (`claude_docs/rollback/`)

**Sicherheit & Doku**

- [ ] Sicherheit: Keine Secrets im Diff; neue `.gitleaksignore`-Einträge begründet; neu exponierte Ports, Caddy-Routen oder Keycloak-Client-Änderungen bewusst geprüft
- [ ] Doku: `claude_docs/HANDOVER.md` aktualisiert; Topologie/Entscheidungen in `claude_docs/` nachgezogen, falls betroffen
