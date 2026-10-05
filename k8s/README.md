# K8s deployment (spike/k8s)

Pfisterer's AppStore (appstore-api, worker, self-service-ui with the AppStore
section) on the k3s cluster of OpenStack project `ma_wwi_24sea_appstore_g3`,
deployed by Argo CD. **Production (docker compose, `main`) is unaffected**:
the only workflow added is `k8s-images.yml`, triggered by pushes to `spike/**`
alone, and the cluster's Argo CD tracks `spike/k8s` only.

```
git push spike/k8s ──► k8s-images.yml builds 3 images ──► ghcr.io/dhbw-appstore-t3/k8s-*:spike-<sha>
                       └─ commits the tag to k8s/env/*.yaml [skip ci]
                                         │
Argo CD (root app, tracks spike/k8s) ◄───┘  syncs:
  cnpg · platform (Postgres, Keycloak) · role-provider-service · appstore-api · self-service-ui
```

| URL (zone `t3-k8s.s242437-at-student-dhbw-mannheim-de.users.dhbw.site`) | What |
| --- | --- |
| `pfisterer.<zone>` | UI (oauth2-proxy BFF in front) |
| `sso-pfisterer.<zone>` | Keycloak, realm `appstore` |
| `argocd.<zone>` | Argo CD |

## Layout
- `src/appstore-api`, `src/self-service-ui`: vendored copy of Pfisterer's code (his `appstore-api` has no public remote or published images yet). Re-sync by copying over.
- `argocd/`: root app + one Application per component. `manifests/platform/`: Postgres + Keycloak.
- `env/`: image tags, written by CI.
- `bootstrap.sh`: creates namespace + all Secrets (none in git), applies the root app. Run once.

## Demonstrator mode
`appstore.simulate` is **false** now (real OpenStack, `api.mode: production`). With `simulate: true` + `mode: development` OpenStack and the worker jobs are simulated; login and roles are real either way
(Keycloak + role-provider-service). Demo users: `faculty@cs.example` (Dozent), `cs-student@cs.com`
(student), `root.admin@uni.example` (AppStore admin); password printed by `bootstrap.sh`.
The role-provider keeps its data in Postgres; `manifests/seed` (Sync-hook Job) fills the demo course and roles. Edit the member list there to change who is Dozent / student / admin.
Add an OpenStack application credential in the UI (Credentials) as the Dozent.

## Not done yet / known limits
- No Trivy scan in `k8s-images.yml` (Pfisterer's CI has one).
- Pods reach `sso-pfisterer.<zone>` via public DNS (verified, no hairpin workaround needed).
- The cluster is IPv6-primary: every server in a container must bind `::`, not `0.0.0.0`.
- `platform` shows OutOfSync because of defaulted fields on the CNPG Cluster (cosmetic).
- Argo admin password change and removal of `argocd-initial-admin-secret` are still manual.
