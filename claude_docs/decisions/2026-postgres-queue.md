# Entscheidung: Postgres-Queue statt RabbitMQ und Redis, Celery bleibt (.github#5)

## Kontext
Celery lief über RabbitMQ (Broker) und Redis (Result-Backend). Das kostete drei zustandsbehaftete Dienste und
hatte Fehler, die im Code belegt sind:
- Jedes Worker-Event wurde einmal pro uvicorn-Prozess verarbeitet (vier Listener): Task-Update, Zugangs-Mails und
  Soft-Delete viermal.
- Live-Status nur innerhalb eines API-Prozesses (In-Process-Pub/Sub); keine Replikate, kein Wiederaufsetzen.
- Wiederzustellung langer Jobs nach `consumer_timeout` (20.09.: Windows-Build doppelt ausgeführt).
- Ergebnisse inklusive generierter Passwörter im Klartext in Redis; zwei Wahrheiten (DB und Celery) und ein
  Reconciler, der sie abgleicht.

## Entscheidung
**Option B aus .github#5:** eigener Kombu-Transport `pgq` (`backend/app/pgq.py` = `worker/app/pgq.py`), Celery bleibt.

- **Recherche (2026-10-09):** kein gepflegtes Paket mit dieser Funktion. `trunk` (PyPI, letzte Version 2013) ist
  Pub/Sub: jeder Worker bekommt jeden Job. `karellen-kombu-ext` (letzte Version 2016) pollt. Procrastinate (gepflegt,
  3.10.0 vom 2026-09-23) ersetzt Celery; das ist Option D und bleibt die Rückfalloption.
- **Messung** (lokal, PostgreSQL 16): Enqueue bis Task-Start 0–2 ms mit warmem Producer, 0–16 ms im Test (Timer-
  Auflösung unter Windows; der Test verlangt < 100 ms). Ohne NOTIFY findet der Fallback-Poll die Nachricht nach
  höchstens 5 s.
- **`kill -9`:** `worker/tests/test_worker_process.py::test_a_killed_worker_does_not_run_the_job_twice` (Linux-CI):
  Worker samt Kindprozessen per SIGKILL beendet, ein neuer Worker bekommt die Nachricht nach Ablauf der Lease, der Job
  startet **kein** zweites Mal, der Task endet als FAILED (`worker_lost`).
- **Verbindungen:** je API-Prozess eine LISTEN-Verbindung, dazu der SQLAlchemy-Pool und höchstens zwei Producer-
  Verbindungen; Worker-Hauptprozess drei (Kanal, LISTEN, Lease-Erneuerung); je Kindprozess eine (Cancel-LISTEN), je
  laufendem Job zwei (Events, Lease) plus kurze für Prolog und Epilog. Bei 4 uvicorn-Prozessen und Concurrency 4
  sind das rund 25 dauerhafte Verbindungen zusätzlich zu den Pools; `max_connections` (Default 100) im Blick behalten.

### Mechanik
- `celery_queue`: eine Zeile je Nachricht. Claim mit `FOR UPDATE SKIP LOCKED` und Lease (`visible_after`), die der
  Worker-Hauptprozess erneuert; Ack = `DELETE`; Requeue = wieder sichtbar; Wecken per `NOTIFY pgq_<queue>`.
  Celery-Task-ID = `tasks.taskId`; ein zweites Senden derselben Task ist wirkungslos (eindeutiger Index).
- Task-Prolog im Worker (`job_runtime`): `PENDING -> RUNNING` mit `claimed_by` und Lease auf der Task-Zeile. Kommt
  eine Nachricht für eine Task, die schon RUNNING ist und deren Lease abgelaufen ist, ist das eine Wiederzustellung
  nach einem toten Worker: FAILED (`worker_lost`), kein zweiter Lauf.
- Events: `task_events` (Trigger `NOTIFY task_events`), SSE aus der Tabelle mit `id:` und `Last-Event-ID`; Event-Namen
  unverändert, das Frontend bleibt gleich.
- Ergebnis: Status, Transkript und `outputs_enc` (Fernet über Outputs **und** State) schreibt der Worker selbst.
- Cancel: `cancel_requested_at` + CANCELLED + `task-revoked` in einer Transaktion; eine noch nicht abgeholte Nachricht
  wird gelöscht, sonst `NOTIFY task_cancel` an den Worker (killpg des laufenden Werkzeugs). Der Destroy danach wird
  **geparkt** (`celery_queue.after_task`), bis der Worker den abgebrochenen Job losgelassen hat (Security-Review A-5,
  Race 2).
- Folgearbeit genau einmal über `tasks.finalized_at` (Soft-Delete nach Destroy, Zugangs-Mails nach Deploy).
- Rolle `appstore_worker`: Queue, Event-Inserts, Ergebnis-Spalten von `tasks`; kein Zugriff auf `users`, `apps`,
  `user_openstack_credentials`, `deployments`.
- Build-Lock: Advisory-Lock auf einer eigenen Session statt Redis-Schlüssel.

## Abweichungen vom Issue
1. Der Reconciler sendet verlorene Dispatches (PENDING ohne Queue-Zeile, älter als 60 s) **nicht** erneut, sondern
   setzt sie auf FAILED: Die Argumente einer Nachricht existieren nur in der Nachricht. Antwort auf offene Frage 3.
2. `celery_queue` hat zusätzlich einen eindeutigen Index auf `task_id` und die Spalte `after_task` (geparkter Destroy
   statt eines erneuten Dispatches aus der API).
3. `outputs_enc` enthält Outputs und State; die Klartext-Spalten `outputs`/`tf_state` schreibt niemand mehr. Die
   Lesepfade (`backend/app/services/task_results.py`) verstehen beide Formen; die Datenmigration alter Zeilen bleibt
   bei .github#7 E.
4. Gemeinsamer Code: zwei identische Dateien (`pgq.py`, `task_contract.py`) mit Hash-Test in beiden Repos, noch kein
   `shared`-Paket (offene Frage 1).
5. Aufbewahrung: `task_events` bis 7 Tage nach Task-Ende; Live-Log höchstens 10 000 Zeilen je Task, danach eine Marke
   (offene Frage 2). Das vollständige Transkript steht in `tasks.logs`.
6. Ein Cancel bricht die langen Werkzeuge ab (terraform init/plan/apply/destroy, packer init/build); kurze Aufrufe
   (≤ 60 s: `terraform output`, OpenStack-CLI) laufen zu Ende, danach stoppt der Job.
7. `with_retries` für idempotente Phasen (Issue §2.4) ist nicht umgesetzt: Es wird weiterhin nichts automatisch
   wiederholt. Folge-Issue, sobald transiente Fehler klassifiziert sind.
8. Voraussetzung .github#7 A nur teilweise: Minimal-Umgebung und UID je Slot (A.1, A.2) umgesetzt; Var-Datei statt
   `-var` (A.3) und State-Rollen je Deployment (A.4) offen. App-Code sieht weiterhin `PG_CONN_STR` der State-DB.

## Umstellung (Staging, dann Prod)
1. Laufende Tasks abwarten (RabbitMQ leer).
2. Secret `WORKER_DB_PASSWORD` (mindestens 16 Zeichen) in `STAGING_ENV_FILE` bzw. `PRODUCTION_ENV_FILE` ergänzen.
3. Neue Images (`spike-dev` bzw. Release), Compose ohne `rabbitmq`/`redis`, Migrationen, `python -m app.worker_db_role`
   (Ansible macht beides), Worker-Neustart.
4. Alte Container entfernen: `docker rm -f rabbitmq-prod redis-prod` (Compose läuft ohne `--remove-orphans`).
   Volumes `rabbitmq_*`/`redis_*` erst nach einem Release löschen.

**Rückweg:** alte Images und Compose-Dateien; die Migrationen `5e1f0c2a9b7d` und `4d0e9b1a8c6f` haben ein Downgrade.
