# Handover — Deployment

Lebendes Übergabedokument gemäß [HARNESS.md](https://github.com/DHBW-AppStore-T3/.github/blob/main/docs/HARNESS.md) Abschnitt 1.2.
Jede Session liest dieses Dokument zu Beginn und aktualisiert es vor dem Abschluss.

---

## 1. Status & Fokus

- **Die 2 Flows (Harness Engineering):**
  - **Flow 1 (`/user-story`):** Spezifikations- und Klärungsdialog zur Issue-Erstellung.
  - **Flow 2 (`/harness-workflow`):** Autonome Umsetzung via `dev`-Trunk -> TDD -> PR auf `dev` -> CI grün -> Auto-Merge auf `dev` -> Staging Deploy -> Hermes Discord Statusmeldung. Push auf `main` bleibt strikt menschlich + Test Coverage Gate.
- **Staging CI/CD:** `staging.yml` triggert nun automatisch bei Push/Merge auf `dev` (Self-Hosted Runner). Nach Abschluss führt `notify_staging_health.py` den Health-Check durch und meldet Status & System Health (GUT / SCHLECHT) nach Discord.
- **Produktions-VM:** `appstore-prod-01` läuft auf OpenStack (`ma_wwi_24sea_appstore_g3`), 10 Container (nginx, frontend, backend, worker, keycloak, 2× postgres, rabbitmq, redis, tfstate-postgres).
- **Hermes Agent & MCP:** `hermes-agent-prod` und `podman-mcp-prod` laufen im Docker-Netzwerk auf der VM. Discord-Integration ist aktiv (Allowlist-gesichert).
- **Guardrails:** PreToolUse-Guardrail (`deployment/.claude/hooks/appstore-prod-guardrail.py`) schützt direkten SSH-Zugriff gegen unbefugte Docker-Befehle (nur `docker restart <name>` aus `RESTART_ALLOWLIST` erlaubt).

---

## 2. In Arbeit & Nächste Schritte

- [x] Reengineering auf 2 Flows im Deployment-Repo: `staging.yml` auf `dev`-Trigger umgestellt.
- [x] Staging Health-Check & Discord-Notification (`notify_staging_health.py`) implementiert.
- [ ] **GitHub MCP & OpenStack MCP aktivieren:** Liegen vorkonfiguriert in `agent/config.yaml`, warten auf Read-Only-PAT bzw. `clouds.yaml`.
- [ ] **Moodle-Integration:** Feinabstimmung von `docker-compose.moodle.yml` auf Staging/Prod.

---

## 3. Bekannte Fallstricke & Blocker

1. **Discord Gateway Intents:** `PrivilegedIntentsRequired` tritt auf, wenn "Message Content Intent" im Discord Developer Portal nicht aktiviert ist.
2. **`podman-mcp` Container:** Braucht `stdin_open: true` in Compose, da `cmd.Execute()` sonst EOF erhält und crasht; Symlink `podman -> docker` und `--podman-impl cli` sind im Dockerfile erzwungen.
3. **Hermes Reconnect:** Hermes verbindet sich nur beim Start mit MCPs — `podman-mcp` muss vor Hermes gesund sein (`depends_on: condition: service_healthy`).
4. **Staging Runner:** Muss Zugriff auf den `tfstate-postgres`-Container im internen Netzwerk haben.
5. **Menschliches Gate für Produktion:** Kein automatisches Deployment nach Prod; Push auf `main` ist rein menschlich und testabdeckungs-gesichert.

---

## 4. Letzte Übergaben (Historie)

- **2026-09-18 (Harness 2-Flow Reengineering):** `staging.yml` auf `dev`-Trunk umgestellt; Health-Check und Discord-Benachrichtigung (`notify_staging_health.py`) nach Staging-Deployment integriert; `HANDOVER.md` aktualisiert.
- **2026-09-17:** Universelle Skills (`code-reviewer`, `/tdd`, `/ship-feature`) ins `.github`-Repo umgezogen. Wochenlogs abgelöst durch dieses lebende Übergabedokument (#33).
- **2026-09-16:** PreToolUse-Guardrail (`appstore-prod-guardrail.py`) für direkten SSH-Zugriff implementiert; `code-reviewer`-Agent adaptiert; Staging-Runner an Worker-Netzwerk angebunden (#14).
- **2026-09-15:** Hermes Agent und `podman-mcp` live auf `appstore-prod-01` gebracht; Discord-Integration aufgesetzt; Branch-Protection org-weit aktiviert; Remotes auf `DHBW-AppStore-T3` korrigiert.
