"""
Auftrags-Parameter: eine Tabelle für Standardwerte, Grenzen, Prüfung und die Beschreibung in der API.

parse(raw, strict=True)   -> Fehlerliste bei falschem Typ, Wert außerhalb der Grenzen, unbekanntem Feld
parse(raw, strict=False)  -> nachsichtig wie die Weboberfläche: ungültig = Standardwert,
                             außerhalb der Grenzen = auf die Grenze gesetzt
"""
import difflib
import math
from dataclasses import dataclass

import engraving as E


@dataclass(frozen=True)
class Param:
    name: str
    kind: str            # number | integer | boolean | string | choice
    default: object
    lo: float = None
    hi: float = None     # bei string: maximale Länge
    choices: tuple = None
    group: str = ""
    unit: str = None
    doc: str = ""


def _n(name, default, lo=None, hi=None, unit="mm", doc="", group=""):
    return Param(name, "number", default, lo, hi, None, group, unit, doc)


def _b(name, default, doc="", group=""):
    return Param(name, "boolean", default, group=group, doc=doc)


def _c(name, default, choices, doc="", group=""):
    return Param(name, "choice", default, choices=tuple(choices), group=group, doc=doc)


PARAMS = [
    # --- Werkstück
    _c("plate_src", "rect", ("rect", "file"), group="plate",
       doc="rect = Platte aus plate_w/plate_h/plate_r, file = gespeicherte Kontur"),
    _n("plate_w", 70, 5, 1000, group="plate", doc="Breite (X)"),
    _n("plate_h", 50, 5, 1000, group="plate", doc="Höhe (Y)"),
    _n("plate_r", 3, 0, 500, group="plate", doc="Eckradius"),
    # --- Spannbereiche (Sperrzonen links und rechts)
    _b("clamp_on", True, group="clamp",
       doc="Spannbereiche links und rechts sperren: Kreis, der ins Werkstück ragt; wird nie durchfahren"),
    _n("clamp_d", E.CLAMP_D, 1, 200, group="clamp", doc="Durchmesser des Spannkreises"),
    _n("clamp_in", E.CLAMP_IN, 0, 100, group="clamp", doc="So weit ragt der Kreis ins Werkstück"),
    _n("clamp_y", None, -1000, 1000, group="clamp", doc="Y der Kreismitte (Standard: halbe Werkstückhöhe)"),
    _n("clamp_margin", 0, 0, 20, group="clamp", doc="Zusätzlicher Sicherheitsabstand um den Kreis"),
    # --- Text
    Param("text", "string", "", hi=E.MAX_CHARS, group="text", doc="Gravurtext, Zeilenumbruch mit \\n"),
    _c("font", E.font_key(E.DEFAULT_FONT), E.FONTS, group="text", doc="Schrift"),
    _n("height", 10, 0.5, 100, group="text", doc="Höhe der Großbuchstaben"),
    _c("spacing_mode", "optical", ("optical", "font"), group="text",
       doc="optical = Abstände nach Buchstabenform, font = Abstände und Kerning der Schrift"),
    _n("tracking", E.OPT_TRACKING, 0, 150, unit="%", group="text",
       doc="Laufweite bei optical: Ziel-Lücke in % der Schrifthöhe"),
    _n("width_pct", 100, 50, 200, unit="%", group="text", doc="Schriftbreite"),
    _n("letter_spacing", 0, -3, 10, group="text", doc="Zusätzlicher Zeichenabstand"),
    _n("text_bottom", 3, 0, group="text", doc="Abstand Text – unterer Werkstückrand"),
    _n("margin_side", 3, 0, group="text", doc="Rand links und rechts"),
    _c("align", "center", ("left", "center", "right"), group="text",
       doc="Ausrichtung mehrerer Zeilen zueinander"),
    _b("autoshrink", True, group="text", doc="Zu breiten Text automatisch verkleinern"),
    _b("smooth", True, group="text", doc="Rundungen glätten (nur Hershey-Schriften)"),
    # --- Logo
    _b("logo_on", True, group="logo", doc="Logo gravieren, wenn eines vorhanden ist"),
    _n("logo_gap", 3, 0, group="logo", doc="Abstand Textoberkante – Logo-Bereich"),
    _n("margin_top", 3, 0, group="logo", doc="Rand oben"),
    _n("logo_scale", 100, 1, 1000, unit="%", group="logo", doc="Größe, 100 = eingepasst"),
    _n("logo_dx", 0, group="logo", doc="Verschiebung in X"),
    _n("logo_dy", 0, group="logo", doc="Verschiebung in Y"),
    _b("logo_fill", False, group="logo", doc="Geschlossene Flächen mit Linien füllen"),
    _n("fill_step", None, 0.05, 10, group="logo", doc="Linienabstand beim Füllen (Standard: line_w × 0,8)"),
    _n("logo_depth", None, 0.01, 5, group="logo", doc="Frästiefe Logo (Standard: wie depth)"),
    # --- Fräsen
    _c("mode", "engrave", ("engrave", "air", "outline"), group="milling",
       doc="engrave = gravieren, air = Bahn 1 mm über der Oberfläche, outline = Umriss abfahren"),
    _n("depth", 0.2, 0.01, 5, group="milling", doc="Frästiefe Text"),
    Param("passes", "integer", 1, 1, 10, group="milling", doc="Durchgänge"),
    _n("feed", 240, 10, 1800, unit="mm/min", group="milling", doc="Vorschub"),
    _n("plunge", 60, 5, 1800, unit="mm/min", group="milling", doc="Eintauchgeschwindigkeit"),
    _n("rpm", 7000, 3000, 7000, unit="U/min", group="milling", doc="Spindeldrehzahl"),
    _n("safe_z", 2, 0.5, 30, group="milling", doc="Sicherheitshöhe für Leerfahrten"),
    _c("wcs", "G54", E.WCS, group="milling", doc="Werkstück-Koordinatensystem aus VPanel"),
    _b("park", True, group="milling", doc="Am Ende in die VIEW-/Parkposition fahren"),
    _n("park_x", E.PARK_X, -E.WORK_X, E.WORK_X, group="milling", doc="Parkposition X"),
    _n("park_y", E.PARK_Y, -E.WORK_Y, E.WORK_Y, group="milling", doc="Parkposition Y"),
    _n("park_z", E.PARK_Z, 0, 70, group="milling", doc="Parkposition Z"),
    _n("line_w", 0.3, 0.05, 5, group="milling", doc="Linienbreite (Vorschau, Standard für fill_step)"),
]
NAMES = [p.name for p in PARAMS]

_TRUE = ("1", "true", "yes", "ja", "on", "y", "j")
_FALSE = ("0", "false", "no", "nein", "off", "n", "")


class Invalid(ValueError):
    pass


def to_bool(v, strict=True):
    """true/false, 1/0 oder Text wie "true", "ja", "on" / "false", "nein", "off"."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in _TRUE:
            return True
        if s in _FALSE or not strict:
            return False
    elif isinstance(v, (int, float)) and (v in (0, 1) or not strict):
        return bool(v)
    elif not strict:
        return bool(v)
    raise Invalid("muss true oder false sein")


def _fmt(x):
    return f"{x:g}".replace(".", ",")


def _number(p, v, strict):
    try:
        if isinstance(v, bool) and strict:
            raise ValueError
        f = float(v)
        if not math.isfinite(f):
            raise ValueError
    except (TypeError, ValueError):
        if strict:
            raise Invalid("muss eine Zahl sein")
        return p.default
    if p.kind == "integer":
        if strict and f != int(f):
            raise Invalid("muss eine ganze Zahl sein")
        f = int(f)
    for limit, bad, word in ((p.lo, lambda: f < p.lo, "mindestens"), (p.hi, lambda: f > p.hi, "höchstens")):
        if limit is not None and bad():
            if strict:
                raise Invalid(f"muss {word} {_fmt(limit)} sein (ist {_fmt(f)})")
            f = int(limit) if p.kind == "integer" else float(limit)
    return f


def _convert(p, v, strict):
    if p.kind in ("number", "integer"):
        return _number(p, v, strict)
    if p.kind == "boolean":
        return to_bool(v, strict)
    if p.kind == "string":
        if not isinstance(v, str):
            if strict:
                raise Invalid("muss ein Text sein")
            v = str(v)
        if len(v) > p.hi:
            if strict:
                raise Invalid(f"höchstens {p.hi} Zeichen (sind {len(v)})")
            v = v[:p.hi]
        return v
    if v not in p.choices:  # choice
        if strict:
            raise Invalid("erlaubt: " + ", ".join(p.choices))
        return p.default
    return v


def parse(raw, strict=True, extra=()):
    """Prüft die Auftrags-Parameter. Liefert (werte, fehler).

    werte enthält immer alle Felder aus PARAMS. fehler ist eine Liste von
    {"field": ..., "message": ...} und im nachsichtigen Modus immer leer.
    extra: weitere erlaubte Feldnamen, die der Aufrufer selbst auswertet."""
    errors = []
    if not isinstance(raw, dict):
        if strict:
            errors.append({"field": "", "message": "Es wird ein JSON-Objekt erwartet."})
        raw = {}
    out = {}
    for p in PARAMS:
        v = raw.get(p.name)
        out[p.name] = p.default
        if v is None:
            continue
        try:
            out[p.name] = _convert(p, v, strict)
        except Invalid as e:
            errors.append({"field": p.name, "message": str(e)})
    if strict:
        for key in raw:
            if key not in NAMES and key not in extra:
                near = difflib.get_close_matches(str(key), list(NAMES) + list(extra), 1)
                errors.append({"field": str(key), "message": "unbekanntes Feld"
                               + (f" – meintest du „{near[0]}“?" if near else "")})
    # abhängige Standardwerte
    if out["logo_depth"] is None:
        out["logo_depth"] = out["depth"]
    if out["fill_step"] is None:
        out["fill_step"] = min(10.0, max(0.05, out["line_w"] * 0.8))
    return out, errors


def schema():
    """Maschinenlesbare Beschreibung aller Felder (für GET /api/v1/parameters)."""
    out = []
    for p in PARAMS:
        d = {"name": p.name, "type": p.kind, "default": p.default, "group": p.group, "description": p.doc}
        if p.kind == "string":
            d["max_length"] = p.hi
        else:
            if p.lo is not None:
                d["min"] = p.lo
            if p.hi is not None:
                d["max"] = p.hi
        if p.choices:
            d["choices"] = list(p.choices)
        if p.unit and p.kind in ("number", "integer"):
            d["unit"] = p.unit
        out.append(d)
    return out
