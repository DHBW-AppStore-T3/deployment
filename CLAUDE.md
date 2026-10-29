# deployment

Teil der DHBW-AppStore-T3 Organisation — sechs eigenständige Repos, kein Monorepo.
Harness-Gesamtkonzept: https://github.com/DHBW-AppStore-T3/.github/blob/main/docs/HARNESS.md

- Übergabedokument (Ist-Zustand): `claude_docs/HANDOVER.md`
- README: Umgebungen, lokaler Start, Aufbau, CI
- Lokales Setup ab Null: `docs/dev-setup.md`; Staging/Produktion: `k8s/README.md`
- Architektur-Entscheidungen: `claude_docs/decisions/`
- Ops-Skills & Guardrail: `.claude/skills/`, `.claude/hooks/appstore-prod-guardrail.py`

## Skills
- `/deploy-status`, `/diagnose-production`, `/restart-service`
- Staging nach einem Push prüfen: `/verify-staging` (MCP-Server `appstore`: `claude mcp add --transport http appstore https://appstore-mcp-staging.t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site/mcp`, dann `/mcp` → Authenticate)

## Befehle
- Lokal: `make init` (einmalig), `make dev-up`, `make dev-down`, `make health`, `make help`
- Umgebung rendern wie Argo CD (braucht helm, PyYAML): `python3 k8s/tests/render_env.py <staging|prod> out.yaml`
