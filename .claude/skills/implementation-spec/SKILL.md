---
name: implementation-spec
description: "Use after /design-spec — produces the Implementation Spec section of a GitHub Issue. Covers file paths, function signatures, test strategy, migration/rollout notes. Zero placeholders. Triggers on: write an implementation spec, impl spec for this, how should this be implemented."
---

# /implementation-spec

Produces the **Implementation Spec** section of a GitHub Issue — the
*how*. Built on top of `/design-spec`'s *what*. Zero placeholders:
every step names the actual file, actual function, actual assertion.

Inspired by [obra/superpowers' writing-plans skill](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md) —
specifically its rule that every task in a plan must carry its own
test cycle and contain no vague language ("add validation",
"handle edge cases", "implement TBD").

## Prerequisites

- `/design-spec` has been written for this feature.
- The exact repos, modules, and interfaces from the Design Spec are clear.

## What an Implementation Spec covers

| Abschnitt | Inhalt |
|---|---|
| **Taskzerlegung** | Geordnete Liste von Aufgaben, jede ≤ 30 min, jede mit eigenem Testschritt |
| **Dateipfade** | Exakte Pfade aller neuen oder geänderten Dateien |
| **Funktionssignaturen** | Echte Signaturen (Python type hints, TypeScript-Typen), keine Pseudocode-Platzhalter |
| **Teststrategie** | Welche Tests werden geschrieben? Datei, Klasse, Was wird behauptet? |
| **Migrationspfad** | DB-Migrationen, Config-Änderungen, Breaking-Changes — explizit oder "keine" |
| **Rollout-Hinweise** | Reihenfolge der Merges wenn cross-repo; Feature-Flags wenn nötig |

## Zero-Placeholder-Regel

Verboten:
- "add validation logic here"
- "handle the error case"
- "implement as needed"
- "TBD", "TODO", "..."

Erlaubt — Beispiel:
```python
# backend/app/api/v1/endpoints/apps.py
async def get_app_by_id(app_id: int, db: AsyncSession = Depends(get_db)) -> AppResponse:
    ...
```

## Taskformat

```
### Task N — <Name>
**Datei(en):** `<pfad>`
**Was:** <ein Satz>
**Test:** `<pfad/test_datei.py>::<TestKlasse>::<test_methode>` — behauptet <X>
**Done wenn:** Test grün, Linter clean
```

## Output-Format (für /issue-creation Step 5)

```markdown
## Implementation Spec

### Taskzerlegung
<Tasks im Format oben>

### Neue / geänderte Dateien
- `<pfad>` — <Zweck>

### Teststrategie
<Welche Tests, in welchen Dateien, was wird behauptet>

### Migrationspfad
<Schritte oder "Keine Migration erforderlich">

### Rollout-Reihenfolge
<Merge-Reihenfolge bei cross-repo oder "Einzelner PR in <repo>">
```

## Merge-Reihenfolge bei cross-repo Änderungen

Wenn backend und frontend beide betroffen sind: immer zuerst backend
mergen (API-Contract existiert), dann frontend. Worker-Änderungen
können parallel zu backend laufen wenn sie denselben Contract
konsumieren.

Nach Erstellung: Design Spec + Implementation Spec zusammenführen und
an Menschen für Freigabe übergeben (zurück zu `/issue-creation` Step 6).
