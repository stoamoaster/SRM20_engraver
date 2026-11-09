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

## Logo-Dateien
- **SVG** (z. B. aus Inkscape/Illustrator) oder **DXF** (aus jedem CAD-Programm).
- **DWG** geht nur mit dem kostenlosen „ODA File Converter“. Einfacher: im CAD als DXF speichern.
- Texte in der Datei vorher in Kurven/Pfade umwandeln, sonst fehlen sie.
- Graviert werden die Umrisslinien. „Flächen mit Linien füllen“ schraffiert geschlossene
  Flächen (dauert deutlich länger).
- Logo, Kontur und eigene Vorlagen liegen im Ordner `data/` und bleiben beim Neustart erhalten.

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
- Umlaute werden aus Grundbuchstabe + Punkten gebaut, ß wird zu „ss“.
- Zeichen, die die Schrift nicht kennt (z. B. €), werden ausgelassen und angezeigt.
- Andere Geräte im WLAN können über http://<IP-des-PCs>:5000 gravieren
  (Windows-Firewall fragt beim ersten Start).
