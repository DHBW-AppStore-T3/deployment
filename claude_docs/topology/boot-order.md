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

## podman-mcp-/Moodle-Overlays — eigene, spätere Reihenfolge

`docker-compose.podman-mcp.yml` (auf `appstore-prod-01`,
`staging-dhbw-appstore` und `ci-dhbw-appstore`, je einzeln):
```
podman-mcp (muss healthy sein, echter Healthcheck gegen /mcp)
```
Kein `depends_on` mehr auf ein lokales `hermes-agent` — seit
deployment#49 läuft Hermes auf einer eigenen VM
(`docker-compose.hermes.yml` auf `hermes-dhbw-appstore`) und verbindet
sich über MCP/TCP zu allen drei `podman-mcp`-Instanzen. Compose kann
diese startreihenfolge-Abhängigkeit über Host-Grenzen hinweg nicht mehr
ausdrücken — Hermes' eigenes "verbindet nur beim Start, parkt nach 3
Fehlversuchen"-Verhalten (siehe unten) ist die einzige noch bestehende
Absicherung, pro podman-mcp-Instanz einzeln.

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

Als `podman-mcp` und `hermes-agent` noch im selben `docker-compose.agent.yml`
auf `appstore-prod-01` liefen, hatte `hermes-agent` ursprünglich nur
`depends_on: podman-mcp` **ohne** `condition: service_healthy` — das
ordnet nur den Start, wartet aber nicht auf Bereitschaft. Da
`podman-mcp` beim ersten echten Deploy mehrfach crashte (siehe
`.github`-Repo `HARNESS.md` Abschnitt 2.1), verband sich Hermes nie,
weil es die MCP-Verbindung nur beim eigenen Start versucht und danach
"parkt". Fix damals: echter Healthcheck + `condition: service_healthy`
innerhalb derselben Compose-Datei. Seit deployment#49 gibt es dieses
lokale `depends_on` nicht mehr (siehe oben) — der Healthcheck in
`docker-compose.podman-mcp.yml` bleibt trotzdem bestehen, damit
`docker compose ps` und Diagnose auf jeder einzelnen VM weiterhin
zeigen, ob podman-mcp dort bereit ist.
