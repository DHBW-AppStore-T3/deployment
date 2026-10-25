# JupyterLab – Notebook-Umgebung

Eine eigene JupyterLab-Instanz für jede Person eines Deployments, mit eigenem Speicher und
eigenem Login. Die App läuft als Pods (App-Vertrag v2), nicht mehr als VMs: **ein
JupyterLab-Pod je Person** mit 5 GiB Speicher für Notebooks und Einstellungen, HTTPS-Link und
eigenem Passwort. JupyterHub wird nicht mehr benötigt.

## User-Management

Jede Person erhält ihren eigenen Pod und ein von der Plattform erzeugtes Passwort. Link und
Passwort stehen nach dem Deployment unter „Meine Zugänge“. Notebooks und Einstellungen liegen im
persistenten Home-Verzeichnis und überstehen Pause/Fortsetzen und Neustart.

- **Login:** auf der Login-Seite das generierte Passwort eintragen („Password or token“).
- **Software:** JupyterLab, NumPy, pandas und Matplotlib. Weitere Pakete lassen sich im Notebook
  mit `%pip install …` nachinstallieren (Internetzugang ist erlaubt, die Pakete landen im
  persistenten Home-Verzeichnis).
- **Kein `sudo`:** Systempakete (`apt`) können nicht installiert werden. Das Root-Dateisystem ist
  schreibgeschützt, schreibbar sind nur das Home-Verzeichnis und `/tmp`.

## Deployment

Es wird **ein Pod pro Person** deployed, nicht mehr eine gemeinsame VM für alle Nutzer und Teams.

## Konfigurierbare Variablen

Keine. Kein File-Upload, alle Einstellungen stehen in der `appstore.yaml` der App.
