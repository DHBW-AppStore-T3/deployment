# pgAdmin 4 – PostgreSQL-Administration mit Beispieldatenbank

Eine pgAdmin4-Instanz pro Team mit einer vorinstallierten PostgreSQL-Datenbank
(Pagila-Beispieldatensatz). Die App läuft als Pods (App-Vertrag v2), nicht mehr als VMs:
**ein Pod pro Team** mit zwei Containern, pgAdmin 4 (per HTTPS-Link erreichbar) und PostgreSQL
mit der Pagila-Beispieldatenbank. Beide teilen sich ein Volume (2 GiB), sodass Konfiguration und
Daten Pause/Fortsetzen und Neustart überstehen.

## User-Management

Es wird **ein pgAdmin-Account pro Team** erstellt, alle Mitglieder eines Teams teilen sich
denselben Login.

- **Login:** Benutzername `pgadmin@dhbw.de` (für alle Teams gleich), das Passwort wird von der
  Plattform erzeugt und steht nach dem Deployment unter „Meine Zugänge“.
- **Datenbank:** Der Server „pagila (local)“ (Film-/Videoverleih-Schema) ist im pgAdmin-Account
  vorkonfiguriert. Das Passwort für `pagila_user` ist `pagila` und wird beim ersten Verbinden
  abgefragt.

## Deployment

Es wird **ein Pod pro Team** deployed. Bei zwei Teams entstehen zwei Pods mit eigenem Link und
eigenem pgAdmin-Login. Pagila wird beim Bau des Images geladen, nicht beim Start.

## Konfigurierbare Variablen

Keine. Kein File-Upload, alle Einstellungen stehen in der `appstore.yaml` der App.
