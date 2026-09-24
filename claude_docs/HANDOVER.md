# Handover — Deployment

Lebendes Übergabedokument gemäß [HARNESS.md](https://github.com/DHBW-AppStore-T3/.github/blob/main/docs/HARNESS.md) Abschnitt 1.2.
Jede Session liest dieses Dokument zu Beginn und aktualisiert es vor dem Abschluss.

---

## 1. Status & Fokus

- **Die 2 Flows (Harness Engineering):**
  - **Flow 1 (`/user-story`):** Spezifikations- und Klärungsdialog zur Issue-Erstellung.
  - **Flow 2 (`/harness-workflow`):** Autonome Umsetzung via `dev`-Trunk -> TDD -> PR auf `dev` -> CI grün -> Auto-Merge auf `dev` -> Staging Deploy -> Hermes Discord Statusmeldung. Push auf `main` bleibt strikt menschlich + Test Coverage Gate.
- **Staging CI/CD:** `staging.yml` triggert nun automatisch bei Push/Merge auf `dev` (Self-Hosted Runner). Nach Abschluss führt `notify_staging_health.py` den Health-Check durch und meldet Status & System Health (GUT / SCHLECHT) nach Discord.
- **Produktions-VM:** `appstore-prod-01` läuft auf OpenStack (`ma_wwi_24sea_appstore_g3`), 10 Container (caddy, frontend, backend, worker, keycloak, 2× postgres, rabbitmq, redis, tfstate-postgres).
- **Hermes Agent & MCP (deployment#49 — umgezogen):** `hermes-agent` läuft seit dieser Session nicht mehr als Overlay auf `appstore-prod-01`, sondern auf einer eigenen VM (`hermes-dhbw-appstore`, `2001:7c0:1b20:c913:1::342`, provisioniert per `hermes.yml`-Workflow). `podman-mcp` läuft stattdessen einzeln auf jeder Ziel-VM (`appstore-prod-01`, `staging-dhbw-appstore`, `ci-dhbw-appstore`), erreichbar von der Hermes-VM über MCP/TCP:8080 (Security-Group-scoped). Details: `claude_docs/decisions/2026-hermes-dedicated-vm.md`.
- **Guardrails:** PreToolUse-Guardrail (`deployment/.claude/hooks/appstore-prod-guardrail.py`) schützt direkten SSH-Zugriff gegen unbefugte Docker-Befehle (nur `docker restart <name>` aus `RESTART_ALLOWLIST` erlaubt).

---

## 2. In Arbeit & Nächste Schritte

- [x] Reengineering auf 2 Flows im Deployment-Repo: `staging.yml` auf `dev`-Trigger umgestellt.
- [x] Staging Health-Check & Discord-Notification (`notify_staging_health.py`) implementiert.
- [ ] **GitHub MCP & OpenStack MCP aktivieren:** Liegen vorkonfiguriert in `agent/config.yaml`, warten auf Read-Only-PAT bzw. `clouds.yaml`.
- [x] **deployment#49 — Hermes auf eigene VM:** `envs/hermes/` provisioniert (`hermes-dhbw-appstore`, `2001:7c0:1b20:c913:1::342`), `HERMES_VM_IPV6`-Secret gesetzt. `podman-mcp`-Rollout auf prod/staging/ci sowie `hermes-agent`-Start liefen zum Sessionende noch (workflow_dispatch, `.github/workflows/hermes.yml`) — Status im nächsten Handover prüfen. **Offen:** `HERMES_ENV_FILE`-Secret (Discord-Bot-Token, Gemini-Key) noch nicht gesetzt — kann nicht aus `PRODUCTION_ENV_FILE` übernommen werden (GitHub-Secrets sind write-only), braucht einen Menschen mit den echten Credentials. Ohne dieses Secret bleibt `hermes-agent` nicht startbar.
- [x] **Moodle-Integration Prod-CI/CD:** `production.yml`/`production.yml`-Workflow bekommen denselben `moodle_enabled`-Mechanismus wie `staging.yml` (deployment#43, Task 1-4), seit 2026-09-24 Default-`true` statt Opt-in.
- [x] **Task 5 (Staging-Regressionscheck):** `moodle-prod`/`moodle-db-prod` laufen healthy, App-Ebene bestätigt.
- [ ] **TLS für `MOODLE_HOSTNAME` auf Staging:** Caddy scheitert an der ACME-Order-Finalisierung bei `certificates.dhbw.cloud`, siehe Historie unten — vermutlich CA-seitiger Bug, nächster Ansatzpunkt: Caddy-eigenes ACME-Zertifikats-Handling für diesen einen Hostnamen debuggen (evtl. `on_demand_tls` statt statischer Domain-Liste, oder direkter Kontakt zum HARICA/DHBW-Cloud-Betreiber).
- [ ] **Task 6 (Prod-Deploy + IPv6-Rückgabe):** weiterhin menschlich zu triggern — letzter Schritt der gesamten backend#9/frontend#9/self-service-ui#5/deployment#43-Serie.

---

## 3. Bekannte Fallstricke & Blocker

1. **Discord Gateway Intents:** `PrivilegedIntentsRequired` tritt auf, wenn "Message Content Intent" im Discord Developer Portal nicht aktiviert ist.
2. **`podman-mcp` Container:** Braucht `stdin_open: true` in Compose, da `cmd.Execute()` sonst EOF erhält und crasht; Symlink `podman -> docker` und `--podman-impl cli` sind im Dockerfile erzwungen.
3. **Hermes Reconnect:** Hermes verbindet sich nur beim Start mit MCPs — `podman-mcp` muss vor Hermes gesund sein (`depends_on: condition: service_healthy`).
4. **Staging Runner:** Muss Zugriff auf den `tfstate-postgres`-Container im internen Netzwerk haben.
5. **Menschliches Gate für Produktion:** Kein automatisches Deployment nach Prod; Push auf `main` ist rein menschlich und testabdeckungs-gesichert.

---

## 4. Letzte Übergaben (Historie)

- **2026-09-24 (deployment#49 — Hermes-Umzug auf eigene VM):** PR #51 (`dev`) und #52 (`dev`→`main`) gemergt. **Zwei echte Stolpersteine dabei entdeckt, nicht nur der geplante Umzug:**
  1. **`dev` hat aktuell kein PR-Gate:** kein Branch-Protection, kein `pull_request`-Trigger gegen `dev` (`secret-scan.yml` läuft nur gegen `main`). PR #51 wurde deshalb ohne wartbaren CI-Check gemergt — abweichend vom in Abschnitt 1 beschriebenen Flow 2 ("PR auf dev -> CI grün"). Nicht behoben in dieser Session (auf Wunsch), nur dokumentiert — nächste Session sollte klären, ob das gewollt ist oder ob `dev` ein eigenes leichtgewichtiges Gate braucht.
  2. **`main` war 14 Commits hinter `dev`**, inklusive eines Commits (`f5cb796`, PR #42), der auf `dev` nie ankam und beim Promote-PR echte Konflikte auslöste (ältere, bereits durch #45/#46/#48 überholte `moodle_enabled`-Logik). Aufgelöst zugunsten von `dev`s neuerem Stand, per Merge in beide Richtungen (`main`→`dev`, dann `dev`→`main`), nicht nur im PR weggeklickt.
  3. Der Merge auf `dev` brach `staging.yml`/`production.yml` kurzzeitig (`terraform plan` schlug fehl, da `hermes_vm_ipv6` ohne `TF_VAR_hermes_vm_ipv6`/Secret keinen Wert hatte) — Ursache: `.github/workflows/hermes.yml` (neu) ist erst nach dem Merge auf `main` überhaupt per `workflow_dispatch` ansprechbar (GitHub registriert das nur vom Default-Branch), also ließ sich die Hermes-VM nicht vor dem `main`-Merge provisionieren. Nach Merge sofort `provision-hermes-vm` gefahren, `HERMES_VM_IPV6`-Secret gesetzt, beide Deploys liefen danach wieder grün.
  4. Direkter SSH-Zugriff auf alle drei Ziel-VMs sowie auf den `tfstate-postgres`-Backend war aus dieser Session heraus nicht erreichbar (Netzwerk-Scoping, keine Berechtigungsfrage) — deshalb lief die komplette Provisionierung/Rollout über den Self-Hosted-Runner (`ci-dhbw-appstore`) statt direkt.
- **2026-09-24 (deployment#43 Task 5 — Staging-Live-Verifikation, Moodle jetzt Default-On):** Auf expliziten Wunsch `moodle_enabled` von Opt-in auf Default-`true` umgestellt (PR #45), zwei Nachbesserungen nötig, bis es auf einem echten Push wirklich griff (PR #46, #48 — `${{ inputs.moodle_enabled != false }}` allein reichte nicht: GitHub Actions liefert bei `push`-Events und bei API/CLI-`workflow_dispatch` ohne explizites `-f` keinen brauchbaren `inputs.moodle_enabled`-Wert, weder `null` noch den YAML-`default`; robuste Lösung war der Shell-Fallback `${MOODLE_ENABLED:-true}` statt `:-false`). `STAGING_ENV_FILE`-Secret um `MOODLE_HOSTNAME`/`MOODLE_DB_PASSWORD`/`MOODLE_REPO_PATH` ergänzt (fehlten komplett, hätten jeden Deploy mit Moodle-Default-On blockiert). `moodle-prod`/`moodle-db-prod` laufen jetzt healthy auf Staging, App-Ebene per internem Test bestätigt (Apache/PHP antworten, korrekter `install.php`-Redirect für frische Instanz). **Offenes Problem:** Caddy bekommt für den neuen `MOODLE_HOSTNAME` (`moodle-staging.…`) kein TLS-Zertifikat von `certificates.dhbw.cloud` (HARICA) — DNS-01-Autorisierung wird wiederholt als `valid` bestätigt, Order bleibt bei der Finalisierung trotzdem `pending`. Reproduziert über 8+ Versuche, auch nach Bereinigung verwaister `_acme-challenge`-TXT-Records (die von den ersten fehlgeschlagenen Versuchen liegen geblieben waren — Caddy räumt sie bei einem `finalizing order`-Fehler nicht auf). Sieht nach einem serverseitigen State-Sync-Bug bei `certificates.dhbw.cloud` zwischen dessen `authz`- und `order`-Objekten aus, nicht nach einem Konfigurationsfehler hier — die bestehende `staging.s242437-…`-Domain im selben Caddy-Prozess, derselben Zone, demselben TSIG-Key hat ihr Zertifikat ohne Probleme. Moodle bleibt bis zur Klärung ohne eigenes TLS erreichbar (nur intern/HTTP-301, kein Browser-Zugriff über den öffentlichen Hostnamen). Nicht weiterverfolgt in dieser Session — nächste Session sollte zuerst hier ansetzen, bevor ein echter Browser-LTI-Test möglich ist.
- **2026-09-24 (deployment#43 Task 1-4):** `docker-compose.dev.yml` um LTI13/Handoff-Env + `host.docker.internal` erweitert (backend#9-Kontrakt lokal testbar). `production.yml`/`production.yml`-Workflow um denselben `moodle_enabled`-Opt-in wie `staging.yml` ergänzt (compose_files, bedingte Klon/Chown-Tasks, `workflow_dispatch`-Input). Task 6 (Live-Prod-Deploy + IPv6-Rückgabe) weiterhin explizit menschlichem Trigger überlassen — letzter Schritt der gesamten backend#9/frontend#9/self-service-ui#5/deployment#43-Serie.
- **2026-09-18 (Harness 2-Flow Reengineering):** `staging.yml` auf `dev`-Trunk umgestellt; Health-Check und Discord-Benachrichtigung (`notify_staging_health.py`) nach Staging-Deployment integriert; `HANDOVER.md` aktualisiert.
- **2026-09-17:** Universelle Skills (`code-reviewer`, `/tdd`, `/ship-feature`) ins `.github`-Repo umgezogen. Wochenlogs abgelöst durch dieses lebende Übergabedokument (#33).
- **2026-09-16:** PreToolUse-Guardrail (`appstore-prod-guardrail.py`) für direkten SSH-Zugriff implementiert; `code-reviewer`-Agent adaptiert; Staging-Runner an Worker-Netzwerk angebunden (#14).
- **2026-09-15:** Hermes Agent und `podman-mcp` live auf `appstore-prod-01` gebracht; Discord-Integration aufgesetzt; Branch-Protection org-weit aktiviert; Remotes auf `DHBW-AppStore-T3` korrigiert.
