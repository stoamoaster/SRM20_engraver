# SRM-20 Gravur

Schild mit Text und Logo gestalten, Vorschau ansehen, direkt an die Roland SRM-20 senden.

## Einrichten (einmalig)
1. Python 3 installieren (python.org, beim Setup „Add Python to PATH“ anhaken).
2. In **VPanel** → Setup: Befehlssatz auf **NC-Code** stellen.
   Achtung: G-Code im RML-1-Modus lässt die Maschine hängen.
3. Ordner irgendwohin kopieren, `start.bat` doppelklicken.
   Beim ersten Start wird eine virtuelle Umgebung (`.venv`) im Ordner angelegt und die
   Pakete werden dort installiert, nicht global. Danach öffnet sich http://localhost:5000
   Pakete werden nur neu installiert, wenn sich `requirements.txt` ändert.
   Bei Problemen einfach den Ordner `.venv` löschen, beim nächsten Start wird er neu erstellt.

## Aufbau des Schilds
Standard: Platte **70 × 50 mm** quer, mit runden Ecken.

- **Nullpunkt** X/Y = linke untere Ecke der Platte, Z = Oberseite.
  (Bei runden Ecken ist das die gedachte Ecke, an der sich die beiden Kanten treffen würden.)
- **Text**: 10 mm hoch (Höhe der Großbuchstaben), waagrecht mittig, 3 mm von der Unterkante.
  Ist der Text zu breit für die Platte, wird er automatisch verkleinert (abschaltbar).
- **Logo**: wird automatisch in den freien Platz über dem Text eingepasst
  (gestrichelter Rahmen in der Vorschau). Größe und Versatz lassen sich nachjustieren.

## Werkstück ändern
- Breite, Höhe und Eckradius direkt eintragen. Mit „Als Vorlage speichern“ kann man sich
  z. B. eine größere Platte merken.
- Oder **Form → Kontur aus Datei**: einen geschlossenen Umriss als DXF/DWG/SVG laden
  (z. B. eine Platte mit besonderer Form). Die linke untere Ecke des Umrisses wird zum Nullpunkt.
- Die Vorschau warnt, wenn Text oder Logo zu nah am Rand oder außerhalb liegen.
- **Spannbereiche** (rot in der Vorschau): links und rechts je ein Kreis (Standard Ø 30 mm, ragt 7 mm
  ins Werkstück, auf halber Höhe). Die Fräse fährt dort nie durch; Leerfahrten werden über dem
  Werkstück darum herumgeführt. Der fertige G-Code wird zusätzlich kontrolliert. Liegt etwas im
  roten Bereich, wird nicht gesendet. Jedes Programm fährt zu Beginn immer zuerst in die VIEW-Position
  (erst Z hoch, dann X/Y) und von dort in VIEW-Höhe über den Startpunkt – erst dann wird abgesenkt.

## Logo-Dateien
- **SVG** (z. B. aus Inkscape/Illustrator) oder **DXF** (aus jedem CAD-Programm).
- **DWG** geht nur mit dem kostenlosen „ODA File Converter“. Einfacher: im CAD als DXF speichern.
- Texte in der Datei vorher in Kurven/Pfade umwandeln, sonst fehlen sie.
- Graviert werden die Umrisslinien. „Flächen mit Linien füllen“ schraffiert geschlossene
  Flächen (dauert deutlich länger).
- Logo, Kontur und eigene Vorlagen liegen im Ordner `data/` und bleiben beim Neustart erhalten.
- **Standard-Logos**: Alle Dateien im Ordner `logos/` stehen unter „Standard-Logo“ zur Auswahl.
  Einfach hineinkopieren oder „Datei zu den Standard-Logos hinzufügen…“ benutzen.
  Der Ordner gehört zum Git-Repository, die Logos sind also nach einem Commit überall verfügbar.
- **Plattenvorlagen**: eingebaut in `store.py` (`DEFAULT_PRESETS`), eigene in `data/presets.json`.

## Pro Gravur
1. Werkstück einspannen. In VPanel oben als Koordinatensystem **G54** wählen
   (nicht „Maschinenkoordinatensystem“), dann X/Y-Nullpunkt auf die **linke untere Ecke** und
   **Z-Nullpunkt auf die Oberseite** setzen. Der G-Code wählt G54 ausdrücklich aus
   (umstellbar unter „Koordinatensystem“, falls du G55–G59 benutzt).
2. Text eingeben, Logo prüfen, Vorschau ansehen.
3. Zum Prüfen: Modus **„Werkstück-Umriss abfahren“** fährt 1 mm über der Platte deren Umriss ab.
   Damit sieht man, ob der Nullpunkt passt.
4. Modus **Luftschnitt** fährt die ganze Gravur 1 mm über dem Material ab.
5. Passt alles: Modus **Gravieren**, senden.

Abbrechen: in VPanel oder mit der VIEW-Taste an der Maschine.

## Hinweise
- Startwerte für Gravierstichel / V-Fräser in Kunststoff oder Holz: 0,1–0,3 mm Tiefe, 200–400 mm/min.
  In Alu flacher und mit mehreren Durchgängen. Text und Logo können verschiedene Tiefen haben.
- **Schriften:** Standard ist *Relief SingleLine*, eine fein gezeichnete Single-Line-Schrift mit
  echten Kurven und Kerning. Dazu kommen vier EMS-Schriften (alle frei, siehe `fonts/LIZENZEN.md`).
  Die alten Hershey-Schriften sind auf einem groben Raster gezeichnet (bei 10 mm Höhe ca. 0,5 mm).
  Bei ihnen macht „Rundungen glätten“ die Kurven runder.
- **Zeichenabstände „optisch“** (Standard): Das Programm misst die Form jedes Buchstabens
  und setzt die Abstände so, dass alle Lücken gleich groß wirken (z. B. „ko“ wie „Ja“).
  „Laufweite %“ regelt, wie eng der Text läuft. Mit „aus Schrift“ gelten wieder die Abstände
  und das Kerning der Schrift.
- „Schriftbreite %“ streckt die Buchstaben waagrecht, z. B. für ein breiteres T.
  „Zeichenabstand“ zieht den Text zusätzlich auseinander.
- Am Ende fährt die Fräse in die **VIEW-Position**: erst Z hoch, dann X/Y. Standard ist
  X 33,7 / Y 121,8 / Z 57,5 im G54-System. Alle drei Achsen sind unter „Fräsparameter“ einstellbar,
  der Schalter lässt sich auch abschalten. Die Werte beziehen sich auf den Werkstück-Nullpunkt.
- Umlaute werden aus Grundbuchstabe + Punkten gebaut, ß wird zu „ss“.
- Zeichen, die die Schrift nicht kennt (z. B. €), werden ausgelassen und angezeigt.
- Andere Geräte im WLAN können über http://<IP-des-PCs>:5000 gravieren
  (Windows-Firewall fragt beim ersten Start).

## Steuerung durch andere Programme
Die App lässt sich vollständig über eine HTTP-API (JSON) steuern, vom Schicken der Parameter bis
zum Start des Fräsvorgangs. Ein Aufruf genügt:

```bash
curl -X POST http://localhost:5000/api/v1/jobs -d "{\"text\": \"Max Muster\", \"start\": true}"
```

Beschreibung aller Endpunkte und Parameter: [API.md](API.md)

Zum Entwickeln ohne Fräse: vor dem Start `set SRM20_SIMULATE=1` setzen. Dann wird nichts gesendet,
der G-Code landet in `data/simulated/`.

## Aufbau des Programms
| Datei | Aufgabe |
|---|---|
| `app.py` | Webserver: Weboberfläche und API |
| `engraving.py` | Rechenkern: Text setzen, Geometrie, Schild aufbauen, G-Code |
| `params.py` | Tabelle aller Auftrags-Parameter mit Standardwerten, Grenzen und Prüfung |
| `jobs.py` | Aufträge: berechnen, starten, Zustand verfolgen, abbrechen |
| `machine.py` | Verbindung zur Fräse über den Windows-Drucker, Simulationsmodus |
| `store.py` | Gespeichertes Logo, Kontur und Vorlagen im Ordner `data/` |
| `importer.py`, `svgfont.py` | Einlesen von SVG/DXF/DWG und der SVG-Schriften |
