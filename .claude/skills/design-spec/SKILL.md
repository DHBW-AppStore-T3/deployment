---
name: design-spec
description: "Use after /brainstorming has produced a chosen option — creates the Design Spec portion of a GitHub Issue. Covers what is built, component boundaries, interface contracts, data flow, and technology decisions with rationale. Triggers on: write a design spec, design spec for this feature, document the design."
---

# /design-spec

Produces the **Design Spec** section of a GitHub Issue after `/brainstorming`
has identified the chosen option. No implementation code here — this is
the *what* and *why*, not the *how*.

## Prerequisites

- `/brainstorming` has run and a human has chosen an option.
- HANDOVER.md and `claude_docs/` of all affected repos have been read.

## What a Design Spec covers

| Abschnitt | Inhalt |
|---|---|
| **Ziel** | Ein Satz: Was wird für wen gebaut? |
| **Scope** | Welche Repos, Module, Endpunkte sind betroffen? Explizit was *nicht* im Scope ist. |
| **Komponenten & Verantwortlichkeiten** | Welche neuen oder geänderten Klassen/Module/Services gibt es? Wofür ist jede zuständig? |
| **Schnittstellen** | Neue oder geänderte API-Endpunkte (OpenAPI-Konform), Events, Queue-Messages. Kein Placeholder: echte Pfade, echte Schemas. |
| **Datenfluss** | Wie bewegen sich Daten durch das System? Sequence-Diagramm in ASCII oder Mermaid wenn hilfreich. |
| **Technologieentscheidungen** | Konkrete Entscheidungen mit ein-Satz-Begründung. Verweis auf `claude_docs/decisions/` wenn eine bestehende Entscheidung gilt. |
| **Bekannte Risiken** | Höchstens 3. Nur echte Risiken, keine Boilerplate-Warnungen. |

## Org-specific constraints

- **OpenAPI-first**: Jede neue API-Oberfläche muss als OpenAPI-Fragment dargestellt werden,
  nicht als Prosa. Das Fragment wird später 1:1 in `backend/` eingebaut.
- **Keine Superset-Designs**: Spec nur für das, was das Issue umfasst. Keine
  "könnte man später erweitern"-Abschnitte.
- **Cross-repo**: Wenn frontend und backend beide betroffen sind, listet die Spec
  explizit die Kontraktänderung zwischen beiden (welche Felder kommen neu, welche
  fallen weg).

## Output-Format (für /issue-creation Step 5)

```markdown
## Design Spec

### Ziel
<Ein Satz>

### Scope
**In scope:** <Liste>
**Out of scope:** <Liste>

### Komponenten
- `<Modul/Klasse>` — <Verantwortlichkeit>

### Schnittstellen
```http
POST /api/v1/<endpoint>
Content-Type: application/json

{ "<field>": "<type>" }
```

### Datenfluss
<ASCII oder Mermaid>

### Technologieentscheidungen
- <Entscheidung> — <Begründung>

### Risiken
- <Risiko> — <Mitigation>
```

Nach Erstellung: Übergabe an `/implementation-spec` für den nächsten Abschnitt.
