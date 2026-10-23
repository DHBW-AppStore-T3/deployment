---
name: diagnose-production
description: "Use when something on prod seems broken or the user asks to check production status — a fixed diagnostic order (health, then pods and logs, then recent rollouts, then cluster) instead of guessing where to look first. Triggers on: production down, deploy broken, pod crashing, is prod healthy."
---

# /diagnose-production

Fixed diagnostic order for the prod environment (namespace
`appstore-prod`, Argo apps `prod-*`). Uses the read-only `appstore`
MCP server (see `/verify-staging` for setup). If its tools are
missing, say so; do not guess. Follow the steps in order.

## Step 1 - Health

`health("prod")` (what users see) and `argocd_app("prod-appstore")`
(sync/health message, unhealthy resources). All healthy and Synced
-> go to Step 3, not Step 2.

## Step 2 - Pods and logs (only for problems from Step 1)

`pods("appstore-prod")` -> look at `problems` (CrashLoopBackOff,
ImagePullBackOff, not Ready). Then `events("appstore-prod")` and
`logs("appstore-prod", <pod>, previous=true)` for the affected pod.
Look for the first occurrence of the actual error, not the last line.
`cnpg_clusters()` if the database is involved.

## Step 3 - Recent rollouts (only if Steps 1-2 found nothing)

`rollout_status("prod")`: committed digest vs running digest
(`stale` = the new digest never reached the pods). Check
`github_runs(repo="deployment", workflow="k8s-bump.yml")` and
`github_open_prs(repo="deployment")` for failed or stuck bump PRs
(workflow runs can sit on `action_required`).

## Step 4 - Cluster (only if Steps 1-3 explained nothing)

Node, storage, ingress or certificate problems on the k3s cluster
are the least common cause. Check Argo apps `prod-platform` /
`cnpg`, then ask the human for node-level access.

## Reporting back

State which step found the issue and why earlier steps didn't.

## Before proposing a fix

Root cause first, not a symptom patch - see
[obra/superpowers' systematic-debugging skill](https://github.com/obra/superpowers/blob/main/skills/systematic-debugging/SKILL.md):
"NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST". A restart that
"fixes" a symptom without an identified root cause is a coin flip;
say so explicitly if you propose one anyway.
