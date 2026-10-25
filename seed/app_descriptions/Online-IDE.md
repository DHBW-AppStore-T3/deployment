# Online-IDE – VS Code im Browser

Eine eigene Entwicklungsumgebung (code-server, VS Code im Browser) für jede Person eines
Deployments, mit eigenem Speicher und eigenem Login. Die App läuft als Pods (App-Vertrag v2),
nicht mehr als VMs: **ein code-server-Pod je Person** mit 5 GiB Speicher im Home-Verzeichnis,
HTTPS-Link und eigenem Passwort.

## User-Management

Jede Person erhält ihren eigenen Pod und ein von der Plattform erzeugtes Passwort. Link und
Passwort stehen nach dem Deployment unter „Meine Zugänge“. Dateien liegen im persistenten
Home-Verzeichnis (`/home/coder`) und überstehen Pause/Fortsetzen und Neustart.

Weil die App pro Person läuft, bekommt im Wizard jede Person ein eigenes Team. Gruppen mit
gemeinsamer Umgebung gibt es nicht.

## Deployment

Es wird **ein Pod pro Person** deployed, nicht mehr eine VM pro Team. Jede Person arbeitet in
einer eigenen Umgebung ohne Zugriff auf die Umgebungen anderer.

## Software im Terminal

| Werkzeug | Hinweis |
|---|---|
| `gcc`, `g++`, `make` | `build-essential` |
| `python3`, `pip`, `python3 -m venv` | Pro Projekt `python3 -m venv .venv` benutzen; ohne venv installiert `pip` nach `~/.local` |
| `node`, `npm` | `npm install -g` landet in `~/.npm-global` |
| `git`, `curl`, `wget`, `unzip` | |

Das Root-Dateisystem ist schreibgeschützt, schreibbar sind nur das Home-Verzeichnis und `/tmp`.
`sudo` und `apt` gibt es nicht. Internetzugang ist erlaubt (PyPI, npm). Java ist **nicht**
enthalten; dafür gibt es die Java-IDE.

## Konfigurierbare Variablen

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `assignments` | Aufgaben als ZIP-Datei pro Team (also pro Person), höchstens 1 MiB | Nein |

### Aufgaben (`assignments`)

Die ZIP-Datei wird beim ersten Start des Arbeitsplatzes nach `~/Coding-Aufgabe` entpackt und ist
direkt in code-server sichtbar. Ohne ZIP startet der Arbeitsplatz leer. Das Archiv wird vor dem
Entpacken geprüft; ein unzulässiger Eintrag (zum Beispiel ein Pfad mit `..` oder ein symbolischer
Link) verwirft das ganze Archiv, die IDE startet dann mit leerem Arbeitsplatz.
