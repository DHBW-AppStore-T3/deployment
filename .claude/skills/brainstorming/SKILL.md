---
name: brainstorming
description: "Use before any non-trivial implementation to develop and align on a design — Spike, Bounded, or Architectural path depending on scope. Required in /issue-creation Step 4. Triggers on: brainstorm this, think through options, what's the best approach for, how should we design."
---

# /brainstorming

For the underlying principle and the three paths (Spike / Bounded /
Architectural), see
[obra/superpowers' brainstorming skill](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md) —
the gating rule, the anti-pattern ("too simple to need approval"),
and the design artifact requirements per path. This skill is the
org-specific *how* layered on top.

## Hard Gate (from upstream)

> Before taking any implementation action — including invoking
> /ship-feature, writing product code, scaffolding, or creating
> issues — complete the selected path's prerequisites and get
> human approval.

## Org-specific additions

### Cross-repo analysis (required for Architectural path)

This org has six repos in one org (`DHBW-AppStore-T3`). Before
proposing options, always:

1. **Graphify**: run `/graphify` if a cross-repo dependency graph
   would change the design. The committed Graphify graphs in
   `backend/`, `frontend/`, `worker/`, `deployment/` show current
   module boundaries.
2. **OpenAPI contract**: for any change that touches the API boundary
   between frontend and backend, read `backend/openapi.json` (or run
   `GET /openapi.json` locally) before proposing a design — the
   contract is ground truth, not the code narrative.
3. **claude_docs/decisions/**: check for existing decisions in the
   affected repo before proposing a direction that contradicts a
   documented decision. Cite the decision file if you find one.

### Path classification for this org

| Scope | Path |
|---|---|
| "Does X work / is X feasible?" | Spike |
| Änderung in einem Repo, bestehender Endpunkt oder Komponente | Bounded |
| Neuer Endpunkt, neue Service-Schicht, cross-repo Änderung, DB-Migration | Architectural |

### Output format for `/issue-creation` Step 4

When called from `/issue-creation`, produce:

```
## Brainstorming — <Anforderungstitel>

**Gewählter Pfad:** Bounded / Architectural

### Option A — <Name>
<2–3 Sätze: was, wie, Trade-offs>

### Option B — <Name>
<2–3 Sätze: was, wie, Trade-offs>

### Option C (optional) — <Name>
<2–3 Sätze: was, wie, Trade-offs>

**Empfehlung:** Option <X>, weil <ein Satz>.
```

Dann **STOP** — warte auf Signal des Menschen, bevor `/design-spec`
oder `/implementation-spec` aufgerufen wird.
