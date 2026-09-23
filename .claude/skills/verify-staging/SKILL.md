---
name: verify-staging
description: "Use after a PR is merged and staging has deployed — initiates Hermes' staging health check by posting a trigger comment on the merged PR, then reports the result. Triggered from /ship-feature Step 8. Triggers on: verify staging, check staging after deploy, did staging deploy correctly."
---

# /verify-staging

Called from `/ship-feature` after a human-merged PR has triggered the
staging deploy pipeline. Coordinates the staging verification via Hermes
(HARNESS.md System 2 + System 3).

## Kommunikationskanal: Dev-Agent → Hermes

Der Coding-Agent (Claude Code) hat keine direkte Discord-Verbindung.
Hermes hat Zugriff auf GitHub via `github-mcp-server` (aktuell noch
commented out in `deployment/agent/config.yaml` — aktivierbar sobald
`GITHUB_TOKEN` gesetzt ist). Bis dahin: Mensch fungiert als Relay.

**Protokoll:**

### Wenn github-mcp bei Hermes aktiviert ist (Normalfall)

Schritt 1 — Trigger-Comment auf den gemergten PR:
```bash
gh pr comment <PR-NUMBER> -R DHBW-AppStore-T3/<repo> \
  --body "@hermes /verify-staging — PR #<number> wurde gemerged, bitte Staging-Status prüfen und im Discord posten"
```

Schritt 2 — Hermes liest den Comment via GitHub-MCP, führt `/verify-staging`
auf Hermes-Seite aus, postet Ergebnis im Discord-Channel.

Schritt 3 — Warte auf Discord-Bestätigung (oder Hermes' GitHub-Comment
zurück auf den PR). Wenn nach 5 Minuten keine Antwort: Mensch bitten,
Hermes manuell zu fragen.

### Wenn github-mcp bei Hermes noch nicht aktiviert ist (aktueller Zustand)

Schritt 1 — Trigger-Comment trotzdem setzen (als Audit-Trail):
```bash
gh pr comment <PR-NUMBER> -R DHBW-AppStore-T3/<repo> \
  --body "Staging deploy ausgelöst. @hermes /verify-staging ausstehend — github-mcp noch nicht aktiviert, bitte manuell auf Discord anfragen."
```

Schritt 2 — Dem Menschen mitteilen:
> "PR ist gemerged, Staging deployt gerade. github-mcp bei Hermes ist noch nicht aktiviert — bitte Hermes auf Discord manuell bitten: `/verify-staging`. Sobald Hermes antwortet, bin ich für Prod-Freigabe bereit."

## Was Hermes beim /verify-staging prüft (Hermes-seitiger Skill)

Hermes führt auf seiner Seite aus:
1. `container_list` — alle Staging-Container running?
2. `container_inspect` — Health-Status jedes Containers
3. `container_logs --tail 50` — letzte Logs für jeden Container (nur wenn ein Container nicht `healthy`)
4. Ergebnis als Discord-Nachricht: "✅ Staging OK" oder "⚠️ <Container> unhealthy: <letzte Fehlerzeile>"

## Was dieser Skill NICHT tut

- Kein direkter SSH zu appstore-prod-01 oder dem Staging-Host
- Keine eigenständige Container-Inspektion (das ist Hermes' Job)
- Kein Weiterleiten an Prod — nach positivem Staging-Verify ist das
  System 5.2's zweites Gate: explizite menschliche Entscheidung

## Aktivierung github-mcp bei Hermes

Sobald `GITHUB_TOKEN` (PAT mit `repo` read access) in
`deployment/.env` gesetzt ist, in `deployment/agent/config.yaml` den
`github:` Block uncommentieren. Danach entfällt das manuelle
Discord-Relay komplett.
