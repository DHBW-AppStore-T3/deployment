---
name: deploy-status
description: "Use when the user asks whether staging/prod is in sync with dev/main, what the latest deploy was, or whether it's safe to promote staging to prod. Triggers on: is staging up to date, what's the last deploy, can we promote to prod, deploy status."
---

# /deploy-status

Answers "is what's running the same as what's in git" for staging
(`dev`, automatic) and prod (`main`, via bump PRs and promotion PRs).
Everything runs on Kubernetes with Argo CD; use the `appstore` MCP
server (read-only, see `/verify-staging`). If its tools are missing,
say so and do not guess.

## Staging

A push to a component's `dev` triggers CI, then `k8s-bump.yml` writes
the image digest to `k8s/images/staging.yaml`, then Argo CD
(`staging-appstore`) rolls it out. So "is staging current" means:

- `github_runs(repo=<component>, branch="dev")` and
  `github_runs(repo="deployment", branch="dev", workflow="k8s-bump.yml")`: latest runs `success`?
- `rollout_status("staging")`: component `stale` means the pods still run an older digest than committed.
- `argocd_app("staging-appstore")`: Synced/Healthy?

A failed latest run means staging runs the *previous* successful
digest, not `dev` HEAD. Say that explicitly.

## Prod

Prod tracks `main`. `k8s-bump.yml` opens a bump PR (auto-merge) per
component digest in `k8s/images/prod.yaml`; chart/config changes reach
prod through a `dev` -> `main` promotion PR (`k8s/promote.sh`). To compare:

- `rollout_status("prod")` and `argocd_app("prod-appstore")` for what runs,
- `github_open_prs(repo="deployment")` for pending bump/promotion PRs,
- `git log --oneline origin/main..origin/dev` in `deployment` for what a promotion would bring.

## "Is it safe to promote staging to prod"

Not this skill's call. Report the facts (last healthy staging verdict
and its commit, CI state, open PRs, diff between `dev` and `main`)
and let the human decide. Prod promotion is a human-approval point.
