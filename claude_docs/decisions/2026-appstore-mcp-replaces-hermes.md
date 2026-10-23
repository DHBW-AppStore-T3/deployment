# appstore-mcp ersetzt Hermes

Der Agent "Hermes" (eigene OpenStack-VM `hermes-dhbw-appstore`, `podman-mcp` auf
den Docker-VMs, Discord) ist entfernt: `agent/`, `docker-compose.hermes.yml`,
`docker-compose.podman-mcp.yml`, `.github/workflows/hermes.yml`,
`infrastructure/ansible/hermes.yml`. Die AppStore-Umgebungen laufen auf k3s
(Argo CD), die Container-Sicht von podman-mcp gibt es dort nicht mehr.

Ersatz: der Remote-MCP-Server `appstore-mcp`
(github.com/DHBW-AppStore-T3/appstore-mcp, Chart `k8s/charts/appstore-mcp`).
Read-only (ServiceAccount nur get/list/watch, keine Secrets, kein exec),
Login über GitHub (nur Org-Mitglieder) oder statische Tokens. Agenten rufen
nach einem Push auf `dev` `staging_verdict` auf (Skill `verify-staging`).
Promotion nach `main`/prod bleibt eine menschliche Entscheidung.

Nicht Teil dieser Änderung: `infrastructure/terraform/envs/hermes` und die
`hermes_vm_ipv6`-Security-Group-Regeln der alten VM-Envs. Der Abbau der VM ist
ein eigener Schritt. Die älteren Entscheidungen
(`2026-hermes-over-custom-mcp.md`, `2026-hermes-dedicated-vm.md`) bleiben als
Historie stehen.
