# Hermes Agent + bestehende MCPs statt Eigenbau

HARNESS.md System 2/3 legt fest: kein selbst gebauter
`appstore-ops`-MCP-Server. Stattdessen Hermes Agent (Nous Research)
als Server-Agent, angebunden an bestehende MCP-Server
(`podman-mcp` produktiv, `github-mcp-server`/`openstack-mcp` geplant).

**Begründung:** Aufwand für Server-Code + Sicherheitsgrenzen
selbst bauen und pflegen steht in keinem Verhältnis zum Nutzen, wenn
etablierte MCPs denselben Bedarf abdecken.

**Was das beim ersten echten Deploy gekostet hat:** vier reale Bugs
bei der `podman-mcp`-Integration (kein veröffentlichtes Docker-Image,
falsche Backend-Auswahl, blockierender stdin, fehlender
Healthcheck) — dokumentiert in `.github`-Repo `HARNESS.md` Abschnitt
2.1. Trotzdem insgesamt weniger Aufwand als ein Server von Grund auf.

## Kein separater `claude-agent`-Host-User

Ursprünglich geplant (eigener SSH-User, `docker`-Gruppe, kein sudo),
dann bewusst verworfen: Hermes selbst *ist* der Server-Agent, ein
zweiter paralleler User hätte nur zwei Guardrail-Flächen statt einer
bedeutet. Siehe `.github`-Repo `HARNESS.md` Abschnitt 3.2.
