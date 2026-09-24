# Netzwerke

Vier Kern-Netzwerke in `docker-compose.prod.yml`
(`*-network-prod`-Namen, `driver: bridge`):

| Netzwerk | Mitglieder | Zweck |
|---|---|---|
| `frontend-network` | caddy, backend, frontend | öffentlich erreichbare Services |
| `backend-network` | caddy, postgres, keycloak, rabbitmq, redis, backend | Backend + seine direkten Abhängigkeiten |
| `worker-network` | postgres, postgres-tfstate, rabbitmq, redis, worker | Worker isoliert von der Anwendungs-DB — kein `postgres`-Zugriff |
| `keycloak-network` | caddy, keycloak-postgres, keycloak | Identity-Provider isoliert |

## Ein zusätzliches Netzwerk aus den Overlays

- `moodle-network` (`docker-compose.moodle.yml`): `moodle-db` +
  `moodle`, zusätzlich tritt `caddy` dem `moodle-network` bei (damit
  der Reverse-Proxy `moodle` per Name auflösen kann) — **nicht** an
  `backend-network`, `worker-network` oder `keycloak-network`.
  Bewusste Isolation: Moodle hat keine Laufzeit-Abhängigkeit zum
  AppStore-Backend.

## `podman-mcp` bekommt seit deployment#49 einen Host-Port

Vor deployment#49 lief `podman-mcp` zusammen mit `hermes-agent` im
selben `agent-network` auf `appstore-prod-01` — kein `ports:`-Mapping
nach außen nötig, da beide Container sich per Docker-DNS erreichten.
Seit `hermes-agent` auf eine eigene VM (`hermes-dhbw-appstore`)
umgezogen ist, gibt es kein gemeinsames Docker-Netzwerk mehr zwischen
den beiden: `docker-compose.podman-mcp.yml` published `8080:8080` auf
dem Host-Interface. Die Zugriffsbeschränkung sitzt jetzt in der
OpenStack-Security-Group (`podman_mcp_from_hermes`-Regel in
`envs/production`/`envs/staging/security_group.tf`), nicht mehr in der
Docker-Netzwerktopologie — siehe
`claude_docs/decisions/2026-hermes-dedicated-vm.md`.
