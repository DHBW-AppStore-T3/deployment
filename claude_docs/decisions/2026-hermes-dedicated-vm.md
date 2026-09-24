# Hermes auf eigene VM statt Overlay auf appstore-prod-01

deployment#49. Vorher lief `hermes-agent` zusammen mit `podman-mcp` als
additives Overlay (`docker-compose.agent.yml`) direkt auf
`appstore-prod-01`, dem laufenden Prod-Host selbst — siehe
`2026-hermes-over-custom-mcp.md` für die ursprüngliche Entscheidung,
Hermes überhaupt einzusetzen. Diese Datei dokumentiert nur den Umzug
auf einen eigenen Host, nicht die Wahl von Hermes als Agent.

**Kein Cutover eines laufenden Dienstes:** Vor diesem Umzug wurde
`hermes-agent`/`podman-mcp` bereits vollständig von
`appstore-prod-01` entfernt (verifiziert per SSH: keine Container,
keine Volumes, keine systemd-Units — nur die alte
`docker-compose.agent.yml` lag noch ungenutzt herum, jetzt gelöscht).
Dies ist ein Neuaufbau auf neuer Infrastruktur, kein Umzug eines
aktiven Dienstes.

## Warum eine eigene VM

- **Blast radius:** Ein Overlay auf dem Prod-Host selbst bedeutet, dass
  ein Fehler in Hermes' eigenem Container (Crash-Loop, Ressourcen-
  Erschöpfung) den Kern-Stack auf derselben VM treffen kann — auch
  wenn Docker-Netzwerke isoliert sind, teilen sich alle Container CPU/
  RAM/Disk des einen Hosts.
- **Ein Agent, drei Ziele:** Hermes soll perspektivisch nicht nur Prod,
  sondern auch Staging und CI diagnostizieren können. Auf `appstore-
  prod-01` selbst zu sitzen und von dort SSH-frei nach staging/ci zu
  reichen wäre eine seltsame Asymmetrie — ein neutraler eigener Host
  behandelt alle drei Ziele gleich.

## Architektur

Ein `podman-mcp`-Container pro Ziel-VM (`appstore-prod-01`,
`staging-dhbw-appstore`, `ci-dhbw-appstore`), je mit dem eigenen
`docker.sock` der jeweiligen VM — kein Cross-VM-Socket-Mount. Hermes
selbst läuft allein auf der neuen `hermes-dhbw-appstore`-VM und
verbindet sich zu allen drei per MCP/TCP (`agent/config.yaml`:
`podman-prod`/`podman-staging`/`podman-ci`).

```
Discord (Mensch) ──Allowlist-Check──► hermes-agent @ hermes-dhbw-appstore
                                          │
                                          ├──MCP/TCP:8080──► podman-mcp@appstore-prod-01
                                          ├──MCP/TCP:8080──► podman-mcp@staging-dhbw-appstore
                                          └──MCP/TCP:8080──► podman-mcp@ci-dhbw-appstore
```

**MCP/TCP statt SSH für Hermes→Ziel-VMs** — HARNESS.md System 3.2: kein
SSH-Zugriff für Agenten, nur für Menschen.

**Ein `podman-mcp` pro Ziel-VM statt zentral auf der Hermes-VM** —
vermeidet einen netzwerk-exponierten Docker-Socket; jede Instanz sieht
nur die Container ihres eigenen Hosts.

**Eigene Terraform-Env (`envs/hermes/`) statt Ad-hoc-VM** — konsistent
mit `envs/staging`/`envs/production`, vermeidet die Lücke, die bei
`ci-dhbw-appstore` bereits besteht (dort nur handgebaut, kein
Terraform-Env — dessen Security-Group-Erweiterung musste deshalb auch
hier manuell nachgezogen werden, siehe unten).

**Kein neues Terraform-Modul** — `modules/openstack_vm` deckt den
Bedarf unverändert ab, wie schon bei staging/production.

## Was sich an Netzwerk/Sicherheit geändert hat

`podman-mcp` hatte vorher keinen Host-Port (`docker-compose.agent.yml`:
nur innerhalb von `agent-network` erreichbar, da `hermes-agent` im
selben Docker-Netzwerk saß). Ohne gemeinsames Docker-Netzwerk über
VM-Grenzen hinweg publiziert `docker-compose.podman-mcp.yml` jetzt
`8080:8080` auf dem Host-Interface jeder Ziel-VM. Die
Zugriffsbeschränkung sitzt seitdem in der OpenStack-Security-Group
(`remote_ip_prefix` auf die IPv6-Adresse der Hermes-VM, keine
öffentliche Erreichbarkeit) — analog zum bestehenden SSH-Scoping-Muster
in `envs/staging`/`envs/production`, siehe deren
`podman_mcp_from_hermes`-Regel.

`ci-dhbw-appstore` ist nicht Terraform-verwaltet — dessen
Security-Group-Regel wurde händisch nachgezogen
(`openstack security group rule create ...`), nicht per `terraform
apply`.

## Bekannte, aus dem ursprünglichen Deploy übernommene Risiken

Die drei realen Bugs aus HARNESS.md 2.1 (fehlendes Docker-Image für
podman-mcp, falsche Backend-Auswahl cli/api, blockierender stdin) sind
im vorhandenen `agent/podman-mcp.Dockerfile` bereits gefixt, mussten
aber pro neuer Instanz (prod, staging, ci) real erneut verifiziert
werden, da der Fix im Dockerfile liegt, nicht im Verhalten des
Upstream-Binaries.

## Aufräumen

Alte `docker-compose.agent.yml` von `appstore-prod-01` entfernt (auch
aus dem Repo gelöscht, siehe git-Historie). `Makefile`s
`agent-up`/`agent-down`/`agent-logs`/`agent-ps`-Targets ersetzt durch
`podman-mcp-up`/`podman-mcp-down`/`podman-mcp-logs`/`podman-mcp-ps`
(kein `hermes-agent`-Target mehr auf dieser VM-Ebene — das lebt jetzt
ausschließlich in `docker-compose.hermes.yml` auf der Hermes-VM).
`.claude/hooks/appstore-prod-guardrail.py`s `RESTART_ALLOWLIST` verliert
`hermes-agent-prod` aus demselben Grund.
