"""
Gespeicherte Dateien im Ordner data/: Logo, Werkstück-Kontur, eigene Vorlagen.
Standard-Logos (immer verfügbar, im Git) liegen im Ordner logos/.
Dazu das Einlesen von Logo/Kontur aus einer Datei oder direkt aus JSON.
"""
import base64
import binascii
import json
import math
import os

import engraving as E
import importer

DATA = E.BASE / "data"
LOGO_DIR = E.BASE / "logos"   # Standard-Logos: einfach SVG/DXF/DWG-Dateien hineinlegen
LOGO_EXT = (".svg", ".dxf", ".dwg")
ASSETS = ("logo", "plate")
DEFAULT_PRESETS = [{"name": "Plate 70 × 50 mm", "w": 70, "h": 50, "r": 3, "builtin": True}]
MAX_POINTS = 500_000


class BadAsset(ValueError):
    """Logo oder Kontur ist nicht verwendbar (Meldung auf Deutsch)."""


def load_json(name, default=None):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj), encoding="utf-8")


# ---------------------------------------------------------------- Vorlagen

def presets():
    return DEFAULT_PRESETS + load_json("presets.json", [])


# ---------------------------------------------------------------- Standard-Logos (Ordner logos/)

_lib_cache = {}  # Dateiname -> (Änderungszeit, Asset)


def library():
    """Dateinamen aller Standard-Logos, alphabetisch."""
    if not LOGO_DIR.is_dir():
        return []
    return sorted((f.name for f in LOGO_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in LOGO_EXT and not f.name.startswith(".")),
                  key=str.lower)


def library_logo(name):
    """Ein Standard-Logo laden. Nur Dateien, die wirklich im Ordner logos/ liegen (kein Pfad)."""
    if not isinstance(name, str) or name not in library():
        raise BadAsset(f"Standard logo \"{name}\" does not exist. Available: " + (", ".join(library()) or "none"))
    f = LOGO_DIR / name
    mtime = f.stat().st_mtime
    hit = _lib_cache.get(name)
    if not hit or hit[0] != mtime:
        hit = (mtime, asset_from_file("logo", name, f.read_bytes()))
        _lib_cache[name] = hit
    return hit[1]


def library_info():
    out = []
    for name in library():
        try:
            a = library_logo(name)
            out.append({"name": name, "size": a["size"], "notes": a["notes"]})
        except BadAsset as e:
            out.append({"name": name, "error": str(e)})
    return out


# ---------------------------------------------------------------- Logo / Kontur

def load_asset(kind):
    a = load_json(f"{kind}.json")
    return a if a and a.get("strokes") else None


def save_asset(kind, asset):
    save_json(f"{kind}.json", {"name": asset["name"], "strokes": asset["strokes"], "notes": asset["notes"]})


def delete_asset(kind):
    (DATA / f"{kind}.json").unlink(missing_ok=True)


def asset_info(kind):
    a = load_asset(kind)
    if not a:
        return None
    x0, y0, x1, y1 = E.bbox_of(a["strokes"])
    return {"name": a["name"], "notes": a.get("notes", []), "size": (round(x1 - x0, 2), round(y1 - y0, 2))}


def _finish(kind, name, strokes, notes):
    """Gemeinsamer Abschluss: Kontur muss geschlossen sein, linke untere Ecke -> 0/0."""
    notes = list(notes)
    if kind == "plate":
        closed = [s for s in strokes if E.is_closed(s)]
        if not closed:
            raise BadAsset("No closed contour found – the workpiece outline "
                           "must be a closed line.")
        if len(closed) < len(strokes):
            notes.append(f"{len(strokes) - len(closed)} open lines ignored.")
        strokes = closed
    x0, y0, x1, y1 = E.bbox_of(strokes)
    strokes = E.rnd(E.transform(strokes, 1, -x0, -y0))
    return {"name": name, "strokes": strokes, "notes": notes,
            "size": (round(x1 - x0, 2), round(y1 - y0, 2))}


def asset_from_file(kind, filename, data):
    """Datei (SVG/DXF/DWG) als Bytes -> Logo bzw. Kontur."""
    try:
        strokes, notes = importer.load(filename, data)
    except importer.ImportFailed as e:
        raise BadAsset(str(e))
    return _finish(kind, filename, strokes, notes)


def _strokes_from_json(v):
    if not isinstance(v, list) or not v:
        raise BadAsset("strokes must be a list of lines: [[[x, y], [x, y], …], …]")
    out, n = [], 0
    for s in v:
        if not isinstance(s, list) or len(s) < 2:
            raise BadAsset("Each line in strokes needs at least two points.")
        line = []
        for pt in s:
            ok = (isinstance(pt, (list, tuple)) and len(pt) == 2
                  and all(isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in pt))
            if not ok:
                raise BadAsset("Each point in strokes must be [x, y] with two numbers.")
            line.append((float(pt[0]), float(pt[1])))
        n += len(line)
        if n > MAX_POINTS:
            raise BadAsset(f"Too many points (more than {MAX_POINTS}).")
        out.append(line)
    return out


def asset_from_json(kind, obj):
    """Logo bzw. Kontur direkt aus JSON. Genau eine dieser Formen:

    {"svg": "<svg …>…</svg>"}                 SVG als Text
    {"dxf": "0\\nSECTION…"}                    DXF als Text
    {"name": "logo.dwg", "base64": "…"}       beliebige Datei (SVG/DXF/DWG), Base64-kodiert
    {"strokes": [[[x, y], [x, y], …], …]}     fertige Linien in mm
    {"library": "firma.svg"}                  Standard-Logo aus dem Ordner logos/ (nur Logo)
    "name" ist überall erlaubt und nur bei base64 Pflicht (wegen der Dateiendung)."""
    if not isinstance(obj, dict):
        raise BadAsset("Object expected, e.g. {\"svg\": \"<svg …>\"} or {\"strokes\": […]}.")
    forms = ("svg", "dxf", "base64", "strokes", "library")
    given = [k for k in forms if obj.get(k) is not None]
    if len(given) != 1:
        raise BadAsset("Specify exactly one of the fields svg, dxf, base64, strokes or library.")
    unknown = [k for k in obj if k not in forms + ("name",)]
    if unknown:
        raise BadAsset("Unknown field: " + ", ".join(map(str, unknown)))
    form, value = given[0], obj[given[0]]
    name = obj.get("name")
    if name is not None and not isinstance(name, str):
        raise BadAsset("name must be a string.")
    name = os.path.basename(name or "")[:120]

    if form == "library":
        if kind != "logo":
            raise BadAsset("library is only available for logos (folder logos/).")
        return library_logo(value)
    if form == "strokes":
        return _finish(kind, name or "strokes", _strokes_from_json(value), [])
    if not isinstance(value, str) or not value.strip():
        raise BadAsset(f"{form} must be a non-empty string.")
    if form == "base64":
        if not name:
            raise BadAsset("With base64, name including the file extension is required (e.g. \"logo.svg\").")
        try:
            data = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise BadAsset("base64 is not validly encoded.")
        return asset_from_file(kind, name, data)
    if not name.lower().endswith("." + form):
        name = (name or kind) + "." + form
    return asset_from_file(kind, name, value.encode("utf-8"))
