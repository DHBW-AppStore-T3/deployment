# K8s deployment (spike)

Pfisterer's AppStore (appstore-api, worker, self-service-ui with the AppStore
section) on the k3s cluster of OpenStack project `ma_wwi_24sea_appstore_g3`,
deployed by Argo CD. The compose stack on `main` / `dev` (prod and staging VMs)
is **untouched**: nothing here runs for `main` or `dev`, and these branches
only add the `k8s/` tree and one workflow.

## Environments

| Environment | Git branch | Namespace | UI | Keycloak |
| --- | --- | --- | --- | --- |
| **prod** | `spike/main` (from `main`) | `appstore-prod` | `appstore.<zone>` | `sso.<zone>` |
| **staging** | `spike/dev` (from `dev`) | `appstore-staging` | `appstore-staging.<zone>` | `sso-staging.<zone>` |
| **pfisterer** (reference, unmodified) | `spike/k8s` | `appstore` | `pfisterer.<zone>` | `sso-pfisterer.<zone>` |

`<zone>` = `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`.
All three share the one k3s node, each has its own Postgres, Keycloak realm,
role-provider and Secrets. `pfisterer` is the vendored original, kept as the
reference to compare against while technologies are cherry-picked into
staging/prod. Its Argo apps live on `spike/k8s` (root app `root`, which also
owns the cluster-wide `cnpg` operator that all environments use).

```
spike/dev  push ─► k8s-images.yml builds 3 images ─► ghcr.io/dhbw-appstore-t3/k8s-*:spike-<sha>
                   └─ commits the tag to k8s/env/*.yaml [skip ci]
                                        │ Argo CD (staging-root, tracks spike/dev)
                                        ▼
                                    STAGING  (appstore-staging.<zone>)
        k8s/promote.sh: PR spike/main <- k8s/ of spike/dev (same images, no rebuild)
                                        │ Argo CD (prod-root, tracks spike/main)
                                        ▼
                                    PROD     (appstore.<zone>)
```

**Promotion** is `k8s/promote.sh`: it opens a PR that changes only `k8s/` on `spike/main`; a human merges it. (A plain merge of `spike/dev` would also drag the other differences between `dev` and `main` along, e.g. the reverts that exist on `main` on purpose.)

Keep the branches on top of the real stack: merge `dev` into `spike/dev` and
`main` into `spike/main` regularly. Taking a technology over into the real
branches is then a normal merge/cherry-pick of `k8s/`.

## Layout
- `src/appstore-api`, `src/self-service-ui`: vendored copy of Pfisterer's code (his `appstore-api` has no public remote or published images yet).
- `argocd/apps-chart`: Helm chart that renders every Argo Application of one environment from `environments/<env>.yaml`. `argocd/roots/<env>.yaml`: the environment's root Application.
- `manifests/platform` (Postgres + Keycloak) and `manifests/seed` (demo roles): charts, parametrised by host.
- `env/`: image tags written by CI. `environments/`: per-environment values (the only difference between staging and prod).
- `promote.sh`: staging -> prod PR. `bootstrap.sh <env>`: creates namespace + all Secrets (none in git) and applies the root app. Run once per environment. `show-credentials.sh <env>` prints the logins.

## Operating notes
- Real OpenStack (`appstore.simulate: false`, `api.mode: production`). Add an application credential in the UI (Credentials) as the Dozent. **Use a separate credential for staging** so staging tests do not touch prod VMs; both deploy into the same OpenStack project.
- Demo users (`faculty@cs.example` Dozent, `cs-student@cs.com` student, `root.admin@uni.example` admin) exist in every environment until a real identity provider is wired in; the password is per environment (`show-credentials.sh`).
- The cluster is IPv6-primary: every server in a container must bind `::`, not `0.0.0.0`. Build VMs in the DHBWV6 network are reached over IPv6 (Packer `ssh_ip_version = 6`); the build security group must allow TCP/22 from the node.
- k3s updates itself nightly between 02:00 and 04:00 (single node, short outage for all environments).

## Not done yet / known limits
- No Trivy scan in `k8s-images.yml` (Pfisterer's CI has one).
- No branch protection on `spike/main` yet: promote through a PR by convention.
- `platform` apps show OutOfSync because of defaulted fields on the CNPG Cluster (cosmetic).
