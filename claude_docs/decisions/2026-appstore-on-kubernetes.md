# Entscheidung: Der AppStore läuft auf Kubernetes (Migrationsplan Phase 0, D1–D10)

**Status:** vorgeschlagen; umgesetzt auf `spike/dev` (backend, worker, frontend) und `spike/pods-platform`
(deployment), Stand 2026-10-16. Die Abnahme im Team steht aus. Ergänzt `2026-pods-instead-of-vms.md` und ändert
dort Punkt 3 (zwei Rollen statt einer) und Punkt 7 (jeder Host gehört seinem Deployment).

## Kontext
Unser Stack lief mit Compose und Ansible auf VMs, alle Apps als OpenTofu/Packer-VMs. Das Pod-MVP (#4) gab es nur als
Kopie von Pfisterers Code im k8s-Staging, mit drei Befunden des Migrationsplans: `my-access` zeigte Teammitgliedern
fremde Zugangsdaten, App-Code (`local-exec`) lief im Pod mit dem Kubernetes-Token, und die Admission Policy erzwang
weder Pod Security `restricted` noch Nicht-Root-Container.

## Entscheidung
| # | Entscheidung | Umsetzung |
|---|---|---|
| D1 | Unser Code (backend, worker, frontend); Pfisterers Kopie nur als Referenz | Portiert auf `spike/dev`; `k8s/src/` rollt Argo CD nicht mehr aus |
| D2 | Windows bleibt VM, in einem eigenen Executor ohne Kubernetes-Rechte | `appstore-t3-vm-executor` (Queue `vm`, kein Service-Account-Token); VM-Code auf dem Stand von `dhbw-appstore` |
| D3 | Laufende VM-Deployments laufen bis zum Destroy; eine Linux-App bekommt nach freigegebener Pod-Version keine neue VM-Version | organisatorisch, bei der Freigabe |
| D4 | Kapazität, Nodes für Studierenden-Pods, Storage, Backups mit Pfisterer klären | **offen**, vor Prod nötig; `podApps.studentNodeSelector`/`studentTolerations` sind vorbereitet |
| D5 | Studierende melden sich mit einem generierten Passwort an; SSO vor den App-Ingresses später | Passwort in den versiegelten Task-Ergebnissen, `my-access` liefert genau den eigenen Eintrag |
| D6 | Unser Keycloak mit Realm `dhbw` auf k8s | Plattform-Chart, Realm gehärtet |
| D7 | Moodle bleibt auf seiner VM, nur die LTI-Hosts ändern sich | `appstore.api.lti` je Umgebung |
| D8 | #5 vorher auf Compose-Prod, wenn der Umstieg mehr als einen Monat entfernt ist | **offen** (Betrieb) |
| D9 | Gemeinsamer Code von backend und worker als identische Kopien mit Hash-Test | `app/k8s/{spec,render,kube,fake}.py`, `pgq.py`, `task_contract.py` u. a. (`test_shared_files.py`) |
| D10 | Images nur aus unserer Registry | Allowlist `ghcr.io/dhbw-appstore-t3/`, nur per Digest (API, Worker und Admission Policy) |

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
9. **CI:** rendert das Chart wie Argo CD, prüft mit kubeconform, dem Policy-Harness und einer kind-Probe; Pushes auf
   `spike/dev` pinnen die Images per Digest in `k8s/env/appstore.yaml` (`k8s-bump.yml`).

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
