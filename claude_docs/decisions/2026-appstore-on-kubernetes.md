# Entscheidung: Der AppStore läuft auf Kubernetes (Migrationsplan Phase 0, D1–D10)

> **Teilweise abgelöst durch .github#12 (OpenStack-VM-Pfad entfernt):** Es gibt keinen VM-Executor, keine Queue `vm`,
> keine OpenStack-Zugangsdaten, kein State-Backend und keinen Credential-Schlüssel für OpenStack-Zugangsdaten. Alle
> Apps laufen als Pods oder KubeVirt-VMs über den Pod-Deployer. Überholt sind D2, D3, „Beim Bauen entschieden“ Punkt 4
> (nur `/api/internal/`), 5 und 6, der Abschnitt „Restrisiko VM-Pfad“ und die VM-States in Plan-Phase 7. Der Rest gilt.

## Kontext
Unser Stack lief mit Compose und Ansible auf VMs, alle Apps als OpenTofu/Packer-VMs. Das Pod-MVP (#4) gab es nur als
Kopie von Pfisterers Code im k8s-Staging, mit drei Befunden des Migrationsplans: `my-access` zeigte Teammitgliedern
fremde Zugangsdaten, App-Code (`local-exec`) lief im Pod mit dem Kubernetes-Token, und die Admission Policy erzwang
weder Pod Security `restricted` noch Nicht-Root-Container.

## Entscheidung
| # | Entscheidung | Umsetzung |
|---|---|---|
| D1 | Unser Code (backend, worker, frontend); Pfisterers Kopie nur als Referenz | Portiert nach `dev`; `k8s/src/` ist entfernt. Das Frontend wurde danach in React neu geschrieben (frontend#36) |
| D2 | Windows bleibt VM, in einem eigenen Executor ohne Kubernetes-Rechte | `appstore-t3-vm-executor` (Queue `vm`, kein Service-Account-Token); VM-Code auf dem Stand von `dhbw-appstore` |
| D3 | Laufende VM-Deployments laufen bis zum Destroy; eine Linux-App bekommt nach freigegebener Pod-Version keine neue VM-Version | organisatorisch, bei der Freigabe |
| D4 | Kapazität, Nodes für Studierenden-Pods, Storage, Backups mit Pfisterer klären | **offen**, vor Prod nötig; `podApps.studentNodeSelector`/`studentTolerations` sind vorbereitet |
| D5 | Studierende melden sich mit einem generierten Passwort an; SSO vor den App-Ingresses später | Passwort in den versiegelten Task-Ergebnissen, `my-access` liefert genau den eigenen Eintrag |
| D6 | Unser Keycloak mit Realm `dhbw` auf k8s | Plattform-Chart, Realm gehärtet |
| D7 | Moodle zieht ebenfalls auf Kubernetes um (`charts/moodle`, ersetzt die VM-Variante); die LTI-Hosts stehen in `appstore.api.lti` je Umgebung | `charts/moodle`, `moodle_appstore`-Image |
| D8 | #5 vorher auf Compose-Prod, wenn der Umstieg mehr als einen Monat entfernt ist | **offen** (Betrieb) |
| D9 | Gemeinsamer Code von backend und worker als identische Kopien mit Hash-Test | `app/k8s/{spec,render,kube,fake}.py`, `pgq.py`, `task_contract.py` u. a. (`test_shared_files.py`) |
| D10 | Images nur aus unserer Registry | Allowlist `ghcr.io/dhbw-appstore-t3/apps/` (die App-Pakete, nicht alle Pakete der Organisation), nur per Digest (API, Worker und Admission Policy) |

## Beim Bauen entschieden
1. **Ein Chart** `k8s/charts/appstore` (alle Namen `appstore-t3-*`) statt der vier Applications der Referenz, als eine
   Argo-CD-Application `<env>-appstore` mit Finalizer.
2. **Pod-Deployer:** legt nur `dep-<8 hex>`-Namespaces seiner Installation an und löscht sie; darin bindet er genau
   zwei Rollen, seine eigene und eine Leserolle für die API (ändert Punkt 3 des MVP). Die ValidatingAdmissionPolicy
   begrenzt jede seiner Anfragen (Liste in `k8s/README.md`), geprüft mit dem VAP-Evaluator von kube-apiserver
   (`k8s/tests/policy`). Kein Internet-Egress, er holt nichts aus App-Repositories.
3. **Hosts** `<workload>-<namespace-id>.<appDomain>`, `appDomain` = Zone (Wildcard-Zertifikat, wie im MVP). Die Policy
   bindet jeden Host an das Deployment seines Namespaces, weil `appstore.` und `sso.` in derselben Zone liegen.
   Ingress-Pfade nur aus einfachen Segmenten: Traefik baut daraus ``PathPrefix(`…`)``, ein Backtick hätte fremde
   Hosts umgeleitet.
4. **Ein Ingress je Host**, zum Frontend; dessen nginx ist Gateway für `/api` (Präfix entfernt wie bei Caddy) und
   beantwortet `/api/internal/` (State-Backend) mit 404. Die API hat keinen Ingress.
5. **VM-Executor:** root nur für den Wechsel zum Slot-User (UID 20000+n, sechs Capabilities). Vor und nach jedem Job
   werden dessen Prozesse beendet, das Home ist leer. Nach der Übergabe schreibt der Worker nichts mehr als root ins
   Job-Verzeichnis. Variablen stehen in privaten Var-Dateien (auch für Packer). Der State liegt im HTTP-Backend der
   API, mit einem Token je Task (Stand `dhbw-appstore`, statt der DB-Rolle je Deployment aus Plan-Phase 6). Egress:
   Postgres, API und Internet (NetworkPolicies kennen keine Hostnamen; OpenStack, Git, Provider und Plugins kommen
   von dort).
6. **Zwei Fernet-Keys:** Credentials (API, VM-Executor) und Task-Ergebnisse (API, beide Worker). Der Pod-Deployer hat
   nur den zweiten, denn er kann die Queue lesen, in der die Credential-Umschläge der VM-Jobs liegen.
7. **Datenbank:** Migrationen als PreSync-Hook mit der Owner-Rolle, danach `REVOKE CONNECT … FROM PUBLIC`; Verbindungen
   mit `sslmode=require`; `appstore_worker` als CNPG-Managed-Role.
8. **Keycloak:** öffentlich nur `/realms/dhbw/`, `/realms/appstore/` und `/resources/`; Master-Realm und
   Admin-Konsole per `kubectl port-forward`; Demo-Nutzer nur auf Staging.
9. **CI:** rendert das Chart wie Argo CD, prüft mit kubeconform, dem Policy-Harness und einer kind-Probe; die CI der
   Komponenten pinnt ihre Images per Digest in `k8s/images/<staging|prod>.yaml` (`k8s-bump.yml`: auf `dev` direkt, auf
   `main` als Pull Request, den eine Person mergt).

## Offen
- D4 und D8.
- Plan-Phase 5: Apps (Online-IDE und template-app mergen, pgAdmin fertigstellen, Jupyter, Web-LaTeX, Ubuntu-App),
  Init-Container für Dateien über 1 MiB, `AppentwicklerGuide.md` in `.github`.
- Plan-Phase 7: Staging-Test (alle Apps, mindestens zwei Teams mit mindestens zwei Personen, Zugang je Person), dann
  Prod: App- und Keycloak-Datenbank umziehen, VM-States mit `python -m app.import_pg_tfstate` übernehmen, DNS und
  LTI-Host umstellen, Compose abschalten.
- Plan-Phase 8 und Betrieb: SSO vor den App-Ingresses, Image-Signaturen (cosign), gVisor/Kata oder ein eigener
  Cluster für Studierenden-Workloads, Backups (CNPG, Volumes), Monitoring.
- Restrisiko VM-Pfad: Destroy und Redeploy führen den OpenTofu-Code der App mit dem Credential der auslösenden Person
  aus, auch eines Admins. Davor schützt nur die Freigabe der App-Version (#7 G).

## Nachträge (Review 2026-10-24, `docs/REVIEW-PODS-MIGRATION-2026-10-24.md`)
- **D1:** Mit dem React-Frontend und der self-service-ui stehen zwei Oberflächen vor einer API. Beide bleiben; weil
  Studierenden-Apps auf derselben Site liegen, lehnt die API Schreibzugriffe ab, die ein Browser für eine fremde Seite
  sendet (`Sec-Fetch-Site`/`Origin`, backend#28).
- **D4:** weiterhin offen; Prod ging ohne die Klärung live.
- **D7:** Moodle läuft im selben Namespace und Postgres-Cluster wie der AppStore (nicht mehr auf seiner VM).
- **Identität:** LTI-Konten hängen an `iss` + `sub` statt an der E-Mail, Kurse an `context.id`; die Rolle ist die
  höchste der Aussagen von Keycloak, letztem LTI-Launch und Admin-Vergabe (backend#29).
