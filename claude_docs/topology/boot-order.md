# Hochfahr-Reihenfolge

`docker-compose.prod.yml` erzwingt über `depends_on` +
`condition: service_healthy` folgende Kette:

```
postgres, postgres-tfstate, keycloak-postgres    (Basis-DBs, parallel)
  → keycloak                                      (wartet auf keycloak-postgres)
rabbitmq, redis                                   (parallel zu den DBs)
  → backend                                        (wartet auf postgres, rabbitmq, redis: healthy;
                                                      keycloak: nur started, nicht healthy)
  → worker                                         (wartet auf rabbitmq, redis, postgres-tfstate: healthy)
  → frontend                                       (wartet auf backend: healthy)
  → caddy                                          (wartet auf frontend, backend, keycloak: started)
```

## Agent-/Moodle-Overlays — eigene, spätere Reihenfolge

`docker-compose.agent.yml`:
```
podman-mcp (muss healthy sein, echter Healthcheck gegen /mcp)
  → hermes-agent
```
`docker-compose.moodle.yml`:
```
moodle-db (healthy)
  → moodle
  → caddy (Override: MOODLE_HOSTNAME + moodle-network, neu
           gestartet für das zweite Site-Block-Zertifikat)
```

Beide Overlays sind additiv — sie starten **nach** dem laufenden
Prod-Stack, nie davor, und ändern nichts an der obigen Kern-Reihenfolge.

## Bekannter, tatsächlich aufgetretener Fehler in dieser Kette

`docker-compose.agent.yml`s `hermes-agent` hatte ursprünglich nur
`depends_on: podman-mcp` **ohne** `condition: service_healthy` — das
ordnet nur den Start, wartet aber nicht auf Bereitschaft. Da
`podman-mcp` beim ersten echten Deploy mehrfach crashte (siehe
`.github`-Repo `HARNESS.md` Abschnitt 2.1), verband sich Hermes nie,
weil es die MCP-Verbindung nur beim eigenen Start versucht und danach
"parkt". Fix: echter Healthcheck + `condition: service_healthy`.
