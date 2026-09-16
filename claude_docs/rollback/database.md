# Alembic-Downgrade-Pfad

Migrationen laufen manuell (`docker exec backend-prod python -m
alembic upgrade head`), nie automatisiert. Downgrade entsprechend
ebenso manuell:

```bash
docker exec backend-prod python -m alembic downgrade -1   # eine Revision zurück
docker exec backend-prod python -m alembic downgrade <revision>  # zu spezifischer Revision
```

**Vor jedem Downgrade gegen staging/prod:** menschliche Bestätigung
im selben Moment, laut HARNESS.md System 3 ohne Ausnahme — auch wenn
CI grün war und ein Mensch den ursprünglichen Merge freigegeben hat.

**Bekannter Fallstrick:** einige Migrationen in `backend/alembic/versions/`
heißen nur `redeploy` (siehe `backend/claude_docs/architecture/database.md`)
— das deutet auf frühere Merge-Konflikte zwischen divergierenden
Branches hin. Vor einem Downgrade über mehrere Revisionen die
Migrationskette in `alembic/versions/` tatsächlich lesen, nicht nur
der Revision-Nummer vertrauen.
