# Graph Report - deployment  (2026-09-16)

## Corpus Check
- 56 files · ~49,094 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 20 file(s) not represented in the graph (top: (none) 12, .example 3, .conf 2)

## Summary
- 326 nodes · 486 edges · 30 communities (18 shown, 12 thin omitted)
- Extraction: 97% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 12 edges (avg confidence: 0.83)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `0b713d5a`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- openstack_vm/variables.tf
- infrastructure/ansible/forgejo.yml Playbook
- module.vm
- seed_data.py
- docker-compose.prod.yml Stack
- staging/security_group.tf
- 02-configure.sh
- Packer Image Build Pattern (shared across apps)
- ansible/requirements.yml
- hermes-agent Service
- set_keycloak_urls.py
- appstore-prod-guardrail.py
- Terraform State Decision on Move (local backend)
- 2026-09-15/16 PreToolUse Guardrail, claude_docs/ + Graphify Org-wide
- postgres-tfstate Worker Isolation Rationale
- tf-state named volume
- entrypoint.sh
- inventory-forgejo.sh
- tf-local.sh
- forgejo/.terraform.lock.hcl
- staging/.terraform.lock.hcl
- 2026-09-15 Org-wide Branch Protection
- 2026-09-15 CORS_ORIGINS Fix and Remote Correction
- postgres-test Isolation Rationale
- tf-state Docker Volume Backup Note
- /diagnose-production
- /ship-feature
- /tdd
- /deploy-status
- /restart-service

## God Nodes (most connected - your core abstractions)
1. `module.vm` - 15 edges
2. `openstack_compute_instance_v2.vm` - 14 edges
3. `infrastructure/ansible/forgejo.yml Playbook` - 13 edges
4. `seed()` - 11 edges
5. `infrastructure/ansible/staging.yml Playbook` - 10 edges
6. `openstack_networking_secgroup_v2.forgejo_vm` - 9 edges
7. `openstack_networking_secgroup_v2.appstore_vm` - 9 edges
8. `openstack_networking_port_v2.secondary` - 9 edges
9. `docker-compose.prod.yml Stack` - 9 edges
10. `docker-compose.staging.yml Stack` - 9 edges

## Surprising Connections (you probably didn't know these)
- `caddy Service (staging)` --semantically_similar_to--> `nginx Service (prod)`  [INFERRED] [semantically similar]
  docker-compose.staging.yml → docker-compose.prod.yml
- `Boot Order (Prod Stack)` --references--> `docker-compose.prod.yml Stack`  [EXTRACTED]
  claude_docs/topology/boot-order.md → docker-compose.prod.yml
- `CD - Staging Deployment (GitHub)` --implements--> `docker-compose.staging.yml Stack`  [INFERRED]
  .github/workflows/staging.yml → docker-compose.staging.yml
- `Deployment Repository` --references--> `SCRIPTS.md Error Message Table`  [EXTRACTED]
  README.md → forgejo/SCRIPTS.md
- `.forgejo/workflows/staging.yml` --conceptually_related_to--> `.github/workflows/staging.yml (CI/CD)`  [AMBIGUOUS]
  forgejo/README.md → infrastructure/README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Forgejo Phase 1 Local Bootstrap Flow (compose services + runner config)** — forgejo_docker_compose_forgejo_service, forgejo_docker_compose_runner_service, forgejo_runner_config_yml [EXTRACTED 1.00]
- **Hermes Agent Governance (Decision, Config, Compose)** — claude_docs_decisions_2026_hermes_over_custom_mcp_hermes_agent_over_custom_mcp, agent_config_yaml_hermes_agent_config, docker_compose_agent_yml_hermes_agent_service, docker_compose_agent_yml_podman_mcp_service [EXTRACTED 1.00]
- **Prod Boot-Order Dependency Chain** — claude_docs_topology_boot_order_hochfahr_reihenfolge, docker_compose_prod_yml_backend_service, docker_compose_prod_yml_worker_service, docker_compose_prod_yml_nginx_service [EXTRACTED 1.00]
- **Staging Deploy Pipeline (Terraform-driven inventory + Ansible playbook + seed data)** — infrastructure_readme_staging_workflow, infrastructure_ansible_staging_yml, seed_readme_seed_data_py [EXTRACTED 1.00]
- **Seed App Catalog Entries as a Family of Deployable Apps** — seed_app_descriptions_gitlab_ce_gitlab_ce, seed_app_descriptions_jupyter_notebook_jupyterhub, seed_app_descriptions_monitoring_stack_monitoring_stack, seed_app_descriptions_online_ide_online_ide, seed_app_descriptions_ubuntu_app_ubuntu_terminal_app, seed_app_descriptions_web_latex_web_latex_editor, seed_app_descriptions_pgadmin_pgadmin_4 [INFERRED 0.85]
- **Dev/Staging/Prod Compose Variants of One Deployment Pattern** — docker_compose_dev_yml_stack, docker_compose_staging_yml_stack, docker_compose_prod_yml_stack [INFERRED 0.85]

## Communities (30 total, 12 thin omitted)

### Community 0 - "openstack_vm/variables.tf"
Cohesion: 0.13
Nodes (30): data.openstack_networking_network_v2.secondary, data.openstack_networking_secgroup_v2.secondary, data.openstack_networking_subnet_v2.secondary_v4, Terraform module: infrastructure/terraform/modules/openstack_vm, openstack_blockstorage_volume_v3.docker_data, openstack_compute_instance_v2.vm, openstack_compute_interface_attach_v2.secondary, openstack_compute_keypair_v2.deploy (+22 more)

### Community 1 - "infrastructure/ansible/forgejo.yml Playbook"
Cohesion: 0.07
Nodes (32): caddy service (TLS termination), db service (postgres:16-alpine), forgejo compose network (enable_ipv6), forgejo service (codeberg.org/forgejo/forgejo:11), runner service (code.forgejo.org/forgejo/runner:6), deploy:docker://forgejo-deploy-job:latest Label, AAAA DNS Record for Forgejo Host, forgejo/.env Configuration File (+24 more)

### Community 2 - "module.vm"
Cohesion: 0.11
Nodes (28): Terraform module: infrastructure/terraform/envs/forgejo, module.vm, openstack_networking_secgroup_rule_v2.http, openstack_networking_secgroup_rule_v2.http_v6, openstack_networking_secgroup_rule_v2.https, openstack_networking_secgroup_rule_v2.https_v6, openstack_networking_secgroup_rule_v2.icmpv6, openstack_networking_secgroup_rule_v2.ssh (+20 more)

### Community 3 - "seed_data.py"
Cohesion: 0.13
Nodes (28): App, AppVersionApprovalStatus, Course, _email(), _ensure_app(), _ensure_course(), _ensure_course_teacher(), _ensure_kc_user() (+20 more)

### Community 4 - "docker-compose.prod.yml Stack"
Cohesion: 0.13
Nodes (26): Single Container Rollback, appstore-prod-01 OpenStack Reality (Single IPv6, No DNS), Why Prod Is Not Pinnable, Environments: dev/staging/prod, moodle-network, Core Networks (Prod), docker-compose.dev.yml Stack, Moodle Network Isolation Rationale (+18 more)

### Community 5 - "staging/security_group.tf"
Cohesion: 0.15
Nodes (18): Terraform module: infrastructure/terraform/envs/staging, module.vm, openstack_networking_secgroup_rule_v2.http, openstack_networking_secgroup_rule_v2.http_v6, openstack_networking_secgroup_rule_v2.https, openstack_networking_secgroup_rule_v2.https_v6, openstack_networking_secgroup_rule_v2.icmpv6, openstack_networking_secgroup_rule_v2.ssh (+10 more)

### Community 6 - "02-configure.sh"
Cohesion: 0.13
Nodes (19): fail(), 01-create-vm.sh script, ANSIBLE_CONFIG, ANSIBLE_ROLES_PATH, fail(), fj(), read_env(), remote() (+11 more)

### Community 7 - "Packer Image Build Pattern (shared across apps)"
Cohesion: 0.16
Nodes (21): Apply Database Migrations Task (alembic upgrade head), Caddy Image Stale/Current Check Task, docker compose up -d --build Task (explicit command), Auf Keycloak Warten Task (TCP Connect Check), Copy seed_data.py and app_descriptions into Backend Container, Seed Ausführen Task (runs seed_data.py in backend), GitLab CE (App Catalog Entry), JupyterHub / Jupyter Notebook (App Catalog Entry) (+13 more)

### Community 8 - "ansible/requirements.yml"
Cohesion: 0.12
Nodes (18): geerlingguy.docker role 7.1.0 (job-image copy), GitHub-Primary / Forgejo-Mirror Topology, Forgejo Phase 1 Local Stack, .forgejo/workflows/staging.yml, community.docker Collection (docker_compose_v2), Cinder Data Volume Mount at /var/lib/docker (forgejo.yml), geerlingguy.docker Role Invocation (forgejo.yml), geerlingguy.docker Role 7.1.0 (infra requirements) (+10 more)

### Community 9 - "hermes-agent Service"
Cohesion: 0.16
Nodes (19): Hermes Agent Config, podman-mcp Tool Allowlist, HARNESS.md, Hermes Agent + Existing MCPs over Custom appstore-ops MCP, No Separate claude-agent Host User, 2026-09-15 Hermes Agent + podman-mcp Live on appstore-prod-01, Alembic Downgrade Path, redeploy-named Migration Pitfall (+11 more)

### Community 10 - "set_keycloak_urls.py"
Cohesion: 0.38
Nodes (6): main(), _patch_client(), KeycloakAdmin, Patcht die Redirect-/Origin-URLs der Realm-Clients ``appstore-frontend`` und…, Suche Client per ``clientId`` und update ihn mit ``payload``., _require()

### Community 11 - "appstore-prod-guardrail.py"
Cohesion: 0.50
Nodes (4): extract_subcommand(), main(), PreToolUse guardrail for appstore-prod-01 (HARNESS.md System 3.2/5.4). Hermes'…, # NOTE: "restart" is intentionally NOT in BLOCKED_SUBCOMMANDS — it is

### Community 12 - "Terraform State Decision on Move (local backend)"
Cohesion: 0.50
Nodes (4): Post-Move Checklist, Terraform State Decision on Move (local backend), Deployment Using act, Local State Assumption (single-operator act deploys)

### Community 25 - "/diagnose-production"
Cohesion: 0.29
Nodes (6): /diagnose-production, Reporting back, Step 1 — Health, Step 2 — Logs (only for containers flagged unhealthy in Step 1), Step 3 — Recent deployments (only if Steps 1–2 found nothing), Step 4 — Infrastructure (only if Steps 1–3 explained nothing)

### Community 26 - "/ship-feature"
Cohesion: 0.33
Nodes (5): After a human merges — you may resume, Known pre-existing CI failures — don't treat these as your bug, /ship-feature, The chain, What "STOP" means here, concretely

### Community 27 - "/tdd"
Cohesion: 0.33
Nodes (5): backend/ and worker/ (Python, Poetry), Before reporting "done", frontend/ (Vue 3, Vitest), /tdd, The loop (same regardless of repo)

### Community 28 - "/deploy-status"
Cohesion: 0.40
Nodes (4): /deploy-status, "Is it safe to promote staging to prod", Prod, Staging

### Community 29 - "/restart-service"
Cohesion: 0.40
Nodes (4): After restarting, Allowed restart targets and command, Preconditions — check both before running anything, /restart-service

## Ambiguous Edges - Review These
- `.forgejo/workflows/staging.yml` → `.github/workflows/staging.yml (CI/CD)`  [AMBIGUOUS]
  forgejo/README.md · relation: conceptually_related_to

## Knowledge Gaps
- **60 isolated node(s):** `ANSIBLE_CONFIG`, `ANSIBLE_ROLES_PATH`, `ANSIBLE_CONFIG`, `ANSIBLE_ROLES_PATH`, `entrypoint.sh script` (+55 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 100 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **12 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `.forgejo/workflows/staging.yml` and `.github/workflows/staging.yml (CI/CD)`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `Deployment Repository` connect `docker-compose.prod.yml Stack` to `ansible/requirements.yml`, `02-configure.sh`?**
  _High betweenness centrality (0.084) - this node is a cross-community bridge._
- **Why does `infrastructure/ansible/staging.yml Playbook` connect `infrastructure/ansible/forgejo.yml Playbook` to `ansible/requirements.yml`, `Packer Image Build Pattern (shared across apps)`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `infrastructure/ansible/forgejo.yml Playbook` connect `infrastructure/ansible/forgejo.yml Playbook` to `ansible/requirements.yml`, `02-configure.sh`?**
  _High betweenness centrality (0.068) - this node is a cross-community bridge._
- **Are the 3 inferred relationships involving `infrastructure/ansible/staging.yml Playbook` (e.g. with `secondary-ipv4-marks.sh Connmark Script` and `infrastructure/ansible/forgejo.yml Playbook`) actually correct?**
  _`infrastructure/ansible/staging.yml Playbook` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `ANSIBLE_CONFIG`, `ANSIBLE_ROLES_PATH`, `ANSIBLE_CONFIG` to the rest of the system?**
  _60 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `openstack_vm/variables.tf` be split into smaller, more focused modules?**
  _Cohesion score 0.13012477718360071 - nodes in this community are weakly interconnected._