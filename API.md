# SRM-20 Gravur – HTTP-API (v1)

Mit dieser Schnittstelle steuert ein anderes Programm die Gravur-App vollständig über JSON:
Parameter schicken, Schild berechnen lassen, Fräsvorgang starten, Zustand abfragen, abbrechen.

> ⚠️ **`"start": true` bzw. `POST /api/v1/jobs/<id>/start` startet die Fräse sofort**, ohne Rückfrage.
> Einen Not-Aus gibt es über die API nicht. Erst mit `mode: "outline"` oder `"air"` testen.

---

## Kurzfassung

Ein einziger Aufruf genügt:

```bash
curl -X POST http://localhost:5000/api/v1/jobs -d "{\"text\": \"Max Muster\", \"depth\": 0.2, \"start\": true}"
```

Oder in zwei Schritten, erst berechnen und prüfen, dann starten:

```
POST /api/v1/jobs              {"text": "Max Muster"}      ->  job.id, job.warnings, job.minutes
POST /api/v1/jobs/<id>/start                               ->  Fräse läuft
GET  /api/v1/jobs/<id>                                     ->  job.state: queued | running | done …
```

---

## Grundlagen

| | |
|---|---|
| **Basis-URL** | `http://<PC-mit-Fräse>:5000/api/v1` (lokal: `http://localhost:5000/api/v1`) |
| **Format** | JSON rein, JSON raus. Der `Content-Type` der Anfrage ist egal, der Body wird immer als JSON gelesen. |
| **Einheiten** | Längen in **mm**, Vorschub in **mm/min**, Drehzahl in **U/min**, Zeit in **Minuten** |
| **Koordinaten** | Nullpunkt (0/0) = linke untere Ecke des Werkstücks, X nach rechts, Y nach oben. Z = 0 auf der Oberseite, negativ = ins Material. |
| **Linien** | Eine Linie (*stroke*) ist eine Liste von Punkten `[[x, y], [x, y], …]`. Ein Bild ist eine Liste solcher Linien. |
| **Wahrheitswerte** | `true`/`false`, auch `1`/`0` oder `"true"`, `"false"`, `"ja"`, `"nein"`, `"on"`, `"off"` |
| **Zeitstempel** | ISO 8601 mit Zeitzone, z. B. `2026-11-10T13:53:46+01:00` |

### Antworten

Erfolg: immer `"ok": true` plus die Daten.

```json
{"ok": true, "job": { … }}
```

Fehler: `"ok": false` und ein `error`-Objekt. `code` ist stabil und für Programme gedacht,
`message` ist ein deutscher Text für Menschen.

```json
{
  "ok": false,
  "error": {
    "code": "invalid_parameters",
    "message": "Ungültige Parameter – nichts berechnet, nichts gesendet.",
    "details": [
      {"field": "depth", "message": "muss höchstens 5 sein (ist 9)"},
      {"field": "hight", "message": "unbekanntes Feld – meintest du „height“?"}
    ]
  }
}
```

| Status | `code` | Bedeutung |
|---|---|---|
| 400 | `invalid_json` | Body fehlt oder ist kein JSON-Objekt |
| 401 | `unauthorized` | API-Schlüssel fehlt oder ist falsch |
| 404 | `not_found`, `job_not_found` | Endpunkt oder Auftrag gibt es nicht |
| 409 | `blocked_by_warning` | Gravur liegt außerhalb des Werkstücks oder Werkstück zu groß. Mit `"force": true` trotzdem starten. |
| 409 | `machine_busy` | Ein anderer Auftrag läuft noch. Mit `"queue": true` dahinter einreihen. |
| 409 | `already_started`, `already_finished` | Auftrag wurde schon gestartet bzw. ist schon abgeschlossen |
| 422 | `invalid_parameters` | Feld falsch, außerhalb der Grenzen oder unbekannt. Alle Fehler stehen in `details`. |
| 422 | `nothing_to_engrave` | Kein Text und kein Logo |
| 422 | `invalid_asset` | Logo oder Kontur nicht lesbar |
| 502 | `send_failed` | Windows-Spooler hat den Auftrag abgelehnt |
| 503 | `machine_unavailable`, `printer_not_found` | Senden nicht möglich bzw. Drucker nicht gefunden |

**Strenge Prüfung:** Anders als die Weboberfläche korrigiert die API v1 nichts stillschweigend.
Ein Wert außerhalb der Grenzen, ein falscher Typ oder ein unbekanntes Feld (Tippfehler) führt zu
`invalid_parameters`, und es wird nichts berechnet und nichts gesendet. Fehlende Felder bekommen den Standardwert.

---

## Übersicht

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/v1` | Name, Version, Liste der Endpunkte |
| GET | `/api/v1/status` | Fräse erreichbar? Drucker, laufende Aufträge, gespeichertes Logo/Kontur |
| GET | `/api/v1/parameters` | Alle Auftrags-Parameter mit Typ, Standardwert und Grenzen, dazu die Schriften |
| POST | `/api/v1/jobs` | Auftrag berechnen, mit `"start": true` **sofort fräsen** |
| GET | `/api/v1/jobs` | Liste der Aufträge, neueste zuerst |
| GET | `/api/v1/jobs/<id>` | Zustand eines Auftrags |
| POST | `/api/v1/jobs/<id>/start` | Berechneten Auftrag **fräsen** |
| POST | `/api/v1/jobs/<id>/cancel` | Auftrag abbrechen (gleichwertig: `DELETE /api/v1/jobs/<id>`) |
| GET | `/api/v1/jobs/<id>/gcode` | G-Code als reiner Text |
| GET · PUT · DELETE | `/api/v1/assets/logo` · `/api/v1/assets/plate` | Logo bzw. Werkstück-Kontur dauerhaft speichern |

---

## POST `/api/v1/jobs` – Auftrag anlegen

Body: die [Auftrags-Parameter](#auftrags-parameter) und dazu diese Steuerfelder. Alles ist optional.

| Feld | Typ | Standard | Bedeutung |
|---|---|---|---|
| `start` | bool | `false` | `true` = nach dem Berechnen sofort an die Fräse senden |
| `force` | bool | `false` | Auch starten, wenn eine sperrende Warnung vorliegt (`outside`, `plate_too_large`) |
| `queue` | bool | `false` | Auch starten, wenn noch ein anderer Auftrag läuft. Der neue wird dahinter eingereiht. |
| `printer` | Text | automatisch | Druckername der Fräse. Ohne Angabe: `SRM20_PRINTER`, sonst der erste Drucker mit „SRM“ im Namen. |
| `logo` | Objekt | gespeichertes Logo | Logo nur für diesen Auftrag, siehe [Logo und Kontur](#logo-und-kontur-als-json) |
| `plate_contour` | Objekt | – | Werkstück-Umriss nur für diesen Auftrag. Ersetzt `plate_w`/`plate_h`/`plate_r`. |
| `include` | Liste | `[]` | Zusätzlich in die Antwort aufnehmen: `"params"`, `"gcode"`, `"geometry"` |

Beispiel:

```json
{
  "text": "Max Muster",
  "plate_w": 70, "plate_h": 50, "plate_r": 3,
  "height": 10, "depth": 0.2,
  "feed": 240, "rpm": 7000,
  "mode": "engrave",
  "start": true
}
```

Antwort **201** mit dem Auftrag:

```json
{
  "ok": true,
  "job": {
    "id": "942304c28c75",
    "state": "queued",
    "message": null,
    "mode": "engrave",
    "created": "2026-11-10T13:53:46+01:00",
    "started": "2026-11-10T13:53:46+01:00",
    "finished": null,
    "printer": "Roland SRM-20",
    "simulated": false,
    "minutes": 1.84,
    "gcode_lines": 262,
    "warnings": [
      {"code": "text_shrunk", "message": "Text zu breit – Schrifthöhe automatisch auf 8.3 mm verkleinert."}
    ],
    "can_start": false,
    "needs_force": false,
    "plate_size": [70, 50],
    "text_height": 8.256,
    "text_bbox": [3.033, 3.0, 66.967, 11.195],
    "logo_area": null,
    "links": {
      "self": "/api/v1/jobs/942304c28c75",
      "start": "/api/v1/jobs/942304c28c75/start",
      "cancel": "/api/v1/jobs/942304c28c75/cancel",
      "gcode": "/api/v1/jobs/942304c28c75/gcode"
    }
  }
}
```

| Feld | Bedeutung |
|---|---|
| `id` | Kennung des Auftrags für alle weiteren Aufrufe |
| `state` | Zustand, siehe [Zustände](#zustände) |
| `message` | Hinweis zum Zustand, z. B. „Fräse offline oder nicht verbunden“ (`null` = nichts) |
| `minutes` | Geschätzte Laufzeit |
| `gcode_lines` | Zeilen im G-Code |
| `warnings` | Hinweise mit stabilem `code` und deutschem Text, siehe [Warnungen](#warnungen) |
| `can_start` | `true` = der Auftrag ist berechnet und kann gestartet werden |
| `needs_force` | `true` = Start nur mit `"force": true` |
| `plate_size` | `[Breite, Höhe]` des Werkstücks |
| `text_height` | Tatsächliche Schrifthöhe nach der automatischen Verkleinerung (`null` ohne Text) |
| `text_bbox` | Rahmen um den Text `[x0, y0, x1, y1]` (`null` ohne Text) |
| `logo_area` | Freier Bereich fürs Logo `[x0, y0, x1, y1]` (`null` ohne Logo) |
| `simulated` | `true` = der Server läuft im Simulationsmodus, es wurde nichts gesendet |
| `params` | nur mit `include`: alle Parameter, wie sie tatsächlich verwendet wurden |
| `gcode` | nur mit `include`: vollständiges NC-Programm |
| `geometry` | nur mit `include`: `{"text": […], "logo": […], "plate": […]}` als Linien für eine eigene Vorschau |

Schlägt bei `"start": true` nur der Start fehl (z. B. `machine_busy`), ist der Auftrag trotzdem
berechnet. Er steht dann in `error.job` und lässt sich später mit `/start` starten.

### Warnungen

| `code` | Bedeutung | sperrt den Start |
|---|---|---|
| `outside` | Teile der Gravur liegen außerhalb des Werkstücks | **ja** (außer bei `mode: "outline"`) |
| `plate_too_large` | Werkstück größer als der Arbeitsbereich (203,2 × 152,4 mm) | **ja** |
| `near_edge` | Gravur näher als 0,5 mm am Rand | nein |
| `text_shrunk` | Schrifthöhe wurde automatisch verkleinert | nein |
| `missing_chars` | Zeichen fehlen in der Schrift und werden ausgelassen | nein |
| `logo_no_space` | Kein Platz für das Logo | nein |
| `logo_no_fill` | Logo hat keine geschlossenen Flächen, Füllen nicht möglich | nein |

### Zustände

| `state` | Bedeutung |
|---|---|
| `prepared` | Berechnet, noch nicht gestartet |
| `queued` | In der Windows-Warteschlange, wartet |
| `running` | Wird an die Fräse übertragen, die Fräse arbeitet |
| `error` | Hängt in der Warteschlange, z. B. Fräse aus. Läuft weiter, sobald das Problem behoben ist. Grund steht in `message`. |
| `done` | Vollständig an die Fräse übertragen |
| `failed` | Konnte nicht gesendet werden, Grund in `message` |
| `cancelled` | Abgebrochen |

Wichtig:
- Der Zustand kommt aus der Windows-Druckwarteschlange. `done` heißt: Der Auftrag ist dort verschwunden,
  die Fräse hat also alle Daten erhalten. Die Maschine selbst meldet nichts zurück. Wie genau `done`
  mit dem Ende der Fräsbewegung zusammenfällt, ist noch nicht an der echten Maschine gemessen.
- `queued`, `running` und `error` belegen die Fräse. Solange gibt ein weiterer Start `machine_busy`.
- Die Aufträge liegen nur im Arbeitsspeicher (die letzten 100) und sind nach einem Neustart des Servers weg.

---

## POST `/api/v1/jobs/<id>/start` – Fräsen

Startet einen berechneten Auftrag (`state: "prepared"`). Body optional:

```json
{"force": false, "queue": false, "printer": "Roland SRM-20"}
```

Antwort: `{"ok": true, "job": { … }}` mit dem neuen Zustand. Jeder Auftrag lässt sich nur einmal starten.
Für eine Wiederholung einen neuen Auftrag anlegen.

## GET `/api/v1/jobs/<id>` – Zustand abfragen

Antwort wie oben. Mit `?include=gcode,geometry,params` kommen die großen Felder dazu.
Zum Warten auf das Ende alle paar Sekunden abfragen, bis `state` `done`, `failed` oder `cancelled` ist.

## POST `/api/v1/jobs/<id>/cancel` – Abbrechen

```json
{"ok": true, "removed_from_queue": true, "job": {"state": "cancelled", "…": "…"}}
```

- Ein Auftrag im Zustand `prepared` wird einfach verworfen.
- Ein wartender Auftrag wird aus der Windows-Warteschlange genommen (`removed_from_queue: true`).
- **Was die Fräse schon erhalten hat, fräst sie weiter.** Dann ist `removed_from_queue` `false`
  und `job.message` sagt es. Anhalten geht nur in VPanel oder mit der VIEW-Taste an der Maschine.

## GET `/api/v1/jobs/<id>/gcode`

Das NC-Programm als `text/plain`, z. B. zum Speichern als `.nc`.

---

## GET `/api/v1/status`

```json
{
  "ok": true,
  "version": "1.0",
  "machine": {
    "can_send": true,
    "simulate": false,
    "printer": "Roland SRM-20",
    "printers": ["Roland SRM-20", "Adobe PDF"],
    "busy": false,
    "active_jobs": []
  },
  "assets": {
    "logo": {"name": "logo.svg", "notes": [], "size": [36.0, 10.0]},
    "plate": null
  }
}
```

| Feld | Bedeutung |
|---|---|
| `can_send` | `false` = Senden nicht möglich (kein Windows oder pywin32 fehlt). Berechnen geht trotzdem. |
| `simulate` | `true` = Simulationsmodus, siehe [Betrieb](#betrieb) |
| `printer` | Drucker, der ohne Angabe von `printer` benutzt wird. `null` = keiner gefunden. |
| `printers` | Alle Windows-Drucker. Einträge mit „SRM“ im Namen stehen vorne. |
| `busy`, `active_jobs` | Läuft gerade ein Auftrag dieser App? Aufträge anderer Programme (z. B. VPanel) sieht die App nicht. |
| `assets` | Gespeichertes Logo bzw. gespeicherte Kontur (`null` = keine) |

Der erste Aufruf kann einige Sekunden dauern, weil Windows die Drucker auflistet. Danach gilt die Liste 10 Sekunden.

## GET `/api/v1/parameters`

Liefert die Parameter-Tabelle maschinenlesbar, z. B. um Eingabefelder zu bauen oder vorab zu prüfen.

```json
{
  "ok": true,
  "parameters": [
    {"name": "depth", "type": "number", "default": 0.2, "group": "milling",
     "description": "Frästiefe Text", "min": 0.01, "max": 5, "unit": "mm"},
    {"name": "mode", "type": "choice", "default": "engrave", "group": "milling",
     "description": "…", "choices": ["engrave", "air", "outline"]}
  ],
  "fonts": {"relief": "Relief SingleLine (empfohlen)", "…": "…"},
  "presets": [{"name": "Platte 70 × 50 mm", "w": 70, "h": 50, "r": 3, "builtin": true}],
  "work_area": {"x": 203.2, "y": 152.4}
}
```

`type` ist `number`, `integer`, `boolean`, `string` oder `choice`. `default: null` heißt: Der Wert
richtet sich nach einem anderen Feld (`logo_depth`, `fill_step`).

---

## Auftrags-Parameter

### Werkstück

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `plate_src` | Text | `"rect"` | `rect`, `file` | `rect` = Platte mit runden Ecken aus den Maßen unten. `file` = gespeicherte Kontur (`PUT /api/v1/assets/plate`). Mit `plate_contour` im Auftrag ist das Feld unnötig. |
| `plate_w` | Zahl | 70 | 5–1000 | Breite (X) |
| `plate_h` | Zahl | 50 | 5–1000 | Höhe (Y) |
| `plate_r` | Zahl | 3 | 0–500 | Eckradius |

### Text

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `text` | Text | `""` | max. 200 Zeichen | Gravurtext, Zeilenumbruch mit `\n` |
| `font` | Text | `"relief"` | Schlüssel aus `/api/v1/parameters` → `fonts` | Schrift (siehe unten) |
| `height` | Zahl | 10 | 0,5–100 | Höhe der Großbuchstaben |
| `spacing_mode` | Text | `"optical"` | `optical`, `font` | `optical` = Abstände nach der Form der Buchstaben gleichmäßig ausgleichen (siehe unten). `font` = Abstände und Kerning wie in der Schrift festgelegt. |
| `tracking` | Zahl | 35 | 0–150 | Laufweite bei `optical`: Ziel-Lücke zwischen zwei Buchstaben in % der Schrifthöhe. 35 ergibt etwa die gleiche Textbreite wie `font`. |
| `width_pct` | Zahl | 100 | 50–200 | Schriftbreite in %. Streckt die Buchstaben waagrecht. |
| `letter_spacing` | Zahl | 0 | −3–10 | Zusätzlicher Abstand zwischen den Buchstaben in mm (in beiden Modi) |
| `text_bottom` | Zahl | 3 | ≥ 0 | Abstand vom unteren Werkstückrand bis zum tiefsten Punkt des Texts |
| `margin_side` | Zahl | 3 | ≥ 0 | Rand links und rechts (für die automatische Verkleinerung und das Logo) |
| `align` | Text | `"center"` | `left`, `center`, `right` | Ausrichtung mehrerer Zeilen zueinander. Der Textblock selbst steht immer mittig. |
| `autoshrink` | bool | `true` | | Zu breiten Text verkleinern, bis er zwischen die seitlichen Ränder passt |
| `smooth` | bool | `true` | | Rundungen glätten, Ecken bleiben scharf. Wirkt nur bei Hershey-Schriften. |

**Optischer Ausgleich** (`spacing_mode: "optical"`): Die festen Zeichenbreiten der Schrift werden ignoriert.
Jedes Zeichen wird in 30 waagrechte Streifen zerlegt, und pro Streifen wird gemessen, wo die Linie links und rechts endet.
Das nächste Zeichen wird so gesetzt, dass ½ · engste Lücke + ½ · mittlere Lücke = `tracking` % der Höhe ergibt.
Tiefe Einbuchtungen (z. B. beim T, L, r) zählen nur bis 22 % der Höhe, und die engste Stelle bleibt
mindestens 35 % der Ziel-Lücke breit, damit sich keine Buchstaben berühren. Prinzip wie HT Letterspacer.

**Schriften** (`font`):

| Schlüssel | Schrift | Art |
|---|---|---|
| `relief` | Relief SingleLine (Standard, empfohlen) | SVG, echte Kurven, Kerning, Umlaute, ß, € |
| `readability` | EMS Readability | SVG, schlichte Grotesk |
| `tech` | EMS Tech | SVG, technische Handschrift |
| `osmotron` | EMS Osmotron | SVG, eckig-geometrisch |
| `allure` | EMS Allure | SVG, Schreibschrift |
| `futural`, `futuram`, `rowmans`, `rowmand`, `scripts`, `timesr` | Hershey-Schriften | grobes Raster, ohne Umlaute (werden aus Buchstabe + Strichen gebaut), ohne € |

Die SVG-Schriften liegen im Ordner `fonts/`. Fehlt eine Datei, taucht die Schrift in `/api/v1/parameters` nicht auf.

### Logo

| Feld | Typ | Standard | Bereich | Bedeutung |
|---|---|---|---|---|
| `logo_on` | bool | `true` | | Logo gravieren (nur wenn eines gespeichert ist oder im Auftrag mitkommt) |
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

> Ist ein Logo gespeichert, wird es bei **jedem** Auftrag mitgraviert. Wer das nicht will, schickt `"logo_on": false`.

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
| `park` | bool | `true` | | Am Ende in die VIEW-/Parkposition fahren: erst `G00 Z…`, dann `G00 X… Y…`. Bei `false` fährt die Fräse zum Werkstück-Nullpunkt (`G00 X0 Y0`) zurück. |
| `park_x` | Zahl | 33,7 | −203,2–203,2 | Parkposition X im gewählten Koordinatensystem (`wcs`) |
| `park_y` | Zahl | 121,8 | −152,4–152,4 | Parkposition Y im gewählten Koordinatensystem |
| `park_z` | Zahl | 57,5 | 0–70 | Parkposition Z im gewählten Koordinatensystem. Nie tiefer als `safe_z`. |
| `line_w` | Zahl | 0,3 | 0,05–5 | Linienbreite. Nur für die Vorschau und als Standard für `fill_step`. |

Die Standardwerte der Parkposition sind die VIEW-Position der SRM-20, gemessen im G54-System. Weil sie sich auf den
Werkstück-Nullpunkt beziehen, verschieben sie sich mit ihm. Bei einem stark anderen Nullpunkt die Werte anpassen.

---

## Logo und Kontur als JSON

Logo und Werkstück-Kontur haben überall dieselbe Form. Genau **eines** der Felder `svg`, `dxf`, `base64`, `strokes` angeben:

```json
{"svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" …>…</svg>"}
{"dxf": "0\nSECTION\n…"}
{"name": "logo.dwg", "base64": "QUMxMDMy…"}
{"strokes": [[[0, 0], [80, 0], [80, 40], [0, 40], [0, 0]]]}
```

| Feld | Bedeutung |
|---|---|
| `svg` | SVG-Datei als Text |
| `dxf` | DXF-Datei als Text |
| `base64` | Beliebige Datei (SVG, DXF, DWG) Base64-kodiert. Dann ist `name` mit Dateiendung Pflicht. |
| `strokes` | Fertige Linien in mm |
| `name` | Anzeigename, optional |

- Die linke untere Ecke der Zeichnung wird auf 0/0 verschoben.
- Kontur: Es zählen nur geschlossene Linien. Ihre Größe ist die echte Werkstückgröße.
- Das Logo wird ohnehin in den freien Bereich eingepasst, seine Größe in der Datei ist egal.
- Texte in der Datei werden ausgelassen (vorher in Kurven umwandeln). DWG braucht den „ODA File Converter“.
- Maximal 25 MB pro Anfrage.

Zwei Wege:

**1. Im Auftrag mitschicken** (gilt nur für diesen Auftrag, nichts wird gespeichert):

```json
{"text": "Max Muster", "logo": {"svg": "<svg …>"}, "plate_contour": {"strokes": [[[0,0],[80,0],[80,40],[0,40],[0,0]]]}}
```

**2. Dauerhaft speichern** (gilt für alle folgenden Aufträge und für die Weboberfläche):

| Methode | Pfad | Body | Antwort |
|---|---|---|---|
| PUT | `/api/v1/assets/logo` · `/api/v1/assets/plate` | Objekt wie oben | `{"ok": true, "asset": {"name": …, "notes": […], "size": [b, h]}}` |
| GET | dieselben Pfade | – | `{"ok": true, "asset": {…}}` oder `"asset": null`. Mit `?include=geometry` samt `strokes`. |
| DELETE | dieselben Pfade | – | `{"ok": true, "asset": null}` |

`notes` enthält Hinweise vom Import, z. B. ausgelassene Texte oder ignorierte offene Linien.
Eine gespeicherte Kontur wird nur benutzt, wenn der Auftrag `"plate_src": "file"` setzt.

---

## Beispiele

### Python

```python
import time
import requests

API = "http://localhost:5000/api/v1"

def call(method, path, **json):
    r = requests.request(method, API + path, json=json or None, timeout=60).json()
    if not r["ok"]:
        raise SystemExit(f"{r['error']['code']}: {r['error']['message']}")
    return r

# 1) Ist die Fräse frei?
m = call("GET", "/status")["machine"]
assert m["can_send"] and m["printer"] and not m["busy"], m

# 2) Auftrag berechnen und prüfen
job = call("POST", "/jobs", text="Max Muster", height=10, depth=0.2, feed=240,
           logo={"svg": open("logo.svg", encoding="utf-8").read()})["job"]
print(f"Dauer ca. {job['minutes']} min")
for w in job["warnings"]:
    print("Warnung:", w["message"])

# 3) Fräsen
job = call("POST", f"/jobs/{job['id']}/start")["job"]

# 4) Warten, bis alles übertragen ist
while job["state"] in ("queued", "running", "error"):
    time.sleep(3)
    job = call("GET", f"/jobs/{job['id']}")["job"]
print("Ergebnis:", job["state"], job["message"] or "")
```

### curl

```bash
# Zustand
curl http://localhost:5000/api/v1/status

# Erst nur den Umriss in der Luft abfahren (Nullpunkt prüfen)
curl -X POST http://localhost:5000/api/v1/jobs -d '{"mode": "outline", "start": true}'

# Gravieren
curl -X POST http://localhost:5000/api/v1/jobs -d '{"text": "Max Muster", "depth": 0.2, "start": true}'

# Abbrechen
curl -X POST http://localhost:5000/api/v1/jobs/942304c28c75/cancel
```

Unter Windows-`cmd` die Anführungszeichen im JSON als `\"` schreiben oder das JSON aus einer Datei lesen (`-d @auftrag.json`).

### JavaScript

```js
const r = await fetch("http://localhost:5000/api/v1/jobs", {
  method: "POST",
  body: JSON.stringify({text: "Max Muster", depth: 0.2, start: true}),
}).then(r => r.json());
if (!r.ok) throw new Error(r.error.message);
console.log(r.job.id, r.job.state);
```

Aus einer Webseite im Browser geht das nur, wenn der Server mit `SRM20_CORS` gestartet wurde (siehe unten).

---

## Betrieb

Einstellungen über Umgebungsvariablen, vor dem Start setzen (in `start.bat` z. B. `set SRM20_PORT=8080`):

| Variable | Standard | Bedeutung |
|---|---|---|
| `SRM20_HOST` | `0.0.0.0` | Netzwerkadresse. `127.0.0.1` = nur dieser PC. |
| `SRM20_PORT` | `5000` | Port |
| `SRM20_API_KEY` | – | Wenn gesetzt, brauchen Zugriffe von **anderen Rechnern** den Header `X-API-Key: <Schlüssel>` (oder `Authorization: Bearer <Schlüssel>`). Zugriffe vom PC selbst bleiben frei. Gilt auch für die Weboberfläche auf anderen Geräten. |
| `SRM20_PRINTER` | – | Druckername der Fräse, falls er nicht „SRM“ enthält |
| `SRM20_SIMULATE` | – | `1` = **Simulation**: Es wird nichts gesendet. Der G-Code landet in `data/simulated/`, der Auftrag ist sofort `done` und trägt `simulated: true`. Gut zum Entwickeln der externen App ohne Fräse. |
| `SRM20_CORS` | – | Erlaubte Herkunft für Browser-Apps, z. B. `http://localhost:3000`. `*` erlaubt jede Webseite und ist riskant, weil dann jede geöffnete Seite die Fräse starten kann. |

Hinweise:
- Ohne `SRM20_API_KEY` kann jeder im Netz, der den Port erreicht, die Fräse starten. Die Verbindung ist
  unverschlüsselt (HTTP), der Schlüssel schützt also nur in einem vertrauenswürdigen Netz.
- In VPanel muss der Befehlssatz **NC-Code** sein und der Nullpunkt im passenden Koordinatensystem (`wcs`) gesetzt.
- Gespeichertes Logo, Kontur und Vorlagen liegen im Ordner `data/` und gelten für alle. Programme, die
  gleichzeitig verschiedene Logos brauchen, schicken sie besser im Auftrag mit (`logo`).

---

## Ältere Endpunkte (Weboberfläche)

Die Weboberfläche benutzt weiter die Endpunkte der ersten Version. Sie bleiben erhalten, neue Programme
sollten aber `/api/v1` verwenden.

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/info` | Schriften, Drucker, Vorlagen, gespeichertes Logo/Kontur |
| POST | `/api/preview` | Schild berechnen: Linien, Warnungen (als Texte), G-Code, Dauer |
| POST | `/api/send` | Berechnen und senden. Antwort `{"ok": true, "minutes": …, "job": "<id>"}` |
| POST · DELETE | `/api/upload/logo` · `/api/upload/plate` | Datei-Upload als `multipart/form-data`, Feldname `file` |
| POST | `/api/presets` | Werkstück-Vorlage speichern: `{"name": …, "w": …, "h": …, "r": …}` |
| DELETE | `/api/presets?name=…` | Werkstück-Vorlage löschen |

Unterschiede zu v1: Diese Endpunkte brauchen `Content-Type: application/json`, ersetzen ungültige Werte
stillschweigend durch den Standardwert bzw. die Grenze, kennen keine Sperre bei Warnungen und reihen
mehrere Aufträge einfach hintereinander ein. Fehler kommen als `{"ok": false, "error": "Text"}`.
Ein mit `/api/send` gestarteter Auftrag ist auch unter `/api/v1/jobs/<id>` sichtbar.
