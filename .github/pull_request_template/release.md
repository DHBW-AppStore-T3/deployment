## Release nach `main`

<!--
Release-PR: bringt `dev` (oder einen `promote/*`-Branch mit einem Teil von
`dev`) in Produktion: Charts, Admission-Policy, Platform-Manifeste und
Keycloak-Realm. Argo CD (`prod-root`) verfolgt `main`: Mit dem Merge wird die
Änderung ohne weitere Freigabe auf Produktion synchronisiert (der Job
`migrate` läuft vor jedem Sync). Image-Digests gehören nicht hierher: Die
schreiben die CI-Läufe von backend, worker, frontend usw. auf `main` über
eigene PRs (`bump/prod-*`, `k8s/images/prod.yaml`).

Anlegen: `k8s/promote.sh` (legt den PR mit dieser Vorlage an) oder
  gh pr create --base main --head dev --title "release: <Datum>" \
    --body-file .github/pull_request_template/release.md
oder im Browser: .../compare/main...dev?expand=1&template=release.md

Mit Merge-Commit mergen, nicht squashen, damit `dev` und `main` nicht
auseinanderlaufen.
-->

**Enthaltene PRs:**

<!-- Alle PRs seit dem letzten Release, z. B. aus `git log --oneline origin/main..origin/dev` (ohne die Digest-Bumps `chore(k8s): roll out …`). PRs mit "MANUELL" kennzeichnen. -->

-

**Staging:** <!-- Stand von Argo CD auf Staging für diesen `dev`-Stand (`staging_verdict`, Skill `/verify-staging`) -->

**Release-Reihenfolge:** <!-- Nur falls backend/worker/frontend mitziehen. Chart-Änderungen, die ein neueres Image voraussetzen (neue Variablen, Rechte), gehen erst nach dessen Release nach `main`. Sonst "nur deployment". -->

**Manuelle Schritte:** <!-- Was muss vor/nach dem Merge von Hand im Cluster passieren (`k8s/bootstrap.sh prod`, `k8s/keycloak-self-service-client.sh prod`, `k8s/cluster/*`, `scripts/*`), wer macht es, wann? Sonst "keine". -->

## Release-Checkliste

<!--
Jeder Punkt wird abgehakt, bevor der PR gemergt werden kann. Trifft ein
Punkt nicht zu: mit "n/a" markieren UND abhaken, z. B.
- [x] n/a — Realm: keine Änderung an dhbw-realm.json

Die Änderungs-Checklisten der enthaltenen PRs werden hier nicht wiederholt.
Dieser PR prüft, ob der gesammelte Stand in Produktion darf. Gitleaks,
Image-Provenance und der Chart-Check (`k8s-chart.yml`) laufen als CI-Checks.
-->

- [ ] Staging: Dieser `dev`-Stand läuft auf Staging (Argo CD `Synced`/`Healthy`, `staging_verdict` ohne Befund) und die enthaltenen Änderungen wurden dort geprüft
- [ ] Enthaltene PRs: Liste oben vollständig; jeder enthaltene PR hat eine vollständige Checkliste; PRs, die ohne Review auf `dev` gemergt wurden, sind in diesem PR reviewt
- [ ] Prod-Render: `python3 k8s/tests/render_env.py prod out.yaml` rendert; der Diff gegenüber dem bisherigen Prod-Stand enthält keine unbeabsichtigten Löschungen oder Ersetzungen (Namespaces, Volumes, Datenbank, Ingress, NetworkPolicies, RBAC)
- [ ] Kompatibilität: Chart und Policy passen zu den Images, die auf Prod laufen (`k8s/images/prod.yaml`); was ein neueres backend, worker oder frontend voraussetzt, geht erst nach deren Release nach `main` (Reihenfolge oben)
- [ ] Cluster & Secrets: Neue Secret-Schlüssel (`k8s/bootstrap.sh prod`), Cluster-Manifeste (`k8s/cluster/`, `scripts/`) und Änderungen an laufenden Keycloak-Realms (ein bestehender Realm wird nicht neu importiert) sind auf Prod erledigt, bevor gemergt wird
- [ ] Image-Digests: Der Diff ändert `k8s/images/prod.yaml` nicht (nur `k8s-bump.yml` auf `main` schreibt sie); Änderungen an `staging.yaml` sind erwartet
- [ ] Manuelle Schritte: Alle "MANUELL"-Schritte stehen oben, mit Person und Zeitpunkt
- [ ] Daten & Rollback: Keine Änderung löscht Produktionsdaten oder -Volumes; Backups gibt es noch nicht (`claude_docs/HANDOVER.md`, „Offen“); der Rückweg ist bekannt (Revert-PR auf `main`, den Argo CD synchronisiert)
