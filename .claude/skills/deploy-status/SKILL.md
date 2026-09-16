---
name: deploy-status
description: "Use when the user asks whether staging/prod is in sync with main, what the latest deploy was, or whether it's safe to promote staging to prod. Triggers on: is staging up to date, what's the last deploy, can we promote to prod, deploy status."
---

# /deploy-status

Answers "is what's running the same as what's in `main`" — for
staging (auto-deployed) and prod (manually promoted) separately, per
HARNESS.md System 5.1's chain.

## Staging

Staging deploys automatically on every push to `main`
(`.github/workflows/staging.yml` / `.forgejo/workflows/staging.yml`).
So "is staging current" is really "did the last workflow run
succeed":

```bash
gh run list --repo DHBW-AppStore-T3/deployment --workflow staging.yml --limit 5
```

A `failure` on the most recent run means staging is running whatever
the *previous* successful run deployed, not `main` HEAD — say that
explicitly, don't just report the run status.

## Prod

No automatic trigger exists for prod (deliberate, HARNESS.md 5.1) — so
"is prod current" means comparing the deployed commit against `main`
by hand:

```bash
ssh appstore-vm "cd /opt/app-store/deployment && sudo git log --oneline -1"
git -C deployment log --oneline origin/main -1
```

If these differ, prod is behind `main` by however many commits sit
between them — list them (`git log --oneline <prod-sha>..origin/main`)
so the user sees what would actually change on a promotion, not just
that a gap exists.

## "Is it safe to promote staging to prod"

Not this skill's call to make alone — report the facts
(staging's last successful deploy commit, whether that commit's CI
was fully green, how far behind prod currently is) and let the human
decide. HARNESS.md 5.2: prod promotion is a human-freigabe point,
this skill informs that decision, it doesn't replace it.
