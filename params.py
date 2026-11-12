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
       doc="rect = plate from plate_w/plate_h/plate_r, file = stored contour"),
    _n("plate_w", 70, 5, 1000, group="plate", doc="Width (X)"),
    _n("plate_h", 50, 5, 1000, group="plate", doc="Height (Y)"),
    _n("plate_r", 3, 0, 500, group="plate", doc="Corner radius"),
    # --- Spannbereiche (Sperrzonen links und rechts)
    _b("clamp_on", True, group="clamp",
       doc="Lock clamp zones left and right: circle reaching into the workpiece; never traversed"),
    _n("clamp_d", E.CLAMP_D, 1, 200, group="clamp", doc="Diameter of the clamp circle"),
    _n("clamp_in", E.CLAMP_IN, 0, 100, group="clamp", doc="How far the circle reaches into the workpiece"),
    _n("clamp_y", None, -1000, 1000, group="clamp", doc="Y of the circle centre (default: half the workpiece height)"),
    _n("clamp_margin", 0, 0, 20, group="clamp", doc="Additional safety margin around the circle"),
    # --- Text
    Param("text", "string", "", hi=E.MAX_CHARS, group="text", doc="Engraving text, line break with \\n"),
    _c("font", E.font_key(E.DEFAULT_FONT), E.FONTS, group="text", doc="Font"),
    _n("height", 10, 0.5, 100, group="text", doc="Height of capital letters"),
    _c("spacing_mode", "optical", ("optical", "font"), group="text",
       doc="optical = spacing by letter shape, font = spacing and kerning from the font"),
    _n("tracking", E.OPT_TRACKING, 0, 150, unit="%", group="text",
       doc="Tracking for optical: target gap in % of the text height"),
    _n("width_pct", 100, 50, 200, unit="%", group="text", doc="Character width"),
    _n("letter_spacing", 0, -3, 10, group="text", doc="Additional letter spacing"),
    _n("text_bottom", 3, 0, group="text", doc="Distance text – bottom edge of the workpiece"),
    _n("margin_side", 3, 0, group="text", doc="Margin left and right"),
    _c("align", "center", ("left", "center", "right"), group="text",
       doc="Alignment of multiple lines to each other"),
    _b("autoshrink", True, group="text", doc="Automatically shrink text that is too wide"),
    _b("smooth", True, group="text", doc="Smooth curves (Hershey fonts only)"),
    # --- Logo
    _b("logo_on", True, group="logo", doc="Engrave the logo if one is available"),
    _n("logo_gap", 3, 0, group="logo", doc="Distance top of text – logo area"),
    _n("margin_top", 3, 0, group="logo", doc="Top margin"),
    _n("logo_scale", 100, 1, 1000, unit="%", group="logo", doc="Size, 100 = fitted"),
    _n("logo_dx", 0, group="logo", doc="Offset in X"),
    _n("logo_dy", 0, group="logo", doc="Offset in Y"),
    _b("logo_fill", False, group="logo", doc="Fill closed areas with lines"),
    _n("fill_step", None, 0.05, 10, group="logo", doc="Line spacing when filling (default: line_w × 0.8)"),
    _n("logo_depth", None, 0.01, 5, group="logo", doc="Cutting depth logo (default: same as depth)"),
    # --- Fräsen
    _c("mode", "engrave", ("engrave", "air", "outline"), group="milling",
       doc="engrave = engrave, air = toolpath 1 mm above the surface, outline = trace the outline"),
    _n("depth", 0.2, 0.01, 5, group="milling", doc="Cutting depth text"),
    Param("passes", "integer", 1, 1, 10, group="milling", doc="Passes"),
    _n("feed", 240, 10, 1800, unit="mm/min", group="milling", doc="Feed rate"),
    _n("plunge", 60, 5, 1800, unit="mm/min", group="milling", doc="Plunge rate"),
    _n("rpm", 7000, 3000, 7000, unit="U/min", group="milling", doc="Spindle speed"),
    _n("safe_z", 2, 0.5, 30, group="milling", doc="Safe height for rapid moves"),
    _c("wcs", "G54", E.WCS, group="milling", doc="Work coordinate system from VPanel"),
    _b("park", True, group="milling", doc="Move to the VIEW/park position at the end"),
    _n("park_x", E.PARK_X, -E.WORK_X, E.WORK_X, group="milling", doc="Park position X"),
    _n("park_y", E.PARK_Y, -E.WORK_Y, E.WORK_Y, group="milling", doc="Park position Y"),
    _n("park_z", E.PARK_Z, 0, 70, group="milling", doc="Park position Z"),
    _n("line_w", 0.3, 0.05, 5, group="milling", doc="Line width (preview, default for fill_step)"),
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
    raise Invalid("must be true or false")


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
            raise Invalid("must be a number")
        return p.default
    if p.kind == "integer":
        if strict and f != int(f):
            raise Invalid("must be an integer")
        f = int(f)
    for limit, bad, word in ((p.lo, lambda: f < p.lo, "at least"), (p.hi, lambda: f > p.hi, "at most")):
        if limit is not None and bad():
            if strict:
                raise Invalid(f"must be {word} {_fmt(limit)} (is {_fmt(f)})")
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
                raise Invalid("must be a string")
            v = str(v)
        if len(v) > p.hi:
            if strict:
                raise Invalid(f"at most {p.hi} characters (got {len(v)})")
            v = v[:p.hi]
        return v
    if v not in p.choices:  # choice
        if strict:
            raise Invalid("allowed: " + ", ".join(p.choices))
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
            errors.append({"field": "", "message": "A JSON object is expected."})
        raw = {}
    out = {}
    for p in PARAMS:
        v = raw.get(p.name)
        out[p.name] = p.default
        # nichts angegeben (fehlt, null oder leerer Text) -> Standardwert. So bleiben z. B. die
        # Spannbereiche an, solange nicht ausdrücklich "clamp_on": false geschickt wird.
        if v is None or (p.kind != "string" and isinstance(v, str) and not v.strip()):
            continue
        try:
            out[p.name] = _convert(p, v, strict)
        except Invalid as e:
            errors.append({"field": p.name, "message": str(e)})
    if strict:
        for key in raw:
            if key not in NAMES and key not in extra:
                near = difflib.get_close_matches(str(key), list(NAMES) + list(extra), 1)
                errors.append({"field": str(key), "message": "unknown field"
                               + (f" – did you mean \"{near[0]}\"?" if near else "")})
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
