# Web-LaTeX Editor

Ein browserbasierter LaTeX-Editor mit vollständiger LaTeX-Umgebung, Syntax-Highlighting und
Live-PDF-Preview. Die App läuft als Pods (App-Vertrag v2), nicht mehr als VMs: **ein
Editor-Pod je Person** mit eigenem Speicher (2 GiB), HTTPS-Link und eigenem Passwort.

## User-Management

Jede Person erhält ihren eigenen Pod und damit einen isolierten Workspace mit eigenem
Projektverzeichnis. Projekte und Einstellungen liegen im persistenten Home-Verzeichnis und
überstehen Pause/Fortsetzen und Neustart.

Link, Benutzername und Passwort stehen nach dem Deployment unter „Meine Zugänge“. Der
Benutzername ist der Plattform-Benutzername, das Passwort wird automatisch generiert.

## Deployment

Es wird **ein Pod pro Person** deployed, nicht mehr eine VM pro Team. Mitglieder desselben
Teams arbeiten in getrennten Pods und teilen sich nur das Startprojekt (siehe unten).

## Konfigurierbare Variablen

| Variable | Beschreibung | Pflicht |
|---|---|---|
| `starter` | ZIP-Datei pro Team mit dem Startprojekt (LaTeX-Dateien), `master.tex` im Root, max. 1 MiB | Nein |

### Startprojekt (`starter`)

Pro Team kann eine ZIP-Datei hochgeladen werden. Sie muss mindestens eine `master.tex` im
Root enthalten und darf höchstens 1 MiB groß sein. Beim ersten Öffnen des Editors wird die ZIP
im persönlichen Workspace jeder Person des Teams entpackt. Ohne ZIP startet der Editor mit dem
mitgelieferten Demo-Projekt.

## Features

- Live-PDF-Preview nach dem Kompilieren
- Datei-Explorer mit Unterstützung für mehrere `.tex`-Dateien und Unterverzeichnisse
- Neue `.tex`-Dateien direkt im Browser anlegen
- Bilder (PNG, JPG, JPEG, GIF) hochladen und per `\includegraphics{}` einbinden
- Auto-Save (500ms Debounce)
- Kompilierung via `pdflatex` (zweifacher Lauf für TOC/Referenzen)
