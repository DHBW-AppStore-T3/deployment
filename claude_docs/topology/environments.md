# Umgebungen: dev / staging / prod

| Umgebung | Compose-Datei | Reverse Proxy | Deploy-Weg |
|---|---|---|---|
| dev | `docker-compose.dev.yml` | keiner, direkte Ports | `make dev-up` lokal |
| staging | `docker-compose.staging.yml` | Caddy, dns-01-Zertifikat | Forgejo-Workflow (`.forgejo/workflows/staging.yml`), pinnable Image-Versionen (`${BACKEND_VERSION:-latest}`) |
| prod | `docker-compose.prod.yml` | caddy, ACME-Zertifikat (DHBW/HARICA) via DNS-01 | manuell via `make podman-mcp-up`/`make moodle-up`/`prod-up`, Images hart auf `:latest` |

## Warum prod nicht pinnbar ist

`docker-compose.prod.yml`: Image-Tags sind hart auf `:latest` codiert,
kein `${VAR:-latest}`-Override wie in staging. Kombiniert mit
`pull_policy: always` gibt das eine Continuous-Delivery-Pipeline:
Merge auf `main` → Image neu gebaut+gepusht → `compose up` zieht und
rollt. Wer eine reproduzierbare, gepinnte Version braucht, nutzt
staging auf einer separaten VM — prod kann das architektonisch nicht.

## OpenStack-Realität

`appstore-prod-01` läuft mit **einer** IPv6-Adresse, **keiner
DNS-Domain**. Das selbstsignierte Zertifikat trägt CN/SAN direkt auf
diese IP. Konsequenzen: kein Let's-Encrypt-Flow möglich (bräuchte eine
Domain), Moodle bekommt deshalb einen eigenen Port (8443) statt einer
Subdomain (siehe `docker-compose.moodle.yml`-Kommentarkopf).

Die konkrete Adresse hier absichtlich nicht mehr hartkodiert — eine
frühere Version dieser Datei nannte `2001:7c0:1b20:c913:1::15a`, was
nach einem VM-Rebuild bereits veraltet war (echte, per
`terraform output -raw vm_ip` gegen `envs/production` verifizierte
Adresse: `2001:7c0:1b20:c913:1::180`, siehe deployment#49). Immer per
`terraform output` gegen den Terraform-State abfragen, nicht aus einer
Doku zitieren — die Adresse ändert sich bei jedem VM-Rebuild.

## Vierte VM: `hermes-dhbw-appstore` (deployment#49)

Kein Umgebung im Sinne der Tabelle oben (kein Anwendungs-Deploy-Ziel) —
läuft ausschließlich `hermes-agent` (`docker-compose.hermes.yml`,
`infrastructure/terraform/envs/hermes/`). SSH-only Security-Group,
keine HTTP/HTTPS-Ingress-Regeln: der Host serviert nichts eingehend,
sondern verbindet sich ausgehend zu `podman-mcp` auf `appstore-prod-01`,
`staging-dhbw-appstore` und `ci-dhbw-appstore` (MCP/TCP:8080, siehe
`claude_docs/decisions/2026-hermes-dedicated-vm.md`). Vorher lief
Hermes als Overlay auf `appstore-prod-01` selbst — siehe diese
Entscheidungsdatei für die Begründung des Umzugs.
