---
name: restart-service
description: "Use ONLY after /diagnose-production has identified a specific unhealthy container on appstore-prod-01 AND a human has confirmed a restart is the right fix. This is the one write action this skill set permits — everything else on that host stays read-only. Triggers on: restart the container, restart backend/frontend/worker on prod."
---

# /restart-service

The single permitted write action against `appstore-prod-01`
(HARNESS.md System 3.2/5.4). Everything else — `rm`, `stop`, `compose
down`, image operations — is blocked by
`deployment/.claude/hooks/appstore-prod-guardrail.py`, which this
skill does not attempt to route around.

## Preconditions — check both before running anything

1. **`/diagnose-production` has already identified the specific
   container.** If you haven't run it this session, run it first —
   this skill is not a shortcut past diagnosis.
2. **A human has confirmed the restart.** This is a state-changing
   action against a live production system with real user deployments
   — do not restart a container on your own initiative because a log
   line looked concerning. Ask, then act.

## Allowed restart targets and command

Only these service names, matching `docker-compose.prod.yml` /
`docker-compose.podman-mcp.yml` / `docker-compose.moodle.yml` container
names:

```
backend-prod, worker-prod, frontend-prod, caddy-prod, keycloak-prod,
podman-mcp-prod, moodle-prod
```

`hermes-agent-prod` is no longer a valid target here — since
deployment#49, `hermes-agent` runs on its own dedicated VM
(`hermes-dhbw-appstore`), not on `appstore-prod-01`. A restart of
Hermes itself is `docker restart hermes-agent` on that host, outside
this guardrail's scope.

**Not** `postgres-prod`, `postgres-tfstate-prod`,
`keycloak-postgres-prod`, `rabbitmq-prod`, `redis-prod`,
`moodle-db-prod` — restarting a stateful data store is not a
"restart the service" action, it risks in-flight transaction loss and
needs its own explicit conversation, not this skill.

```bash
ssh appstore-vm "sudo docker restart <container-name>"
```

Do not use `docker compose restart` — the guardrail hook blocks
`compose` wholesale (see the hook's comments for why: it can't
distinguish `compose restart` from `compose down` without parsing
flags it deliberately doesn't parse). Plain `docker restart
<container>` is the allowed equivalent for a single named container.

## After restarting

Re-run the relevant part of `/diagnose-production` (Step 1: is it
`Up` and not immediately `Restarting` again) — a restart that doesn't
hold is a different, probably more serious problem than the one that
prompted the restart.
