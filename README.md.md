# SRM-20 Gravur

Text eingeben, Vorschau ansehen, direkt an die Roland SRM-20 senden.

## Einrichten (einmalig)
1. Python 3 installieren (python.org, beim Setup „Add Python to PATH“ anhaken).
2. In **VPanel** → Setup: Befehlssatz auf **NC-Code** stellen.
   Achtung: G-Code im RML-1-Modus lässt die Maschine hängen.
3. Ordner irgendwohin kopieren, `start.bat` doppelklicken.
   Installiert die Pakete und öffnet http://localhost:5000

## Pro Gravur
1. Werkstück einspannen, in VPanel X/Y-Nullpunkt und **Z-Nullpunkt auf der Oberfläche** setzen.
2. Text eingeben, Höhe und Tiefe wählen, Vorschau prüfen.
3. Beim ersten Mal **Luftschnitt** anhaken (fährt 1 mm über dem Material) und senden.
4. Passt alles: Luftschnitt aus, senden.

Abbrechen: in VPanel oder mit der VIEW-Taste an der Maschine.

## Hinweise
- „Nullpunkt ist: Textmitte“ ist praktisch, wenn du die Mitte des Werkstücks als Nullpunkt setzt.
- Startwerte für Gravierstichel / V-Fräser in Kunststoff oder Holz: 0,1–0,3 mm Tiefe, 200–400 mm/min.
  In Alu flacher und mit mehreren Durchgängen.
- Umlaute werden aus Grundbuchstabe + Punkten gebaut, ß wird zu „ss“.
- Zeichen, die die Schrift nicht kennt (z. B. €), werden ausgelassen und angezeigt.
- Andere Geräte im WLAN können über http://<IP-des-PCs>:5000 gravieren
  (Windows-Firewall fragt beim ersten Start).
