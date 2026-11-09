# SRM-20 Gravur – HTTP-API

Mit dieser Schnittstelle können andere Programme die Gravur-App steuern: Schild berechnen,
Vorschau und G-Code abholen, Logo und Werkstück-Kontur hochladen und den Auftrag an die Fräse schicken.
Die Weboberfläche benutzt genau dieselben Endpunkte.

> ⚠️ **`POST /api/send` startet die Fräse sofort**, ohne Rückfrage. Es gibt keine Anmeldung und
> keinen Not-Aus über die API. Vorher immer mit `/api/preview` prüfen und mit Modus `air` oder `outline` testen.

---

## Grundlagen

| | |
|---|---|
| **Basis-URL** | `http://<PC-mit-Fräse>:5000` (lokal: `http://localhost:5000`) |
| **Format** | JSON. Anfragen mit Body brauchen `Content-Type: application/json`, sonst Antwort **415**. Ausnahme: Datei-Upload (multipart). |
| **Einheiten** | Längen in **mm**, Vorschub in **mm/min**, Drehzahl in **U/min**, Zeit in **Minuten** |
| **Koordinaten** | Nullpunkt (0/0) = linke untere Ecke des Werkstücks, X nach rechts, Y nach oben. Z = 0 auf der Oberseite, negativ = ins Material. |
| **Linien** | Eine Linie (*stroke*) ist eine Liste von Punkten `[[x, y], [x, y], …]`. Ein Bild ist eine Liste solcher Linien. |
| **Wahrheitswerte** | `true`/`false`, auch `1`/`0` oder `"true"`, `"false"`, `"ja"`, `"nein"`, `"on"`, `"off"`. |
| **Fehler** | Antwort `{"ok": false, "error": "Text auf Deutsch"}` mit Status 400 oder 500. |
| **Anmeldung** | keine. Jeder im Netz, der Port 5000 erreicht, kann die API benutzen. |

Alle Parameter sind optional. Fehlende oder ungültige Werte werden durch den Standardwert ersetzt.
Zahlen außerhalb des erlaubten Bereichs werden auf die Grenze gesetzt, es gibt dafür keine Fehlermeldung.

---

## Übersicht

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/info` | Schriften, Drucker, Vorlagen, geladenes Logo und geladene Kontur |
| POST | `/api/preview` | Schild berechnen: Linien, Warnungen, G-Code, Dauer |
| POST | `/api/send` | Schild berechnen **und an die Fräse senden** |
| POST | `/api/upload/logo` | Logo hochladen (SVG/DXF/DWG) |
| POST | `/api/upload/plate` | Werkstück-Kontur hochladen (SVG/DXF/DWG) |
| DELETE | `/api/upload/logo` · `/api/upload/plate` | Logo bzw. Kontur entfernen |
| POST | `/api/presets` | Werkstück-Vorlage speichern |
| DELETE | `/api/presets?name=…` | Werkstück-Vorlage löschen |
| GET | `/` | Weboberfläche (HTML) |

---

## Auftrags-Parameter

Diese Felder gelten für **`/api/preview`** und **`/api/send`** (bei `send` kommt noch `printer` dazu).

### Werkstück

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `plate_src` | Text | `"rect"` | `rect`, `file` | `rect` = Platte mit runden Ecken aus den Maßen unten. `file` = hochgeladene Kontur (siehe `/api/upload/plate`). Ist keine Kontur geladen, wird `rect` benutzt. |
| `plate_w` | Zahl | 70 | 5–1000 | Breite (X) |
| `plate_h` | Zahl | 50 | 5–1000 | Höhe (Y) |
| `plate_r` | Zahl | 3 | 0–500 | Eckradius |

### Text

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `text` | Text | `""` | max. 200 Zeichen | Gravurtext, Zeilenumbruch mit `\n` |
| `font` | Text | `"futural"` | Schlüssel aus `/api/info` → `fonts` | Schrift |
| `height` | Zahl | 10 | 0,5–100 | Höhe der Großbuchstaben |
| `text_bottom` | Zahl | 3 | ≥ 0 | Abstand vom unteren Werkstückrand bis zum tiefsten Punkt des Texts |
| `margin_side` | Zahl | 3 | ≥ 0 | Rand links und rechts (für die automatische Verkleinerung und das Logo) |
| `align` | Text | `"center"` | `left`, `center`, `right` | Ausrichtung mehrerer Zeilen zueinander. Der Textblock selbst steht immer mittig. |
| `autoshrink` | bool | `true` | | Zu breiten Text verkleinern, bis er zwischen die seitlichen Ränder passt |
| `smooth` | bool | `true` | | Rundungen der Schrift glätten, Ecken bleiben scharf |

### Logo

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `logo_on` | bool | `true` | | Logo gravieren (nur wenn eines hochgeladen ist) |
| `logo_gap` | Zahl | 3 | ≥ 0 | Abstand zwischen Textoberkante und Logo-Bereich |
| `margin_top` | Zahl | 3 | ≥ 0 | Rand oben |
| `logo_scale` | Zahl | 100 | 1–1000 | Größe in %. 100 = so groß, wie es in den freien Bereich passt. |
| `logo_dx` | Zahl | 0 | | Verschiebung in X (mm) |
| `logo_dy` | Zahl | 0 | | Verschiebung in Y (mm) |
| `logo_fill` | bool | `false` | | Geschlossene Flächen mit waagrechten Linien füllen |
| `fill_step` | Zahl | `line_w × 0,8` | 0,05–10 | Linienabstand beim Füllen |
| `logo_depth` | Zahl | = `depth` | 0,01–5 | Frästiefe des Logos |

Der Logo-Bereich reicht von `margin_side` bis Breite − `margin_side` und von Textoberkante + `logo_gap`
bis Höhe − `margin_top`. Das Logo wird mit gleichem Seitenverhältnis eingepasst und mittig gesetzt.

### Fräsen

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `mode` | Text | `"engrave"` | `engrave`, `air`, `outline` | `engrave` = gravieren. `air` = dieselbe Bahn 1 mm **über** der Oberfläche (Test). `outline` = nur den Werkstückumriss 1 mm über der Oberfläche abfahren (Nullpunkt prüfen). |
| `depth` | Zahl | 0,2 | 0,01–5 | Frästiefe Text |
| `passes` | Ganzzahl | 1 | 1–10 | Durchgänge. Die Tiefe wird gleichmäßig aufgeteilt. |
| `feed` | Zahl | 240 | 10–1800 | Vorschub (mm/min) |
| `plunge` | Zahl | 60 | 5–1800 | Eintauchgeschwindigkeit (mm/min) |
| `rpm` | Zahl | 7000 | 3000–7000 | Spindeldrehzahl |
| `safe_z` | Zahl | 2 | 0,5–30 | Sicherheitshöhe für Leerfahrten. Bei `air`/`outline` mindestens 3. |
| `wcs` | Text | `"G54"` | `G54`…`G59` | Koordinatensystem, in dem der Nullpunkt in VPanel gesetzt ist |
| `line_w` | Zahl | 0,3 | 0,05–5 | Linienbreite. Nur für die Vorschau und als Standard für `fill_step`. |

---

## GET `/api/info`

Liefert alles, was man zum Ausfüllen eines Auftrags braucht. Kann **einige Sekunden** dauern, weil Windows die Drucker auflistet.

```json
{
  "fonts":    {"futural": "Futura leicht (einfach, empfohlen)", "futuram": "Futura mittel (doppelte Linie)", "…": "…"},
  "printers": ["Roland SRM-20", "Adobe PDF"],
  "windows":  true,
  "presets":  [{"name": "Platte 70 × 50 mm", "w": 70, "h": 50, "r": 3, "builtin": true}],
  "assets":   {"logo": {"name": "logo.svg", "notes": []}, "plate": null}
}
```

| Feld | Bedeutung |
|---|---|
| `fonts` | Schlüssel → Anzeigename. Der Schlüssel kommt in `font`. |
| `printers` | Windows-Drucker. Einträge mit „SRM“ im Namen stehen vorne. Leer, wenn pywin32 fehlt. |
| `windows` | `false` = Senden nicht möglich (nur Vorschau und G-Code) |
| `presets` | Werkstück-Vorlagen. `builtin: true` = eingebaut, nicht löschbar. |
| `assets` | Geladenes Logo bzw. geladene Kontur (`null` = keine). `notes` = Hinweise vom Import. |

---

## POST `/api/preview`

Berechnet das Schild, sendet aber **nichts**. Body: Auftrags-Parameter (siehe oben).

```json
{
  "text":        [[[29.524, 13.0], [29.524, 3.0]], "…"],
  "logo":        [],
  "plate":       [[[67.0, 0.0], [67.392, 0.026], "…"]],
  "plate_size":  [70.0, 50.0],
  "logo_area":   [3.0, 16.0, 67.0, 47.0],
  "text_height": 10.0,
  "text_bbox":   [29.52, 3.0, 40.48, 13.48],
  "warnings":    [],
  "minutes":     0.55,
  "lines":       33,
  "gcode":       "%\nG17 G21 G90\nG40 G49 G80\nG54\n…"
}
```

| Feld | Bedeutung |
|---|---|
| `text`, `logo` | Gravierlinien in Werkstückkoordinaten (mm, auf 3 Stellen gerundet). Bei `logo_fill` sind die Füll-Linien in `logo` enthalten. |
| `plate` | Umriss des Werkstücks als Linien |
| `plate_size` | `[Breite, Höhe]` |
| `logo_area` | Freier Bereich fürs Logo `[x0, y0, x1, y1]`, oder `null` ohne Logo |
| `text_height` | Tatsächliche Schrifthöhe nach der automatischen Verkleinerung (`null` ohne Text) |
| `text_bbox` | Rahmen um den Text `[x0, y0, x1, y1]` (`null` ohne Text) |
| `warnings` | Hinweise auf Deutsch, z. B. Text verkleinert, zu nah am Rand, **außerhalb des Werkstücks**, Zeichen fehlt in der Schrift |
| `minutes` | Geschätzte Laufzeit |
| `lines` | Zeilen im G-Code |
| `gcode` | Vollständiges NC-Programm. Kann auch selbst gespeichert werden, z. B. als `.nc`. |

**Tipp:** Vor dem Senden `warnings` prüfen. Enthält eine Warnung „AUSSERHALB“, besser nicht senden.

---

## POST `/api/send`

Wie `/api/preview`, schickt den G-Code aber zusätzlich als RAW-Druckauftrag an die Fräse.

Zusätzliches Pflichtfeld:

| Feld | Typ | Bedeutung |
|---|---|---|
| `printer` | Text | Exakter Druckername aus `/api/info` → `printers` |

Antwort bei Erfolg:

```json
{"ok": true, "minutes": 2.68}
```

| Status | `error` | Ursache |
|---|---|---|
| 400 | `pywin32 fehlt oder kein Windows – senden nicht möglich.` | Server läuft nicht unter Windows oder ohne pywin32 |
| 400 | `Drucker nicht gefunden.` | `printer` fehlt oder ist falsch geschrieben |
| 400 | `Nichts zu gravieren.` | Kein Text und kein Logo (bei `mode: "outline"` ist das erlaubt) |
| 500 | Meldung des Druckspoolers | z. B. Fräse aus oder nicht verbunden |

Wichtig:
- `ok: true` heißt nur, dass der Auftrag beim Windows-Spooler angekommen ist. Ob die Fräse fertig ist, meldet die API **nicht**.
- Mehrere `send`-Aufrufe landen hintereinander in der Warteschlange und werden alle ausgeführt.
- Abbrechen geht nur in VPanel oder mit der VIEW-Taste an der Maschine.
- In VPanel muss der Befehlssatz **NC-Code** sein und der Nullpunkt im passenden Koordinatensystem (`wcs`) gesetzt.

---

## POST `/api/upload/logo` · `/api/upload/plate`

Lädt eine Datei hoch. Sie wird auf dem Server gespeichert (`data/logo.json` bzw. `data/plate.json`),
gilt **für alle Benutzer** und bleibt nach einem Neustart erhalten. Ein neuer Upload ersetzt den alten.

- Format: `multipart/form-data`, Feldname **`file`**, max. 25 MB
- Dateitypen: `.svg`, `.dxf`, `.dwg`. DWG geht nur, wenn der „ODA File Converter“ installiert ist.
- Die linke untere Ecke der Zeichnung wird auf 0/0 verschoben.
- `plate`: Es werden nur geschlossene Linien übernommen. Danach `plate_src: "file"` setzen, damit die Kontur benutzt wird.
- Texte in der Datei werden ausgelassen (vorher in Kurven umwandeln). Das steht dann in `notes`.

```json
{"ok": true, "name": "logo.svg", "size": [36.0, 10.0], "notes": ["Nicht übernommen: 1× Text (Texte vorher in Kurven umwandeln)"]}
```

`size` = Größe der Zeichnung in mm, so wie in der Datei. Das Logo wird später ohnehin eingepasst.
Bei der Kontur ist das die echte Werkstückgröße.

Fehler (400): unbekannter Typ, keine Datei, Dateityp nicht unterstützt, Datei nicht lesbar,
keine verwendbaren Linien, keine geschlossene Kontur (nur bei `plate`).

## DELETE `/api/upload/logo` · `/api/upload/plate`

Entfernt Logo bzw. Kontur. Antwort: `{"ok": true}`, auch wenn nichts geladen war.

---

## POST `/api/presets`

Speichert eine Werkstück-Vorlage. Gibt es den Namen schon, wird die Vorlage überschrieben.
Eingebaute Namen sind gesperrt.

```json
{"name": "Platte 100 × 60 mm", "w": 100, "h": 60, "r": 5}
```

Antwort: `{"ok": true, "presets": [ …alle Vorlagen… ]}`. Fehler (400): `Name fehlt.` / `Name ist schon vergeben.`

## DELETE `/api/presets?name=<Name>`

Löscht eine eigene Vorlage (Name URL-kodiert). Antwort: `{"ok": true, "presets": [ … ]}`.
Eingebaute Vorlagen bleiben erhalten.

> Vorlagen sind nur eine Merkhilfe. Für einen Auftrag zählen immer `plate_w`, `plate_h` und `plate_r`.

---

## Beispiele

### curl

```bash
# Vorschau
curl -s -X POST http://localhost:5000/api/preview \
     -H "Content-Type: application/json" \
     -d '{"text": "Max Muster", "height": 10, "depth": 0.2}'

# Logo hochladen
curl -s -F "file=@logo.svg" http://localhost:5000/api/upload/logo

# Erst Umriss in der Luft abfahren, dann gravieren
curl -s -X POST http://localhost:5000/api/send -H "Content-Type: application/json" \
     -d '{"text": "Max Muster", "mode": "outline", "printer": "Roland SRM-20"}'
```

Unter Windows-`cmd` die Anführungszeichen im JSON als `\"` schreiben oder das JSON aus einer Datei lesen (`-d @auftrag.json`).

### Python

```python
import requests

BASE = "http://localhost:5000"

info = requests.get(f"{BASE}/api/info", timeout=30).json()
printer = next(p for p in info["printers"] if "srm" in p.lower())

with open("logo.svg", "rb") as f:
    r = requests.post(f"{BASE}/api/upload/logo", files={"file": f}, timeout=60).json()
    assert r["ok"], r["error"]

job = {
    "text": "Max Muster",
    "plate_w": 70, "plate_h": 50, "plate_r": 3,
    "height": 10, "text_bottom": 3,
    "depth": 0.2, "logo_depth": 0.15,
    "feed": 240, "rpm": 7000,
    "wcs": "G54",
}

prev = requests.post(f"{BASE}/api/preview", json=job, timeout=60).json()
print(f"Dauer ca. {prev['minutes']:.1f} min", *prev["warnings"], sep="\n")
if any("AUSSERHALB" in w for w in prev["warnings"]):
    raise SystemExit("Gravur liegt außerhalb des Werkstücks")

# G-Code nur speichern ...
open("gravur.nc", "w").write(prev["gcode"])

# ... oder direkt an die Fräse
r = requests.post(f"{BASE}/api/send", json={**job, "mode": "engrave", "printer": printer}, timeout=60).json()
print("gesendet" if r["ok"] else r["error"])
```

---

## Hinweise für den Betrieb

- Der Server lauscht auf allen Netzwerkkarten (Port 5000). Wer die Fräse nicht für das ganze Netz
  freigeben will, sperrt den Port in der Windows-Firewall oder startet mit `host="127.0.0.1"` (am Ende von `app.py`).
- Logo, Kontur und Vorlagen liegen gemeinsam im Ordner `data/`. Mehrere Programme, die gleichzeitig
  verschiedene Logos hochladen, überschreiben sich gegenseitig.
- Einstellungen der Weboberfläche (Text, Tiefe usw.) speichert nur der Browser. Die API kennt sie nicht,
  jeder Aufruf muss seine Parameter selbst mitschicken.
