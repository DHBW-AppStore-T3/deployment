# The AppStore on Kubernetes

Our AppStore (backend, worker, frontend) on the k3s cluster of OpenStack
project `ma_wwi_24sea_appstore_g3`, deployed by Argo CD. Linux apps run as
pods in a namespace `dep-<id>` per deployment; the Windows desktop still runs
as OpenStack VMs, through the VM executor. This is the only deployment of the
AppStore: there is no compose stack and no vendored third-party code in this
repository any more.

## Environments

| Environment | Git branch | Namespace | AppStore | Keycloak |
| --- | --- | --- | --- | --- |
| **prod** | `main` | `appstore-prod` | `appstore.<zone>` | `sso.<zone>` |
| **staging** | `dev` | `appstore-staging` | `appstore-staging.<zone>` | `sso-staging.<zone>` |

`<zone>` = `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`. Both
share the one k3s node.

```
push to dev  of backend / worker / frontend            push to main of backend / worker / frontend
   └─ CI: lint, test, scan, build, push to ghcr.io        └─ the same
   └─ k8s-bump.yml (ref dev): digest -> k8s/images/       └─ k8s-bump.yml (ref main): PR with the digest
      staging.yaml, commit on dev                            -> k8s/images/prod.yaml, auto-merged after
                  │ Argo CD (staging-root, tracks dev)       the required checks
                  ▼                                                      │ Argo CD (prod-root, tracks main)
              STAGING                                                    ▼
                                                                       PROD
push to dev of this repository (charts, policy, platform) -> staging; k8s/promote.sh: PR dev -> main -> prod
```

Apps (the things students deploy) are not part of this: they are registered
through the AppStore and run as pods; see the app-registry repository.

## What runs in an environment

| Application | Path | What |
| --- | --- | --- |
| `<env>-platform` (wave 1) | `manifests/platform` | CloudNativePG cluster (databases `appstore_t3`, `keycloak`), Keycloak with realm `dhbw` (ours) and `appstore` (reference) |
| `<env>-appstore` (wave 3) | `charts/appstore` | our services, below |

`charts/appstore` (all names start with `appstore-t3-`):

| Component | Image | Runs as | Kubernetes rights | Reaches |
| --- | --- | --- | --- | --- |
| `api` (2 replicas) | `backend` | UID 10001, read-only root | read namespaces; in `dep-*` only the reader role (no Secrets) | Postgres, Keycloak, Kubernetes API, internet |
| `pod-deployer` | `worker-pods` | UID 10001, read-only root | creates/deletes `dep-*` namespaces and binds two roles in them; confined by the admission policy | Postgres, Kubernetes API |
| `vm-executor` | `worker` | root with 6 capabilities, to run each slot's tools as UID 20000+n | none (no token) | Postgres, the API (state backend), internet |
| `frontend` (2 replicas) | `frontend` | UID 101, read-only root | none | the API |
| `migrate` (hook) | `backend` | UID 10001 | none | Postgres |
| `orphans` (hourly) | `backend` | UID 10001, the API's account | as the API | Postgres, Kubernetes API |

- **One Ingress per host**, to the frontend. Its nginx is the gateway for
  `/api` (prefix stripped, as Caddy does on the VMs) and answers
  `/api/internal/` (OpenTofu's state backend) with 404. The API has no Ingress.
- **Migrations** run before every sync (Helm pre-install/pre-upgrade hook =
  Argo CD PreSync), as the database owner. Afterwards only roles that were
  granted `CONNECT` may open the database.
- **The worker's database role** `appstore_worker` is a CNPG managed role (its
  login comes from the Secret `appstore-worker-db`); the migrations grant it
  only the queue, task events and task results. `python -m app.worker_db_role`
  is not used here.
- **Two Fernet keys** (Secret `appstore-t3`): `credential-encryption-key`
  (OpenStack credentials at rest, the VM jobs' credential envelopes and state
  tokens) for the API and the VM executor; `results-encryption-key` (task
  results) for the API and both workers. The pod deployer has only the
  second: as a worker it can read the job queue, where the VM jobs'
  envelopes travel.
- **NetworkPolicies**: deny by default, then only the flows in the table.
  "Internet" excludes the private and link-local ranges (the metadata service
  among them) and the cluster's own ranges (`podApps.extraEgressExcept`).
  Keycloak and Postgres are not selected.
- **Admission policy** (`templates/admission-policy.yaml`, migration plan
  finding 3): the pod deployer may only touch `dep-<8 hex>` namespaces of its
  own installation (label `appstore.dhbw/environment`), each with Pod Security
  `restricted`; only Opaque Secrets, ClusterIP Services, a quota without node
  ports or load balancers, role bindings of exactly its two roles; pod
  templates without root, privileges, added capabilities, host namespaces,
  host paths, service account token or scheduling overrides, images from the
  allowlist pinned by digest; Ingress hosts `<workload>-<deployment>.<appDomain>`
  of its own deployment only (never `appstore.<zone>` or `sso.<zone>`), plain
  `Prefix` paths, no annotations but cert-manager's; network policies that
  keep the student pods' isolation. Single objects are never deleted, only
  namespaces, pods (restart) and volume claims (reset).
- **Keycloak realm `dhbw`**: access tokens of 5 minutes, refresh token
  rotation, brute-force protection, a password policy, PKCE S256 and no
  password grant for `appstore-frontend`, an audience mapper `appstore-api`,
  users cannot change their e-mail. Only `/realms/dhbw/`, `/realms/appstore/`
  and `/resources/` are on the public host: the master realm and the admin
  console are reached with `kubectl -n <ns> port-forward svc/keycloak 8080`
  (then <http://localhost:8080/admin/>, user `admin`, password from
  `show-credentials.sh`). The local port has to be 8080: the console and the
  master realm's login pages are built for <http://localhost:8080> (the job
  `keycloak-admin-url` gives the master realm that frontend URL after each
  sync). Realm files are imported into a new database only; a running realm
  is changed in the admin console. Demo users only on staging.

## Layout

- `charts/appstore`: our services (values documented in `values.yaml`).
- `manifests/platform` (Postgres + Keycloak): chart, parametrised by host.
- `argocd/apps-chart`: renders every Argo Application of one environment from
  `environments/<env>.yaml`; `argocd/roots/<env>.yaml`: the environment's root.
- `images/<env>.yaml`: the image digests, written by CI (dev writes staging,
  main writes prod). `environments/`: the per-environment values.
- `tests/`: `render_env.py` renders an environment as Argo CD does;
  `policy/` evaluates the admission policy with kube-apiserver's evaluator;
  `cluster_probe.py` checks RBAC and policy in a kind cluster. CI:
  `.github/workflows/k8s-chart.yml`.
- `promote.sh`: PR dev -> main. `bootstrap.sh <env>`: namespace, all
  Secrets (none in git), root app; safe to run again (adds missing keys, never
  rotates). `show-credentials.sh <env>` prints the logins.

## Setting up an environment

Once per environment (the cluster has no other state that is not in git):

1. `GHCR_PULL_TOKEN_FILE=<file> k8s/bootstrap.sh staging|prod`. It creates the
   namespace and every Secret (database logins, Fernet keys, Keycloak client
   secrets, the image pull Secret `ghcr-pull`; the token needs `read:packages`
   only) and applies the environment's root Application. Run it again whenever
   the chart gains a Secret key; it never rotates existing ones. The generated
   logins are printed once (`show-credentials.sh <env>` prints them later).
2. Settings in `environments/<env>.yaml`: `appstore.api.openstackAllowedAuthUrls`
   (the DHBW Keystone, from the GitHub secrets; without it no VM app runs),
   the LTI settings if Moodle should launch the AppStore, and check
   `appstore.network.kubeApi` with `kubectl get svc,endpoints kubernetes -n default`.
3. Check: `kubectl -n argocd get applications | grep <env>`.

Rolling back an image: set its digest in `images/<env>.yaml` back (commit on
`dev`, or a PR on `main`); Argo CD follows. Rolling back anything else: revert
the commit.

## Operating notes

- **Real OpenStack only for the Windows desktop**: a teacher adds an
  application credential under Settings. Use a separate credential for
  staging.
- **Demo users** (staging): `dozent.demo` (teacher), `admin.demo` (admin),
  `student1.demo` ... `student4.demo`; password: `show-credentials.sh staging`.
  Production has none: create the first admin in the admin console
  (realm `dhbw`, role `admin`) and connect the university's identity provider
  there; its mappers must deliver a verified e-mail address that users cannot
  edit.
- **IPv6-primary cluster**: every server in a container binds `::`. Build VMs
  in the DHBWV6 network are reached over IPv6; the build security group must
  allow TCP/22 from the node.
- **k3s updates itself** nightly between 02:00 and 04:00 (single node, short
  outage for all environments).
- **Not done yet**: backups of the CNPG cluster and of the student volumes,
  separate nodes for student pods (`podApps.studentNodeSelector` and
  `studentTolerations`, migration plan D4), image signatures (cosign), a full
  end-to-end job (API, workers and real pods in kind), network policy probes
  in CI (kind's CNI does not enforce them; check them on staging).
