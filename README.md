# Rezepte – gemeinsame Rezeptsammlung über OneDrive

Eine kleine lokale Web-App. Sie läuft auf eurem eigenen Rechner (`http://127.0.0.1:8642`)
und speichert alles in einem geteilten OneDrive-Ordner. Es gibt keinen Server und kein Hosting,
OneDrive übernimmt den Abgleich zwischen euch beiden.

## Funktionen

- **Import per URL**: Rezept-Adresse einfügen, dann werden Titel, Zutaten, Schritte, Zeit,
  Portionen und Bild übernommen. Das funktioniert bei allen Seiten, die Rezeptdaten im
  schema.org-Format einbetten (Chefkoch, Lecker, EatSmarter, BBC Good Food und die meisten Food-Blogs).
- **Bearbeiten**: alle Felder plus eigene Notizen und Tags
- **Bewerten**: jeder vergibt eigene Sterne, die Liste zeigt den Durchschnitt
- **Fotos**: werden vor dem Hochladen auf max. 1600 px verkleinert
- **Suche und Sortierung**: nach Titel, Zutat, Tag, Bewertung oder Datum
- **Gelöschtes** landet im Unterordner `_papierkorb` und nicht im Nirwana

## Voraussetzungen

- Windows mit OneDrive
- Python 3.9 oder neuer ([python.org](https://www.python.org/downloads/), bei der Installation
  „Add python.exe to PATH“ ankreuzen). Zusatzpakete sind nicht nötig.

## Einrichtung

### 1. Gemeinsamen Ordner anlegen (einer von euch)

1. Im OneDrive-Ordner einen Ordner `Rezepte` anlegen.
2. Rechtsklick → **Freigeben** → E-Mail-Adresse des Freundes eingeben, **„Kann bearbeiten“** auswählen.

### 2. Ordner einbinden (der andere)

1. Auf [onedrive.live.com](https://onedrive.live.com) unter **Geteilt** den Ordner `Rezepte` öffnen.
2. **„Verknüpfung zu ‚Meine Dateien‘ hinzufügen“** klicken.
3. Kurz warten, dann erscheint der Ordner im lokalen OneDrive-Ordner und wird synchronisiert.

### 3. App starten (beide)

1. Diesen App-Ordner (`rezepte`) auf euren Rechner kopieren, **nicht** in den geteilten Rezepte-Ordner.
2. Doppelklick auf **`Rezepte starten.bat`**. Der Browser öffnet sich automatisch.
3. Beim ersten Start wird `config.json` angelegt. Prüft dort, ob `datenordner` auf den geteilten
   Ordner zeigt (Standard: `%OneDrive%\Rezepte`). Falls nicht, Pfad anpassen und neu starten.
   Für die geteilte Verknüpfung heißt der Ordner manchmal anders, z. B. `Rezepte - Erik`.
4. Oben rechts auf 👤 klicken und euren Namen eintragen. Unter diesem Namen werden Bewertungen gespeichert.

Das Fenster mit der schwarzen Konsole muss offen bleiben, solange ihr die App benutzt.

### Optional: automatisch beim Hochfahren starten

So läuft die App unsichtbar im Hintergrund, ohne Konsolenfenster und ohne dass sich der Browser öffnet.
Ihr ruft sie dann einfach über `http://127.0.0.1:8642` auf (am besten als Lesezeichen).

1. **Win+R** → `shell:startup` → Enter
2. Rechtsklick → **Neu → Verknüpfung**, als Ziel (Pfad anpassen):
   ```
   pyw -3 "C:\Pfad\zu\rezepte\app.py" --no-browser
   ```
3. Name `Rezepte`, fertig.

- **Beenden**: Doppelklick auf `Rezepte beenden.bat`
- **Fehler** landen ohne Konsole in `rezepte.log` im App-Ordner
- **Autostart abschalten**: die Verknüpfung aus `shell:startup` löschen

## Datenformat

```
Rezepte/                    ← geteilter OneDrive-Ordner
  lasagne-bolognese-3f2a.json
  thai-curry-91bc.json
  fotos/
    lasagne-bolognese-3f2a-a81c0e.jpg
  _papierkorb/
```

Jedes Rezept ist eine lesbare JSON-Datei. Ihr kommt also auch ohne die App an eure Daten.

## Gleichzeitiges Bearbeiten

- **Bewertungen und Fotos** werden einzeln gespeichert und kommen sich nicht in die Quere.
- **Text bearbeiten**: Hat der andere dasselbe Rezept gespeichert, während du es bearbeitet hast,
  warnt die App und fragt, ob du überschreiben willst.
- **Konfliktkopien**: Wenn OneDrive selbst einen Konflikt nicht auflösen kann, legt es eine Kopie wie
  `rezept-DESKTOP-ABC.json` an. Die App zeigt das oben in der Liste an. Dann im Ordner die falsche Datei löschen.

## Sicherheit

- Die App ist nur vom eigenen Rechner aus erreichbar (`127.0.0.1`), nicht aus dem Netzwerk.
- Andere Webseiten im Browser können keine Änderungen auslösen.
- Inhalte aus Rezeptdateien werden nur als Text angezeigt, nie als HTML oder Code ausgeführt.
- Fotos werden auf echte JPG-, PNG- oder WebP-Dateien geprüft.
- OneDrive hat einen eigenen Papierkorb und eine Versionsgeschichte (Rechtsklick → Versionsverlauf).

## Testen ohne OneDrive

```bash
py app.py --ordner C:\Temp\rezepte-test
```
