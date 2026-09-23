---
name: issue-creation
description: "Use when a human brings a new requirement and it needs to be turned into a fully specified, approved GitHub Issue — walks Prozess 1 of HARNESS.md (Klarifizierung → Brainstorming → Design Spec → Implementation Spec → Freigabe → gh issue create). Triggers on: create issue for this, spec this feature, write an issue for, new requirement."
---

# /issue-creation

Walks HARNESS.md Prozess 1 end-to-end: from a human's raw requirement to
a GitHub Issue that contains a reviewed, human-approved specification.
**Do not proceed to /ship-feature until a human has explicitly approved
the spec and the issue is created.**

## The chain

```
1. READ context           — HANDOVER.md + claude_docs/ für das betroffene Repo
2. KLARIFIZIEREN          — Gezielte Rückfragen stellen (STOP, warte auf Mensch)
3. MENSCH antwortet       — Antworten einarbeiten
4. BRAINSTORMING          — /brainstorming aufrufen: cross-repo Abhängigkeiten,
                            Graphify + OpenAPI, Optionen entwickeln
5. SPECS                  — /design-spec → Design Spec Optionen
                            /implementation-spec → Implementation Spec
6. FREIGABE               — Spec dem Menschen vorlegen (STOP, warte auf Freigabe)
7. GH ISSUE CREATION      — gh issue create mit Spec als Body
```

---

## Schritt 1 — Kontext lesen

Lies **vor jeder Rückfrage**:
- `HANDOVER.md` im betroffenen Repo (aktueller Stand, laufende Änderungen)
- `claude_docs/` des betroffenen Repos (Architektur, Entscheidungen, bekannte Fallstricke)
- Falls cross-repo: tue dasselbe für jedes betroffene Repo

Ziel: Fragen stellen, die ohne diesen Kontext nicht gestellt werden könnten.
Keine Rückfrage stellen, die claude_docs/ bereits beantwortet.

---

## Schritt 2 — Klarifizieren (STOP)

Stelle **gezielte** Rückfragen — keine Architektur raten, keine Annahmen
still einbauen. Maximal 3–5 offene Fragen. Typische Klärungsachsen:

- **Scope**: Welche Repos sind betroffen? Gibt es bestehende Endpunkte
  (OpenAPI), die erweitert werden, oder neue?
- **Nutzer und Kontext**: Wer löst diesen Workflow aus, in welchem State?
- **Grenzen**: Was ist explizit *nicht* Teil dieser Anforderung?
- **Abhängigkeiten**: Blockiert das andere Features / wird es von etwas
  geblockt?
- **Akzeptanzkriterien**: Woran erkennt man, dass die Anforderung erfüllt ist?

Format: Nummerierte Liste, eine Frage pro Zeile. Dann **STOP** —
warte auf Antworten, bevor du weitergehst.

---

## Schritt 3 — Antworten einarbeiten

Verarbeite die Antworten und ergänze das Kontextbild. Wenn eine Antwort
neue Unklarheiten aufwirft, darfst du eine zweite, kurze Klärungsrunde
machen — aber maximal eine zweite Runde. Danach weiter mit Schritt 4.

---

## Schritt 4 — Brainstorming

Rufe `/brainstorming` auf. Gib mit:
- Die geklärte Anforderung
- Welche Repos betroffen sind
- Den Kontext aus HANDOVER.md / claude_docs/

`/brainstorming` läuft Graphify + OpenAPI-Analyse und entwickelt
Lösungsoptionen mit Trade-offs. Gib die Optionen dem Menschen **kurz**
(2–3 Sätze pro Option, Empfehlung markiert) — warte auf Signal, welche
Option weiterverfolgt wird, bevor du Specs schreibst.

---

## Schritt 5 — Specs

Mit der gewählten Brainstorming-Option:

1. **Design Spec** via `/design-spec` — Was wird gebaut? Komponenten,
   Schnittstellen, Datenfluss. Technologieentscheidungen mit Begründung.
2. **Implementation Spec** via `/implementation-spec` — Wie wird es
   gebaut? Dateipfade, Funktionssignaturen, Teststrategie, Migrations-
   oder Rollout-Hinweise.

Beide Specs werden als zusammenhängendes Dokument gebündelt, das als
GitHub-Issue-Body dient.

---

## Schritt 6 — Freigabe (STOP)

Lege dem Menschen die gebündelte Spec vor. Format:

```
## Design Spec
<Inhalt>

## Implementation Spec
<Inhalt>

## Akzeptanzkriterien
<Liste>
```

Dann **STOP** — warte auf explizite Freigabe ("sieht gut aus", "freigegeben",
"approved", o.Ä.). Ohne Freigabe kein `gh issue create`. Wenn der Mensch
Änderungen will, überarbeite und wiederhole Schritt 6.

---

## Schritt 7 — GitHub Issue erstellen

Nach Freigabe:

```bash
gh issue create \
  -R DHBW-AppStore-T3/<repo> \
  --title "<prägnanter Titel, ≤72 Zeichen>" \
  --body "$(cat <<'EOF'
## Design Spec
<Inhalt>

## Implementation Spec
<Inhalt>

## Akzeptanzkriterien
- [ ] <Kriterium 1>
- [ ] <Kriterium 2>
EOF
)"
```

Nach der Issue-Erstellung: Issue-URL ausgeben und explizit sagen, dass
das Issue bereit für `/ship-feature #<issue-number>` ist.

---

## Was NICHT in ein Issue gehört

- Implementierungsdetails, die sich aus dem Code selbst ergeben
- Wiederholung von Entscheidungen, die bereits in claude_docs/decisions/ stehen
- Spekulative Zukunftsanforderungen ("könnte man später noch...")
- Interne Diskussionen oder verworfene Optionen (die gehören in die Spec-Erstellung, nicht in das Issue)
