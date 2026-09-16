---
name: diagnose-production
description: "Use when something on appstore-prod-01 seems broken or the user asks to check production status — a fixed diagnostic order (health, then logs, then deployments, then infrastructure) instead of guessing where to look first. Triggers on: production down, deploy broken, container crashing, is prod healthy."
---

# /diagnose-production

Fixed diagnostic order for `appstore-prod-01` (HARNESS.md System 2).
Follow the steps in order — do not skip ahead to infrastructure checks
before ruling out the cheaper, faster ones.

## Step 1 — Health

```bash
ssh appstore-vm "sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
```

Read every row. `(unhealthy)` or `Restarting` on any container is the
finding — stop here and go to Step 2 for that specific container. All
`Up` and no `(unhealthy)` means move to Step 3, not Step 2.

## Step 2 — Logs (only for containers flagged unhealthy in Step 1)

```bash
ssh appstore-vm "sudo docker logs <container-name> --tail 100"
```

Look for the actual error, not just the last line — a crash loop
often prints a full traceback once and then repeats a short "exiting"
message on every restart. Scroll to the first occurrence, not the
most recent one.

**Guardrail reminder:** this hook
(`deployment/.claude/hooks/appstore-prod-guardrail.py`) allows `ps`,
`logs`, `inspect`, `images`, `network`, `version`, `info` against this
host. It blocks `restart`/`stop`/`rm`/`compose`/etc. — if the
diagnosis points to "just restart it", stop and use
`/restart-service` instead of trying to route around the block.

## Step 3 — Recent deployments (only if Steps 1–2 found nothing)

```bash
ssh appstore-vm "cd /opt/app-store/deployment && sudo git log --oneline -10"
```

Compare against what's actually running — does `HEAD` match what you'd
expect from the last known-good state? A silent `main` fast-forward
that never got `make prod-up`'d looks identical to "nothing changed"
until you check both.

## Step 4 — Infrastructure (only if Steps 1–3 explained nothing)

OpenStack-level issues (quota exhausted, floating IP dropped, the VM
itself in an error state) are the least common cause and the most
expensive to check — only reach here when container health, logs, and
deploy history all came back clean. No OpenStack MCP is wired up yet
(HARNESS.md status: openstack-mcp planned, not connected) — for now
this step means logging into https://newstack.dhbw.cloud manually.

## Reporting back

State which step found the issue and why the earlier steps didn't —
"Step 1 showed `podman-mcp-prod` restarting; Step 2's logs showed
`PrivilegedIntentsRequired`" is useful, "something's wrong with
Discord" is not.

## Before proposing a fix

Root cause first, not a symptom patch — see
[obra/superpowers' systematic-debugging skill](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md):
"NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST". The four `podman-mcp`
bugs in `HARNESS.md` System 2.1 were each found this way — reading the
actual upstream source (`pkg/podman/podman_cli.go`,
`pkg/podman-mcp-server/cmd/root.go`) rather than guessing from an error
string. A restart that "fixes" a symptom without an identified root
cause is a coin flip, not a diagnosis — say so explicitly if you're
proposing one anyway under time pressure.
