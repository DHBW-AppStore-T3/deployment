---
name: ship-feature
description: "Use when the user asks to implement and ship a feature or fix end-to-end, from a spec through to a merged PR — walks the HARNESS.md System 5 chain (branch, TDD loop, PR, CI gate, human-approved merge) and stops at the two points a human must approve. Triggers on: implement and ship this, build and merge this feature, ship this fix."
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
4. Open a PR
5. Wait for CI (required status checks) — do not merge before checks resolve. If a check
                                           fails, fix it or explain why it's a
                                           pre-existing, unrelated failure (see the
                                           Security-check precedent below) — never merge
                                           past a required check.
6. STOP — human approval required        — this is System 5.2's first gate. State clearly
                                           that the PR is ready and waiting for a human to
                                           merge. Do not merge it yourself.
```

## What "STOP" means here, concretely

Do not run `gh pr merge`. Report the PR URL, the CI status, and a
one-line summary of what changed, then end your turn. The human
decides when to merge — this is deliberate, not a capability gap (see
HARNESS.md System 5.2 for why: merge is the point where staging
auto-deploys, so a mistake here propagates without further action).

## After a human merges — you may resume

Once merged, staging deploys automatically
(`deployment/.github/workflows/staging.yml` — no action needed from
you). If asked to verify: use `/diagnose-production` and
`/deploy-status` against staging. **Do not** proceed to prod — that is
System 5.2's second gate, always a separate, explicit human decision,
never something this skill initiates.

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
