# Einzelnen Container zurückrollen

## Einen Service neu starten (gleiches Image, neu gezogen)

```bash
make prod-restart SVC=backend    # oder frontend, worker, nginx, ...
```

Führt `docker compose ... up -d --force-recreate <SVC>` aus — zieht
**nicht** automatisch ein älteres Image, nur ein Neustart mit dem
aktuell lokal vorhandenen Image.

## Auf eine ältere Image-Version zurück

Prod hat **keine** Versions-Pins (`docker-compose.prod.yml` nutzt hart
`:latest`, siehe `topology/environments.md`) — ein Rollback auf eine
spezifische ältere Version ist auf dieser Compose-Datei nicht direkt
vorgesehen. Nur über GHCR (Image mit dem alten Digest manuell taggen
und pullen) oder durch Wechsel auf `docker-compose.staging.yml`
(pinnbar) auf einer separaten VM.

## Agent-/Moodle-Overlays gezielt zurückrollen

```bash
make agent-down     # entfernt nur podman-mcp + hermes-agent, Kern-Stack unberührt
make moodle-down    # entfernt nur moodle + moodle-db, Kern-Stack unberührt
```

Beide sind additive Overlays — ein Rollback hier betrifft nie den
laufenden Kern-Stack (backend/frontend/worker/keycloak/etc.).
