# Ubuntu Terminal App

Eine einfache Linux-Lernumgebung für Hochschulkurse. Die App läuft als Pod (App-Vertrag v2),
nicht mehr als VM: **ein Web-Terminal pro Person**, also eine Bash-Sitzung im Browser, ohne SSH.
Dazu gibt es ein vorgefertigtes Lernverzeichnis mit Übungsaufgaben und Kurzreferenz zu den
wichtigsten Terminal-Befehlen.

## Zugang

- Adresse und Passwort stehen nach dem Deployment unter „Meine Zugänge“.
- Die Sitzung überlebt das Schließen des Tabs: Seite neu öffnen, und Hintergrundprozesse und
  Arbeitsverzeichnis sind noch da.
- `https://<adresse>/?arg=2` öffnet ein zweites, unabhängiges Terminal (zum Beispiel für Server
  und Client).
- Es gibt kein SSH, kein `sudo` und keinen root-Zugang.

## Vorinstallierte Software

- Python 3 (inkl. pip, venv)
- Node.js (inkl. npm)
- Git, curl, wget, tree, htop, nano, vim, openssl, net-tools
- Handbuchseiten (`man`, `info`), `ps`, `top`, `ip`, `ping`, `gawk`

Internetzugang ist erlaubt (für `curl`, `ping`, `pip` und `npm`).

## Lernverzeichnis

Beim ersten Start wird `~/linux-kurs/` im Home-Verzeichnis angelegt:

    ~/linux-kurs/
    ├── LIES_MICH.txt              ← Kurzreferenz aller wichtigen Befehle
    ├── beispieldaten/
    │   ├── studenten.csv          ← CSV für Übungen mit cut, grep, sort
    │   └── server.log             ← Logdatei für Übungen mit grep, tail, wc
    └── uebungen/
        ├── 01-navigation/
        ├── 02-dateien/
        ├── 03-berechtigungen/
        ├── 04-prozesse/
        └── 05-textverarbeitung/

Die Übungen 3 und 5 sind an die fehlenden Rechte angepasst.

## User-Management

- **Ein Pod pro Person.** Es gibt keine gemeinsame Umgebung; andere Personen haben keinen
  Zugriff auf deinen Pod.
- Der Benutzername ist der Plattform-Benutzername, das Passwort wird automatisch generiert.
- Dateien liegen im persistenten Speicher (2 GiB unter `/home/student`) und bleiben bei Pause
  und Fortsetzen erhalten.

## Deployment

Es wird **ein Pod pro Person** deployed, nicht mehr eine gemeinsame VM für alle Teams.

## Konfigurierbare Variablen

Keine. Alle Einstellungen stehen in der `appstore.yaml` der App.
