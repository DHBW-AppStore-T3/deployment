# The AppStore on Kubernetes

Our AppStore (backend, worker, frontend) on the k3s cluster of OpenStack
project `ma_wwi_24sea_appstore_g3`, deployed by Argo CD. Linux apps run as
pods in a namespace `dep-<id>` per deployment; Windows desktop apps run as
KubeVirt VMs in such a namespace (`runtime: kubevirt-vm`, golden image in the
namespace `vm-poc`, volumes on Cinder; `scripts/install-cinder-csi.sh`,
`scripts/migrate-golden-image.sh`, `scripts/enable-cross-namespace-clone.sh`,
noVNC proxy image from `docker/novnc-proxy`). This is the only deployment of
the AppStore: staging and prod run on k3s via Argo CD, and the local
development stack runs the exact same charts in a local `k3d` cluster via
`k8s/local/up.sh` (`make init` / `make dev-up`, see `docs/dev-setup.md`).

## Environments

| Environment | Git branch | Namespace | AppStore | Keycloak |
| --- | --- | --- | --- | --- |
| **prod** | `main` | `appstore-prod` | `appstore.<zone>` | `sso.<zone>` |
| **staging** | `dev` | `appstore-staging` | `appstore-staging.<zone>` | `sso-staging.<zone>` |

The second UI (self-service-ui, below) is on `self-service.<zone>` (prod) and `self-service-staging.<zone>` (staging): one label below the zone, for the wildcard certificate.
Moodle: `moodle.<zone>` (prod) and `moodle-staging.<zone>` (staging).

`<zone>` = `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`. Both
share the one k3s node.

```
push to dev  of a component (backend, worker, ...)     push to main of a component
   └─ CI: lint, test, scan, build, push to ghcr.io,       └─ the same
      sign the image's origin (attestation)
   └─ k8s-bump.yml (ref dev, started with a token of      └─ k8s-bump.yml (ref main): checks the origin,
      the GitHub App, see below): checks the origin,         PR with the digest -> k8s/images/prod.yaml;
      PR with the digest -> k8s/images/staging.yaml,         a person approves and merges it
      merged at once                                                     │ Argo CD (prod-root, tracks main)
                  │ Argo CD (staging-root, tracks dev)                    ▼
                  ▼                                                     PROD
              STAGING
push to dev of this repository (charts, policy, platform) -> staging; k8s/promote.sh: PR dev -> main -> prod
```

**Image provenance.** Only images our CI built are rolled out:
- Each component's CI signs, for the digest it pushed, which repository, workflow, branch and commit built it (`actions/attest`, keyless).
- Before pinning, `k8s-bump.yml` runs `.github/scripts/verify-image.sh`. A digest whose signature does not name the component's CI, the environment's branch (dev: staging, main: prod) and the commit of the tag is refused.
- Pull requests that change `images/*.yaml` by hand get the same verification from `image-provenance.yml` (required check "🔏 Image provenance"). The bump PRs get that check from `k8s-bump.yml`.
- The packages are private: each grants this repository read access (package settings → *Manage Actions access* → `deployment`: Read), because `gh` resolves the image on ghcr.io.

**Starting the bump.** The component CIs start `k8s-bump.yml` with a one-hour token of the GitHub App *DHBW AppStore deploy*. That app is installed only on this repository and has only *Actions: write*. Its client ID is the organisation variable `DEPLOY_APP_CLIENT_ID`, its private key the organisation secret `DEPLOY_APP_PRIVATE_KEY`; both are visible to the six component repositories only.

`appstore-mcp` (`charts/appstore-mcp`, Application `<env>-mcp`, host
`appstore-mcp[-staging].<zone>`): a read-only remote MCP server for agents
(`staging_verdict` after a push to dev), image key `appstoreMcp`. Secret
`appstore-mcp` is created by `bootstrap.sh`; a human adds the GitHub OAuth app
credentials (see the appstore-mcp repo, docs/OPERATIONS.md). Off on prod until
`main` has an image (`mcp.enabled` in `environments/prod.yaml`).

Apps (the things students deploy) are not part of this: they are registered
through the AppStore and run as pods; see the app-registry repository.

## What runs in an environment

| Application | Path | What |
| --- | --- | --- |
| `<env>-platform` (wave 1) | `manifests/platform` | CloudNativePG cluster (databases `appstore_t3`, `keycloak`), Keycloak with realm `dhbw` (ours) and `appstore` (reference) |
| `<env>-appstore` (wave 3) | `charts/appstore` | our services, below |
| `<env>-moodle` (wave 3) | `charts/moodle` | Moodle, see Moodle below |

`charts/appstore` (all names start with `appstore-t3-`):

| Component | Image | Runs as | Kubernetes rights | Reaches |
| --- | --- | --- | --- | --- |
| `api` (2 replicas) | `backend` | UID 10001, read-only root | read namespaces; in `dep-*` only the reader role (no Secrets) | Postgres, Keycloak, Kubernetes API, internet |
| `pod-deployer` | `worker-pods` | UID 10001, read-only root | creates/deletes `dep-*` namespaces and binds two roles in them; confined by the admission policy | Postgres, Kubernetes API |
| `frontend` (2 replicas) | `frontend` | UID 101, read-only root | none | the API |
| `migrate` (hook) | `backend` | UID 10001 | none | Postgres |
| `orphans` (hourly) | `backend` | UID 10001, the API's account | as the API | Postgres, Kubernetes API |

- **One Ingress per host**, to the frontend. Its nginx is the gateway for
  `/api` (prefix stripped, as Caddy does on the VMs). The API has no Ingress.
- **Migrations** run before every sync (Helm pre-install/pre-upgrade hook =
  Argo CD PreSync), as the database owner. Afterwards only roles that were
  granted `CONNECT` may open the database.
- **The worker's database role** `appstore_worker` is a CNPG managed role (its
  login comes from the Secret `appstore-worker-db`); the migrations grant it
  only the queue, task events and task results. `python -m app.worker_db_role`
  is not used here.
- **Two Fernet keys** (Secret `appstore-t3`): `credential-encryption-key` for
  the API only (it opens task results sealed before the results key existed);
  `results-encryption-key` (task results) for the API and the pod deployer.
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
  keep the student pods' isolation (the only `podSelector` peer is the empty
  selector, TCP with a concrete numeric port and no port range, in a policy named `allow-intra-namespace`; the app's `expose.port` is enforced by the renderer, not by admission: pods of one
  deployment may reach each other). Single objects are never deleted, only
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
  is changed in the admin console, except `loginTheme`: the job `keycloak-config`
  sets it in the live realm after each sync. The login page is the theme `dhbw`
  (T3 look, `manifests/platform/files/themes/dhbw`, mounted from ConfigMaps
  `keycloak-theme*`; the local dev stack mounts the same files; a changed theme
  restarts Keycloak). Demo users only on staging.

## The second UI: self-service-ui

Repository `self-service-ui` (fork of pfisterer/self-service-ui) with its App
Store section: catalog, one-click deploy, deployments and a student's own
access data, against the same API. Templates in `charts/appstore`
(`self-service-ui.yaml`), not a chart of its own: it shares the labels, the
hardening, the image pull Secret and, above all, the NetworkPolicies of the
API (which now admit it), and it is rolled out with the same Application.

One pod, two containers, read-only root filesystem, UID 65532, no service
account token: oauth2-proxy (`:4180`, the Ingress target) signs people in at
Keycloak and forwards to Caddy (`:8080`: the SPA, and `/api/app-store/*` to the
API with the prefix removed). The browser holds only the proxy's cookie.

- **Login**: Keycloak realm `dhbw`, client `appstore-self-service`: public, PKCE
  S256, redirect `https://<self-service host>/oauth2/callback`, audience mapper
  `appstore-api`. oauth2-proxy insists on a client secret and gets a
  placeholder that Keycloak ignores; the only secret is the proxy's cookie
  secret (`self-service-cookie-secret` in Secret `appstore-t3`, added by
  `bootstrap.sh`). The proxy forwards the **access token** as the Bearer; the
  API accepts it because `OIDC_ALLOWED_CLIENTS` lists the client
  (`keycloak.selfServiceClientId`, only while `selfServiceUi.enabled`).
- **Image**: `images.tags.selfServiceUi` (`k8s-bump.yml`, component
  `self-service-ui`). Empty: the component is not rendered.
- **No CORS entry** is needed: browser and API talk same-origin through Caddy.
- **A realm that already exists is not re-imported.** The client is in
  `dhbw-realm.json` for new realms; for a running one, once per environment
  (after the platform app has synced the change):

      export KUBECONFIG=...; k8s/keycloak-self-service-client.sh staging   # or prod

  It reads the client from the rendered realm (ConfigMap `keycloak-realm`),
  takes the admin password from `keycloak-secret` into a shell variable (never
  printed) and creates or updates the client through the admin REST API over
  `kubectl port-forward` (local port 8080). Idempotent. The same in the admin
  console: realm `dhbw`, Clients, Create (public, standard flow, PKCE S256).
- **Prod** has `selfServiceUi.enabled: false` until the client exists in its
  live realm; then set it and promote (`promote.sh`).

## Layout

- `charts/appstore`: our services (values documented in `values.yaml`).
- `charts/moodle`: Moodle (image from the `moodle_appstore` repository).
- `manifests/platform` (Postgres + Keycloak): chart, parametrised by host.
- `argocd/cluster/cnpg.yaml`: the CloudNativePG operator, shared by both
  environments (applied by `bootstrap.sh`).
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

## Moodle

Moodle (the `moodle_appstore` fork) runs on the cluster; there is no Moodle VM
or compose file any more.

- **Image**: built from the `Dockerfile` of `moodle_appstore` (Apache + PHP 8.3,
  UID 33, read-only root, port 8080). Its CI (`moodle-image.yml`) scans it with
  Trivy, pushes `ghcr.io/dhbw-appstore-t3/moodle_appstore:sha-<commit>` and
  dispatches `k8s-bump.yml` here with `component=moodle` (key `moodle` in
  `images/<env>.yaml`), like backend, worker and frontend.
- **`charts/moodle`**: Deployment `moodle-web` (1 replica, strategy Recreate),
  Service, Ingress `moodle.<zone>` (wildcard certificate), PVC `moodle-data`
  (`$CFG->dataroot`, never pruned by Argo CD), CronJob `moodle-cron` (every
  minute), NetworkPolicies (deny by default; ingress controller, Postgres, DNS,
  internet).
- **config.php** is baked into the image and reads its environment: `wwwroot`
  from `moodle.host`, database `moodle` on `postgres-cluster-rw` (CNPG role and
  database in `manifests/platform`, login Secret `moodle-db`), `sslproxy` on
  because TLS ends at Traefik.
- **Install / upgrade**: the init container `init` of `moodle-web` runs
  `docker/init.sh` of the image: an empty database gets
  `admin/cli/install_database.php` (admin password from Secret `moodle-admin`),
  an installed one `admin/cli/upgrade.php --non-interactive` on every new image.
- **Secrets** (`bootstrap.sh`, idempotent): `moodle-db`, `moodle-admin`;
  `show-credentials.sh` prints the admin login. Run `bootstrap.sh` (or create
  the two Secrets) before the platform application syncs the `moodle` role.
- **LTI 1.3** with the AppStore: in Moodle register the external tool with
  `https://<appstore-host>/api/lti13/login` and `/launch`, then set
  `appstore.api.lti` in `environments/<env>.yaml` (issuer =
  `https://<moodle-host>`).
- Not done: backups of the `moodle` database and of `moodle-data`; mail
  (SMTP) settings; the data of the old VM Moodle was not migrated (it was
  never installed on prod).

## Setting up an environment

Once per environment (the cluster has no other state that is not in git):

1. `GHCR_PULL_TOKEN_FILE=<file> k8s/bootstrap.sh staging|prod`. It creates the
   namespace and every Secret (database logins, Fernet keys, Keycloak client
   secrets, the image pull Secret `ghcr-pull`; the token needs `read:packages`
   only) and applies the environment's root Application. Run it again whenever
   the chart gains a Secret key; it never rotates existing ones. The generated
   logins are printed once (`show-credentials.sh <env>` prints them later).
2. Settings in `environments/<env>.yaml`: the LTI settings if Moodle should launch the AppStore, and check
   `appstore.network.kubeApi` with `kubectl get svc,endpoints kubernetes -n default`.
3. Check: `kubectl -n argocd get applications | grep <env>`.

Rolling back an image: set its digest in `images/<env>.yaml` back, with its tag
comment (a PR on `dev` or `main`); Argo CD follows. The required check accepts
only images whose CI signed their origin, i.e. built after the image provenance
was introduced (2026-10). An older image needs the check suspended by an admin
for that one PR. Rolling back anything else: revert the commit.

## Operating notes

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
