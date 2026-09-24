# Netzwerke

Vier Kern-Netzwerke in `docker-compose.prod.yml`
(`*-network-prod`-Namen, `driver: bridge`):

| Netzwerk | Mitglieder | Zweck |
|---|---|---|
| `frontend-network` | caddy, backend, frontend | öffentlich erreichbare Services |
| `backend-network` | caddy, postgres, keycloak, rabbitmq, redis, backend | Backend + seine direkten Abhängigkeiten |
| `worker-network` | postgres, postgres-tfstate, rabbitmq, redis, worker | Worker isoliert von der Anwendungs-DB — kein `postgres`-Zugriff |
| `keycloak-network` | caddy, keycloak-postgres, keycloak | Identity-Provider isoliert |

## Zwei zusätzliche Netzwerke aus den Overlays

- `agent-network` (`docker-compose.agent.yml`): `podman-mcp` +
  `hermes-agent`, zusätzlich `hermes-agent` an `backend-network`
  gebridged (kann `backend`/`worker`/`rabbitmq`/`redis` per Name
  erreichen) — **nicht** an `frontend-network` oder
  `keycloak-network`, kein Pfad zu nutzerseitigen Services oder zum
  Identity-Provider.
- `moodle-network` (`docker-compose.moodle.yml`): `moodle-db` +
  `moodle`, zusätzlich tritt `caddy` dem `moodle-network` bei (damit
  der Reverse-Proxy `moodle` per Name auflösen kann) — **nicht** an
  `backend-network`, `worker-network` oder `keycloak-network`.
  Bewusste Isolation: Moodle hat keine Laufzeit-Abhängigkeit zum
  AppStore-Backend.

## `podman-mcp` bekommt keinen Host-Port

Einziger Zugriffsweg auf `podman-mcp:8080` ist innerhalb von
`agent-network` — kein `ports:`-Mapping nach außen. Diagnose/Zugriff
von außerhalb läuft über SSH auf den Host, nicht über einen
exponierten Container-Port.
