## Release nach `main`

<!--
Release-PR: bringt `dev` (oder einen `promote/*`-Branch mit einem Teil von
`dev`) in Produktion. Der Merge auf `main` startet `production.yml`:
Terraform plan + apply für `envs/production` OHNE weitere Freigabe, danach
Ansible mit `docker-compose.prod.yml`, den aktuellen `latest`-Images und
`alembic upgrade head`.

Anlegen:
  gh pr create --base main --head dev --title "release: <Datum>" \
    --body-file .github/pull_request_template/release.md
oder im Browser: .../compare/main...dev?expand=1&template=release.md

Mit Merge-Commit mergen, nicht squashen, damit `dev` und `main` nicht
auseinanderlaufen.
-->

**Enthaltene PRs:**

<!-- Alle PRs seit dem letzten Release, z. B. aus `git log --oneline origin/main..origin/dev`. PRs mit "MANUELL" kennzeichnen. -->

-

**Staging:** <!-- Link zum Staging-Deploy-Lauf und zum Hermes-Report für diesen Stand -->

**Release-Reihenfolge:** <!-- Nur falls backend/worker/frontend mitziehen. Neue Variablen und Compose-Änderungen gehen in der Regel zuerst nach `main`. Sonst "nur deployment". -->

**Manuelle Schritte:** <!-- Was muss vor/nach dem Merge von Hand passieren, wer macht es, wann? Sonst "keine". -->

## Release-Checkliste

<!--
Jeder Punkt wird abgehakt, bevor der PR gemergt werden kann. Trifft ein
Punkt nicht zu: mit "n/a" markieren UND abhaken, z. B.
- [x] n/a — Terraform: keine Änderung an envs/production oder modules

Die Änderungs-Checklisten der enthaltenen PRs werden hier nicht wiederholt.
Dieser PR prüft, ob der gesammelte Stand in Produktion darf. Gitleaks läuft
als CI-Check, Terraform-Format und IaC-Scan im Produktions-Deploy.
-->

- [ ] Staging: Dieser Stand ist auf Staging deployt; Staging-Deploy grün, Hermes-Healthcheck GUT
- [ ] Enthaltene PRs: Liste oben vollständig; jeder enthaltene PR hat eine vollständige Checkliste; PRs, die ohne Review auf `dev` gemergt wurden, sind in diesem PR reviewt
- [ ] Terraform: Änderungen an `envs/production` oder `modules/` liefen gleichwertig auf Staging, und der Produktions-Plan enthält keine unbeabsichtigten `destroy`/`replace` (VM, Volumes, Netz), da `production.yml` ohne Freigabe anwendet
- [ ] Secrets: Neue oder geänderte Werte sind in den Produktions-Secrets gesetzt (`PRODUCTION_ENV_FILE`, `PROD_OS_*`, `SSH_PRIVATE_KEY`, `HERMES_VM_IPV6`), bevor gemergt wird
- [ ] Manuelle Schritte: Alle "MANUELL"-Schritte stehen oben, mit Person und Zeitpunkt
- [ ] Daten & Rollback: Keine Änderung löscht Produktions-Volumes oder -Daten ohne vorheriges Backup; der Rückweg ist bekannt (Revert-PR auf `main`, der `production.yml` erneut auslöst; `claude_docs/rollback/`)
