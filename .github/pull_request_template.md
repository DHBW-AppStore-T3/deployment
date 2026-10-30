## Zusammenfassung

<!-- Was ändert dieser PR und warum? 1–3 Sätze. -->

Closes #

**Art der Änderung:** <!-- feat | fix | infra | config | ci | docs | chore; bei Änderungen, die manuelle Schritte im Cluster erfordern (z. B. `k8s/bootstrap.sh`, `k8s/cluster/`, Realm von Hand), zusätzlich "MANUELL" -->

**Betroffene Umgebungen:** <!-- lokal | staging | prod | Cluster (manuell) -->

## Prüfung

<!-- Wie wurde geprüft? Z. B. `make init` + `make health`, `python3 k8s/tests/render_env.py staging out.yaml`, Lauf von `k8s-chart.yml`, `kubectl`-/Argo-CD-Stand auf Staging (`staging_verdict`), `k8s/tests/netcheck/netcheck.py`. -->

## Checkliste

<!--
Checkliste für Änderungs-PRs (Feature-/Fix-Branch → `dev`, Hotfix → `main`).
Release-PRs (`dev` oder `promote/*` → `main`, z. B. von `k8s/promote.sh`)
verwenden stattdessen `.github/pull_request_template/release.md`. Die PRs von
`k8s-bump.yml` (Image-Digests, Branch `bump/*`) haben keine Checkliste: der
Workflow meldet den Check selbst als erledigt.

Jeder Punkt wird abgehakt, bevor der PR gemergt werden kann. Der CI-Check
"PR Checklist" blockiert den Merge, solange hier noch ein offenes "- [ ]" steht.

Trifft ein Punkt nicht zu: mit "n/a" markieren UND abhaken, z. B.
- [x] n/a, Chart: keine Änderung unter k8s/

Gitleaks,
Image-Provenance und bei Änderungen in `k8s/**` der Chart-Check (`k8s-chart.yml`:
Render von Staging und Prod, Kubernetes-Schemas, Admission-Policy, RBAC in kind)
laufen als CI-Checks und werden hier nicht wiederholt. kind erzwingt keine
NetworkPolicies; das prüft nur `k8s/tests/netcheck/netcheck.py` auf einem echten
Cluster.
-->

**Funktionale Eignung**

- [ ] Vollständigkeit: Alle Akzeptanzkriterien des verlinkten Issues sind umgesetzt; Abweichungen oder offene Punkte sind oben begründet
- [ ] Lokal verifiziert: Bei Änderungen an Chart, Policy oder `k8s/local/` läuft der lokale k3d-Cluster damit (`make init` bzw. `make up`), `make health` meldet alle Dienste healthy und der geänderte Ablauf funktioniert; Staging und Prod rendern (`python3 k8s/tests/render_env.py <staging|prod> out.yaml`) und der Diff der gerenderten Objekte ist erklärt
- [ ] Staging: Staging folgt `dev`, geprüft werden kann also erst nach dem Merge. Die Autorin oder der Autor prüft dann den Stand (Argo CD `Synced`/`Healthy`, `staging_verdict` über appstore-mcp, Skill `/verify-staging`; bei NetworkPolicies, CNI, Node-Guard oder Add-on-Policies zusätzlich `k8s/tests/netcheck/netcheck.py`) und trägt das Ergebnis im Release-PR ein

**Betrieb & Konfiguration**

- [ ] Konfiguration: Neue/geänderte Werte in `k8s/charts/appstore/values.yaml` und `k8s/environments/staging.yaml` **und** `prod.yaml` (oder begründet nur in einer), die Werte des lokalen Clusters in `k8s/local/up.sh` sowie `README.md`, `docs/dev-setup.md` und `k8s/README.md` nachgezogen
- [ ] Images & Secrets: Image-Digests (`k8s/images/*.yaml`) nicht von Hand geändert (schreibt `k8s-bump.yml`); neue Secret-Schlüssel kommen aus `k8s/bootstrap.sh`, nicht aus dem Repository
- [ ] Daten & Rollback: Keine Änderung löscht Volumes, Datenbanken oder Namespaces mit Daten; Backups gibt es noch nicht (`claude_docs/HANDOVER.md`, „Offen“), daher ist der Rückweg (Commit zurücknehmen; Digest in `k8s/images/<env>.yaml` zurücksetzen) im PR genannt

**Sicherheit & Doku**

- [ ] Sicherheit: Keine Secrets im Diff; neue `.gitleaksignore`-Einträge begründet; neu exponierte Ingress-Hosts, Ports, NetworkPolicies, RBAC-Rechte, Admission-Policy-Lockerungen oder Keycloak-Realm-/Client-Änderungen bewusst geprüft (neue Rechte des Pod-Deployers gehören in dessen ClusterRole **und** die Admission-Policy, Fälle in `k8s/tests/policy/make_cases.py`)
- [ ] Doku: `claude_docs/HANDOVER.md` aktualisiert; `README.md`, `docs/dev-setup.md`, `k8s/README.md` und Entscheidungen in `claude_docs/decisions/` nachgezogen, falls betroffen; bei geänderter Pipeline oder Architektur auch die Org-Doku in `DHBW-AppStore-T3/.github` unter `docs/` (`ci-cd/`, `c4/`, `technologiestack.md`)
