---
name: restart-service
description: "Use ONLY after /diagnose-production has identified a specific unhealthy workload on prod AND a human has confirmed a restart is the right fix. Triggers on: restart the pod/deployment, restart backend/frontend/worker on prod."
---

# /restart-service

The appstore MCP server is read-only, so a restart is a command the
human runs (or explicitly approves you to run) with cluster access.
It is the only write action this skill set proposes.

## Preconditions - check both before running anything

1. **`/diagnose-production` has already identified the specific
   workload.** This skill is not a shortcut past diagnosis.
2. **A human has confirmed the restart.** Prod serves real users;
   do not restart on your own initiative because a log line looked
   concerning. Ask, then act.

## Allowed targets and command

Stateless Deployments in `appstore-prod` only (backend, worker,
worker-pods, frontend, self-service-ui, moodle-web, keycloak):

```bash
kubectl -n appstore-prod rollout restart deployment/<name>
kubectl -n appstore-prod rollout status deployment/<name>
```

**Not** the CNPG database (`postgres-cluster` pods), Argo CD, or
anything cluster-wide: restarting a stateful store risks in-flight
transactions and needs its own explicit conversation. Do not delete
pods or scale to zero.

## After restarting

Re-run Step 1-2 of `/diagnose-production`. A restart that does not
hold (pod back in CrashLoopBackOff) is a different, probably more
serious problem than the one that prompted it.
