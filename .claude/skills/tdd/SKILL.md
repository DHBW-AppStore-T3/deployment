---
name: tdd
description: "Use when implementing new backend/worker/frontend functionality that should follow a red-green-refactor loop instead of writing implementation first. Branches by language/repo since the exact commands differ. Triggers on: implement this with TDD, write a test first, tdd this feature."
---

# /tdd

One loop, three sets of commands — branch on which repo you're in.
HARNESS.md System 4.2/4.3.

For the underlying principle (why TDD, not just how), see
[obra/superpowers' test-driven-development skill](https://github.com/obra/superpowers/blob/main/skills/test-driven-development/SKILL.md) —
"NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST", including its
answer for when a shortcut feels justified: it isn't. This skill is
the repo-specific how (the exact commands per language/toolchain);
that one is the discipline.

## The loop (same regardless of repo)

1. Write a test that fails for the right reason — run it, confirm the
   failure message matches what you expect (not an import error or a
   typo), before writing any implementation.
2. Write the minimal implementation that makes it pass — resist adding
   anything the current test doesn't require.
3. Run the full suite, not just the new test — a passing new test with
   a broken old one is not done.
4. Refactor with the suite green as your safety net.
5. Re-run the full suite one more time after refactoring.

Only report the task as finished after step 5's full-suite run is
green — a green step-3 run is not sufficient if you touched code in
step 4.

## backend/ and worker/ (Python, Poetry)

```bash
poetry run pytest                    # full suite
poetry run pytest path/to/test.py -v # single file, verbose
poetry run ruff check .              # lint (both repos)
poetry run ruff format .             # backend: Ruff handles formatting too
```

**worker/ only** — has Black + isort as separate tools on top of Ruff
(backend does not):
```bash
poetry run black .
poetry run isort .
poetry run mypy .                    # both repos have mypy, but worker's CI
                                      # config is stricter — check pyproject.toml
                                      # per-file-ignores before assuming a mypy
                                      # error is new
```

`worker/pyproject.toml` pins both `black` and `ruff` to
`line-length = 120`, so the two shouldn't fight — but `worker/` is the
one repo with all three formatters (`black`, `isort`, `ruff`)
configured, so if CI's lint job disagrees with a local run, diff
which formatter last touched the file before assuming the CI config
changed.

## frontend/ (Vue 3, Vitest)

```bash
npm run test              # vitest --run, full suite once
npm run test:watch        # vitest, watch mode — use during the red/green loop itself
npm run test:coverage     # only when coverage matters for this specific change
vue-tsc -b                # type-check — npm run build fails on type errors, not
                           # just warns, so run this before considering "green" complete
```

## Before reporting "done"

Full suite green (not just the new test), lint clean, and for
backend/worker also `mypy` clean unless the error pre-dates your
change (check with `git stash` + re-run to confirm) — see each repo's
`claude_docs/debugging/local-setup-gotchas.md` for repo-specific
known-issue exceptions before assuming a failure is yours to fix.
