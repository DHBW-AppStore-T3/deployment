# deployment

Teil der DHBW-AppStore-T3 Organisation — sechs eigenständige Repos, kein Monorepo.
Harness-Gesamtkonzept: siehe https://github.com/DHBW-AppStore-T3/.github/blob/main/docs/HARNESS.md

Details zu diesem Repo:
- Lebendes Übergabedokument: `claude_docs/HANDOVER.md` (zwingend zu Beginn jeder Session lesen und vor Session-Ende aktualisieren)
- Architektur-Entscheidungen: `claude_docs/decisions/`
- Ops-Skills & Guardrails: `.claude/skills/` und `.claude/hooks/appstore-prod-guardrail.py`

## Repo-Lokale Skills & Befehle
- Lokale Skills: `/deploy-status`, `/diagnose-production`, `/restart-service`
- Staging nach einem Push prüfen: `/verify-staging` (MCP-Server `appstore`, Repo appstore-mcp: `claude mcp add --transport http appstore https://appstore-mcp-staging.t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site/mcp`, dann `/mcp` -> Authenticate). Hermes ist abgelöst.

