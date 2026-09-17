# Infrastructure

Infrastructure-as-code in two layers:

- **Terraform** (`terraform/`) — provisions OpenStack VMs (one Docker host).
- **Ansible** (`ansible/`) — installs Docker on the VM and deploys the application via Docker Compose.

GitHub Actions (`.github/workflows/`) chains the two together: Terraform applies the
infrastructure and exposes the VM's reachable IP as the `vm_ip` output; the workflow reads that
output and writes a small `inventory.ini` that Ansible then deploys onto. The two tools are
**loosely coupled** — Ansible does not read Terraform state.

> **Networking note:** on the current OpenStack the VM's *fixed* IP is already
> publicly routable  so **no floating IP is allocated** (`assign_floating_ip = false`).
> The OpenStack **API** (Keystone), however, is reachable **only from VPN** — so
> every `terraform` / `act` run must be on the VPN.

## Environments

| Environment | Terraform dir               | Ansible playbook | Inventory                         | Trigger                          |
|-------------|-----------------------------|------------------|-----------------------------------|----------------------------------|
| staging     | `terraform/envs/staging`    | `staging.yml`    | generated `inventory.ini`         | manual dispatch (Forgejo Actions) |
| forgejo     | `terraform/envs/forgejo`    | `forgejo.yml`    | `inventory-forgejo.sh`            | run by hand from a workstation   |

`forgejo` is bootstrap infrastructure: it hosts the forge, its database and the
Actions runner that deploys staging. It therefore cannot be deployed by that
runner, and its state backend is local rather than the database this host runs.

> A separate production environment is documented as future work in
> the project plan but not yet wired into the codebase. The Terraform
> module is environment-agnostic, so adding `envs/production/` plus a
> matching playbook is the obvious extension point.

## Terraform

```text
terraform/
├── modules/openstack_vm/             # reusable VM module (keypair + instance + optional floating IP,
│                                     # optional Cinder data volume, optional second interface)
└── envs/
    ├── staging/                      # the application stack (gp1.large)
    └── forgejo/                      # the forge, its database and the Actions runner (gp1.medium)
```

## Addressing

Both hosts sit on `DHBWV6`, whose IPv4 subnet is private — so their only public
address is IPv6, and neither is reachable from a network without it. The module
therefore takes an optional `secondary_network_name`, which attaches a second
interface on a publicly routed IPv4 network. Each host then answers on both
families under one hostname, with an A and an AAAA record side by side.

Three details are load-bearing:

- The interface is attached to the **running** instance
  (`openstack_compute_interface_attach_v2`). A second `network` block on the
  instance would force a replacement, and the root disk holds container data.
- `secondary_subnet_name` is required where the network has more than one IPv4
  subnet, as `DHBWv4` does. The port is pinned to that subnet so the address and
  the gateway Ansible routes through belong together.
- The playbooks configure the interface with a dedicated routing table **and** a
  connection mark. The routing rule on the source address only covers replies the
  host generates itself, which is why SSH worked while every published port timed
  out: Docker DNATs the request before the routing decision, so a container's
  reply still carries its own source address. Neutron's port security then drops
  it on the way out of the primary interface, silently.

Floating IPs are not an option here — the subnet has no router to the external
network, so associating one fails with `ExternalGatewayForFloatingIPNotFound`.
The App blueprints set `enable_floating_ip = false` for the same reason.

Each env dir has:

- `main.tf` — instantiates the `openstack_vm` module (name, image, flavor, **`public_key`**,
  network, security groups, metadata). Outputs `vm_ip`.
- `backend.tf` — `required_version` (`>= 1.5.0`), the OpenStack provider pin
  (`~> 3.4`), and a **local** state backend (`terraform.tfstate` in the env dir). See
  "Local state assumption" below.
- `providers.tf` — OpenStack provider; credentials come entirely from `OS_*` environment variables.
- `variables.tf` — `ssh_public_key`, supplied by CI via `TF_VAR_ssh_public_key`.

The shared module (`modules/openstack_vm/`) registers the supplied public key as an
`openstack_compute_keypair_v2` (so the runner's private key always matches what is injected into
the VM — no dependency on a pre-existing laptop key), then creates an
`openstack_compute_instance_v2`. Two optional pieces are toggled per environment:

- **`assign_floating_ip`** (module default `true`; both envs set `false`) — when true, allocates an
  `openstack_networking_floatingip_v2` from `floating_ip_pool`. Disabled here network already hands out publicly-routable fixed IPs. `vm_ip` returns the floating IP when one
  is assigned, otherwise the instance's fixed IP.
- **`docker_data_volume_size_gb`** (both envs: `50`) — attaches a Cinder volume that the env's
  cloud-init (`user_data`) formats and mounts at `/var/lib/docker`, because the flavor root disk

Only the **public** key half ever reaches OpenStack/state.

Run locally:

```bash
cd terraform/envs/staging
export TF_VAR_ssh_public_key="$(ssh-keygen -y -f /path/to/deploy_key)"
terraform init
terraform apply
```

Requires `OS_AUTH_URL`, `OS_APPLICATION_CREDENTIAL_ID`, `OS_APPLICATION_CREDENTIAL_SECRET`,
`OS_REGION_NAME` in the environment (stored as `STAGING_*` GitHub secrets).

### Local state assumption

State is intentionally kept in a **local** backend (`terraform.tfstate` in each env dir) rather
than a remote backend. This is a deliberate, temporary choice: deploys are driven from a single
operator's machine via `act` (see below) with `--bind`, so the state file persists on the host
and is reused across runs. **This is only safe for one person** — concurrent runs from different
machines/runners would diverge. Moving to a remote backend  is
a possible next step .

## Ansible

```text
ansible/
├── ansible.cfg                       # roles_path, remote_user=ubuntu, SSH tuning, no host key check, no default inventory
├── requirements.yml                  # geerlingguy.docker role + community.docker / ansible.posix collections
├── staging.yml                       # configure Docker + deploy (staging)
├── .gitignore                        # ignores inventory.ini and roles_external/
├── inventory.ini                     # GENERATED at deploy time by the workflow (git-ignored / cleaned up)
└── roles_external/                   # geerlingguy.docker, INSTALLED from Galaxy at deploy time (not vendored, git-ignored)
```

### Inventory hand-off

There is no dynamic inventory plugin. The workflow runs `terraform output -raw vm_ip` and writes:

```ini
[docker_vm]
<floating-ip> ansible_user=ubuntu
```

into `ansible/inventory.ini`. The deploy playbooks target `hosts: docker_vm`, so no IP is
hard-coded in source — it comes straight from the Terraform run that just executed. The file is
created per-run and removed in the workflow's cleanup step.

### Deploy playbooks

`staging.yml` runs against the `docker_vm` host:

1. Creates `/home/ubuntu/app`.
2. Applies the `geerlingguy.docker` role (installs Docker + Compose).
3. rsyncs the **repo root** (`{{ playbook_dir }}/../../` → `/home/ubuntu/app`), excluding `.git`,
   `.history`, `docker-compose.override.yml`, `node_modules`, `__pycache__`, `.venv`,
   `.terraform`, `frontend/dist`, `frontend/test-results`, `frontend/blob-report`, and
   `model_files` (a carryover exclude — no compose service in this repo references it).
4. Renders `keycloak/realm-export.json.j2` with the public `APP_BASE_URL` so Keycloak redirect
   URIs match the deployed host.
5. Generates a self-signed TLS certificate under `nginx/certs/` on first run (idempotent).
6. Runs `community.docker.docker_compose_v2` with `pull: always` against
   `docker-compose.staging.yml` — the full standalone stack (postgres, postgres-tfstate, rabbitmq,
   redis, keycloak + its postgres, backend, worker, frontend, nginx). The explicit `files:` list
   keeps the local-dev `docker-compose.override.yml` from ever being applied to a server.
7. Waits for the backend container, runs Alembic migrations as an explicit task, and reloads
   nginx as a safety net for bind-mounted config changes.

Run locally (after a `terraform apply`, from the env dir, gives you the IP):

```bash
cd ansible
# The role isn't vendored — install it into ./roles_external (where ansible.cfg's
# roles_path looks); collections go to the default path.
ansible-galaxy role install -r requirements.yml -p roles_external
ansible-galaxy collection install -r requirements.yml
printf '[docker_vm]\n%s ansible_user=ubuntu\n' "$(cd ../terraform/envs/staging && terraform output -raw vm_ip)" > inventory.ini
ansible-playbook -i inventory.ini --private-key /path/to/deploy_key staging.yml
```

### Staging realm

The staging environment imports its Keycloak realm from
`keycloak/realm-export.json` (the same file dev uses), bind-mounted by
`docker-compose.staging.yml` at `/opt/keycloak/data/import/realm-export.json`.
Keycloak imports the realm on first boot and skips on subsequent boots
because the realm already exists in the persistent DB volume.

If you need a realm variant with test users for staging, run
`make keycloak-export` against a dev environment that already has those
users — it writes `keycloak/keycloak-export.json` and the staging stack
can mount that file instead by editing the keycloak `volumes:` entry in
`docker-compose.staging.yml`. The current playbook does NOT swap the file
automatically; that was an earlier override-file design that has since
been simplified out.

Validate the staging compose locally with:

```bash
docker compose -f docker-compose.staging.yml config
```

## CI/CD workflows

The staging workflow (`.github/workflows/staging.yml`) runs on every push to `main` and
follows this shape:

1. **Checkout**.
2. **Setup Terraform** (`terraform_wrapper: false`).
3. **Terraform Format Check** — `terraform fmt -check -recursive` (blocking).
4. **Terraform Security Scan (Trivy)** — `trivy config` on HIGH/CRITICAL; **non-blocking**
   (`continue-on-error: true`) for now.
5. **Set up SSH key** from the `SSH_PRIVATE_KEY` secret; derives the public key with
   `ssh-keygen -y -P ''` (the `-P ''` makes a passphrase-protected key fail fast instead of hanging)
   and exports it as `TF_VAR_ssh_public_key` (runs *before* Terraform, which needs it).
6. **Terraform Init, Validate, Plan & Apply** in the env dir (`plan -out=tfplan` → `apply tfplan`),
   then exports `VM_IP` from the `vm_ip` output.
7. **Install Ansible + rsync** (apt; `pip` is blocked by PEP 668 on Ubuntu 24.04 runners), then
   install the `geerlingguy.docker` role into `roles_external/` and the collections — both from the
   pinned `requirements.yml`.
8. **Generate Ansible Inventory** — writes `inventory.ini` from `VM_IP`.
9. **Run Ansible playbook** against `inventory.ini`.
10. **Cleanup** the SSH key + `inventory.ini`.

### Required secrets

`STAGING_OS_AUTH_URL`, `STAGING_OS_APPLICATION_CREDENTIAL_ID`,
`STAGING_OS_APPLICATION_CREDENTIAL_SECRET`, `STAGING_OS_REGION_NAME`, plus a shared
`SSH_PRIVATE_KEY` — an **unencrypted** private key. Terraform registers its derived public half as
the OpenStack keypair, so there is no separate "key pair" name to keep in sync.

`STAGING_ENV_FILE` holds the stack's entire `.env` as one secret. Ansible writes it to the VM
verbatim, so it is runtime configuration rather than CI configuration.

### The staging `.env`

Fields written as `${VAR:?…}` in `docker-compose.staging.yml` abort `compose up` when unset **or
empty**, so the stack refuses to start half-configured:

| Group | Fields |
|---|---|
| URLs | `APP_HOSTNAME`, `APP_BASE_URL`, `CORS_ORIGINS`, `VITE_APP_URL`, `VITE_API_URL`, `VITE_KEYCLOAK_URL` |
| TLS | `ACME_EMAIL`, `DNS_TSIG_KEY_NAME`, `DNS_TSIG_KEY` |
| Backend | `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` |
| Keycloak | `KEYCLOAK_ADMIN_USER`, `KEYCLOAK_ADMIN_PASSWORD`, `KEYCLOAK_CLIENT_SECRET`, `KEYCLOAK_DB_USER`, `KEYCLOAK_DB_PASSWORD`, `KEYCLOAK_DB_NAME` |
| Broker | `RABBITMQ_USER`, `RABBITMQ_PASSWORD` |
| TF state | `TFSTATE_DB_USER`, `TFSTATE_DB_PASSWORD`, `TFSTATE_DB_NAME` |
| GHCR | `GIT_ACCESS_TOKEN` (and `GIT_USER`, which the playbook reads directly and defaults to `x`) |

Everything else carries a `:-` default and can be omitted. Two of those defaults are DHBW-specific
and worth knowing about: `ACME_CA_URL` points at HARICA, and `DNS_SERVER` /`DNS_TSIG_KEY_ALG`
describe the zone that answers the dns-01 challenge.

`APP_HOSTNAME` must be a DNS name with a record pointing at the VM. ACME issues certificates for
domains, never for bare addresses — there is no longer any `<VM-IP>` to substitute, and no
self-signed fallback.

**Moodle (optional, `moodle_enabled=true`):** `MOODLE_HOSTNAME` (its own DNS name, same zone as
`APP_HOSTNAME` — Caddy issues one certificate per site block's domain, see `caddy/Caddyfile`'s
second block), `MOODLE_DB_PASSWORD`. `MOODLE_REPO_PATH` should match `moodle_repo_path` in
`infrastructure/ansible/staging.yml` (default `/home/ubuntu/moodle_appstore`) — the playbook clones
`moodle_appstore` there itself when `moodle_enabled` is set, no manual step needed (unlike prod's
`docker-compose.moodle.yml`, which still expects a manual clone).

**Do not define a key twice.** Compose takes the *last* occurrence, while the playbook's
`grep … | head -n1` for `APP_BASE_URL` takes the *first*. A duplicated key therefore does not
merely pick one value — it hands the containers and the Keycloak realm template two *different*
ones, and the stack starts cleanly while the backend disagrees with its own realm about what URL
it is served from.

### Notes / follow-ups

- The Trivy scan is intentionally non-blocking; review its findings and remove
  `continue-on-error` to enforce once the IaC is clean.
- State is local by design (see "Local state assumption"). A remote backend is the main
  remaining hardening item.

### Reusing this tooling in another repo

See [`EXTRACT.md`](EXTRACT.md) for a step-by-step recipe to copy the Terraform + Ansible +
workflows into another app repo: what to copy, what to recreate by hand (GitHub secrets,
local state), and the Galaxy-role gotcha (the role is no longer vendored, so the destination
must install it from `requirements.yml`).

### Deployment using act

Temporary solution while there is no remote state backend using [act](https://github.com/nektos/act):

```bash
act -W .github/workflows/staging.yml --bind --secret-file .secrets
```

With `--bind`, the container writes directly to your host directory, so `terraform.tfstate` lands
back in `infrastructure/terraform/envs/<env>/` on your machine and is reused next run. As noted
above, this is safe only for one person.

A better way is to create a key for deployment and use it without storing it in the .secrets file:

```bash

act -W .github/workflows/staging.yml --bind --secret-file .secrets \
  -s SSH_PRIVATE_KEY="$(cat ~/.ssh/openstack-deploy)"
```
