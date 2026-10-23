# The AppStore on Kubernetes

Our AppStore (backend, worker, frontend) on the k3s cluster of OpenStack
project `ma_wwi_24sea_appstore_g3`, deployed by Argo CD (.github#4, migration
plan phase 4). Linux apps run as pods in a namespace `dep-<id>` per
deployment; the Windows desktop still runs as OpenStack VMs, through the VM
executor. The compose stack on `main` / `dev` (prod and staging VMs) is
untouched: nothing here runs for `main` or `dev`.

## Environments

| Environment | Git branch | Namespace | AppStore | Keycloak |
| --- | --- | --- | --- | --- |
| **prod** | `spike/main` | `appstore-prod` | `appstore.<zone>` | `sso.<zone>` |
| **staging** | `spike/dev` | `appstore-staging` | `appstore-staging.<zone>` | `sso-staging.<zone>` |
| **pfisterer** (reference, unmodified) | `spike/k8s` | `appstore` | `pfisterer.<zone>` | `sso-pfisterer.<zone>` |

`<zone>` = `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`. All
three share the one k3s node. `pfisterer` is Pfisterer's vendored original
(`k8s/src/`, kept as a reference, no longer built or deployed by this branch);
its Argo apps live on `spike/k8s` (root app `root`, which also owns the
cluster-wide `cnpg` operator).

```
backend / worker: push to spike/dev; frontend: push to spike/react-pods (the React
frontend; spike/vue-pods, the Vue one, is frozen and no longer deployed)
   └─ CI builds, scans and pushes the images (tags spike-dev / spike-react-pods and sha-<commit>)
   └─ CI dispatches k8s-bump.yml here with the pushed digest: it goes into k8s/env/appstore.yaml [skip ci]
                                        │ Argo CD (staging-root, tracks spike/dev)
                                        ▼
                                    STAGING  (appstore-staging.<zone>)
        k8s/promote.sh: PR spike/main <- k8s/ of spike/dev (same digests, no rebuild)
                                        │ Argo CD (prod-root, tracks spike/main)
                                        ▼
                                    PROD     (appstore.<zone>)
```

## What runs in an environment

| Application | Path | What |
| --- | --- | --- |
| `<env>-platform` (wave 1) | `manifests/platform` | CloudNativePG cluster (databases `appstore_t3`, `keycloak`; the reference stack's `appstore`, `roleprovider`), Keycloak with realms `dhbw` (ours) and `appstore` (reference) |
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
- `manifests/platform` (Postgres + Keycloak) and `manifests/seed` (the
  reference stack's demo roles; no longer deployed): charts, parametrised by host.
- `argocd/apps-chart`: renders every Argo Application of one environment from
  `environments/<env>.yaml`; `argocd/roots/<env>.yaml`: the environment's root.
- `env/appstore.yaml`: the image digests, written by CI. `environments/`: the
  per-environment values (the only difference between staging and prod).
- `tests/`: `render_env.py` renders an environment as Argo CD does;
  `policy/` evaluates the admission policy with kube-apiserver's evaluator;
  `cluster_probe.py` checks RBAC and policy in a kind cluster. CI:
  `.github/workflows/k8s-chart.yml`.
- `promote.sh`: staging -> prod PR. `bootstrap.sh <env>`: namespace, all
  Secrets (none in git), root app; safe to run again (adds missing keys, never
  rotates). `show-credentials.sh <env>` prints the logins.

## Switching an environment to our stack

The branch that brings this (`spike/pods-platform`) is not tracked by Argo CD.
Staging first; prod the same way after a successful staging test, through
`promote.sh`.

1. **Destroy the pod deployments of the reference stack** in its UI (the
   `dep-*` namespaces it created, e.g. `dep-cdab2d43`); our stack does not
   know them.
2. **Let the old Applications clean up after themselves.** They carry no
   finalizer, so removing them from the apps-chart would leave their
   Deployments, ClusterRoles and admission policy running:
   ```bash
   for app in appstore-api self-service-ui role-provider-service role-provider-seed; do
     kubectl -n argocd patch application "staging-$app" --type merge \
       -p '{"metadata":{"finalizers":["resources-finalizer.argocd.argoproj.io"]}}'
   done
   ```
3. **Secrets**: `GHCR_PULL_TOKEN_FILE=<file> k8s/bootstrap.sh staging` (from
   this branch). It adds the logins of `appstore_t3` and `appstore_worker`,
   the Secret `appstore-t3` (database URLs, two new Fernet keys, the Keycloak
   client secret of `appstore-backend`, the LTI session secret), the key
   `appstore-backend-client-secret` of `keycloak-secret` and the image pull
   Secret `ghcr-pull` (the file holds a token with `read:packages` only; our
   packages are private). Keycloak does not start without that key, by
   design. Run it again whenever this branch gains a key (e.g.
   `results-encryption-key`): pods do not start without their keys.
4. **Images**: push `spike/dev` of backend and worker and `spike/react-pods` of
   the frontend; their CI pins the new images in `k8s/env/appstore.yaml`.
   Until then the chart uses the moving `spike-dev` / `spike-react-pods` tags.
5. **Settings** in `environments/staging.yaml`: `appstore.api.openstackAllowedAuthUrls`
   (the DHBW Keystone, from the GitHub secrets; without it no VM app runs),
   the LTI settings if Moodle should launch the AppStore, and check
   `appstore.network.kubeApi` with `kubectl get svc,endpoints kubernetes -n default`.
6. **Merge** `spike/pods-platform` into `spike/dev`. Argo CD prunes the old
   Applications (and, through the finalizer, what they deployed), creates the
   database `appstore_t3`, imports realm `dhbw` (Keycloak restarts once, its
   settings change), sets the master realm's frontend URL (job
   `keycloak-admin-url`), migrates and starts our services.
7. **Check**: `kubectl -n argocd get applications | grep staging`; then the
   staging test of the migration plan (phase 7): every app with two teams of
   two people, access checked per person, pause/resume, restart/reset,
   destroy, cancel; the Windows app as a VM; the user search in the wizard
   (it uses Keycloak's admin API through the internal URL).
8. **Afterwards**: delete realm `appstore` and the reference stack's Secrets
   and databases by hand once nothing needs them (`--import-realm` never
   deletes a realm; CNPG keeps a database when its declaration goes).

Rolling back: revert the merge on `spike/dev`; the reference stack's
Applications come back (their data is still there).

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
