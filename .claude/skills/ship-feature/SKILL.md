---
name: ship-feature
description: "Use when the user asks to implement and ship a feature or fix end-to-end — walks the HARNESS.md System 5 chain (branch, TDD loop, PR into dev, CI gate). Merges autonomously into dev (→ staging) once CI is green; stops for human approval before main (→ prod). Triggers on: implement and ship this, build and merge this feature, ship this fix."
---

# /ship-feature

Walks HARNESS.md System 5.1's chain end to end, in one repo of the
six. This skill is the connective tissue between System 1
(`claude_docs/` — read before writing code), System 4 (the TDD loop),
and System 3.1 (branch protection, already enforced server-side).

## The chain

```
1. Read claude_docs/                    — architecture, known decisions, debugging notes
                                           for the repo you're changing. Don't skip this
                                           even for a "small" change — claude_docs/log/
                                           exists specifically to catch repeat mistakes.
2. Branch from an up-to-date main        — git fetch origin main, branch -f main
                                           origin/main, THEN branch off main. Skipping the
                                           fetch/branch -f step was the actual cause of two
                                           real merge conflicts in this repo's history
                                           (deployment claude_docs/log/2026-W38.md) —
                                           don't repeat it.
3. TDD loop (System 4)                  — failing test → minimal implementation → green →
                                           refactor → full suite. Do not skip to "looks
                                           right" without a red test first.
4. Open a PR targeting `dev`
5. Wait for CI (required status checks) — do not merge before checks resolve. If a check
                                           fails, fix it or explain why it's a
                                           pre-existing, unrelated failure (see the
                                           Security-check precedent below) — never merge
                                           past a required check.
6. Merge into dev autonomously           — `gh pr merge --squash --delete-branch` once
                                           CI is green. dev → staging deploys automatically.
7. Call /verify-staging                  — Hermes prüft Staging, postet auf Discord.
8. STOP before main                      — main → prod. This is System 5.2's second gate.
                                           Never merge to main yourself. Report staging
                                           status and wait for explicit human approval.
```

## Merge behaviour by target branch

| Target | Deploys to | Who merges | Gate |
|---|---|---|---|
| `dev` | Staging | Agent (`gh pr merge --squash --delete-branch`) | CI green |
| `main` | Prod | Human only — STOP | Explicit approval required |

**Why dev is autonomous:** staging can be rebuilt from scratch if
something goes wrong — no persistent user state, no live traffic impact.

**Why main requires a human:** `appstore-prod-01` has live user state
(Keycloak realm, running deployments). A mistake here costs real
downtime, not just a container restart.

## After a human merges — you may resume

Once merged, staging deploys automatically
(`deployment/.github/workflows/staging.yml` — no action needed from
you).

### Stufe 8 — Hermes Staging-Verify (Handoff)

Nach erfolgtem Merge und Staging-Deploy rufe `/verify-staging` auf.
Dieser Skill sendet Hermes eine Verify-Anfrage via Discord-Webhook —
Hermes prüft Container-Health, Logs und allgemeinen Status und postet
das Ergebnis im Discord-Channel.

Warte auf Hermes' Discord-Antwort, bevor du dem Menschen "Staging sieht
gut aus" meldest. Wenn Hermes Probleme meldet, nutze `/diagnose-production`
für tiefere Analyse.

**Do not** proceed to prod — that is System 5.2's second gate, always a
separate, explicit human decision, never something this skill initiates.

## Known pre-existing CI failures — don't treat these as your bug

As of 2026-09, `backend`/`frontend`/`worker`'s 🔒 Security checks may
fail on unrelated, pre-existing CVEs in `cryptography`, `gitpython`,
`js-yaml`, `nanoid` (found when GitHub Actions was first enabled
org-wide — see each repo's `claude_docs/debugging/local-setup-gotchas.md`).
If your PR's Security check fails and the finding isn't caused by
your diff, say so explicitly and do not attempt to silently work
around it (no `--ignore-vuln` additions without asking) — surface it
and let the human decide whether to fix the dependency or accept the
blocked state.
