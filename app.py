"""
SRM-20 Gravur – Schild mit Text und Logo gestalten, Vorschau ansehen, direkt an die Roland SRM-20 senden.

Start:  start.bat   (oder: python app.py)  ->  Browser: http://localhost:5000
Voraussetzung: Roland-Treiber installiert, SRM-20 in VPanel auf "NC-Code" gestellt.
Nullpunkt: X/Y = linke untere Ecke des Werkstücks, Z = Oberseite des Werkstücks.
"""
import json
import math
import re
import sys
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from HersheyFonts import HersheyFonts

import importer

try:
    import win32print  # pywin32 – nur unter Windows verfügbar
except ImportError:
    win32print = None

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"  # hochgeladenes Logo, Werkstück-Kontur, eigene Vorlagen

# Arbeitsbereich SRM-20 (X x Y in mm)
WORK_X, WORK_Y = 203.2, 152.4
MAX_CHARS = 200
EDGE_MIN = 0.5  # mm – näher am Werkstückrand gibt es eine Warnung

DEFAULT_PRESETS = [{"name": "Platte 70 × 50 mm", "w": 70, "h": 50, "r": 3, "builtin": True}]

FONTS = {
    "futural": "Futura leicht (einfach, empfohlen)",
    "futuram": "Futura mittel (doppelte Linie)",
    "rowmans": "Roman einfach",
    "rowmand": "Roman doppelt",
    "scripts": "Schreibschrift",
    "timesr": "Times",
}

# Umlaute kennen die Hershey-Fonts nicht -> Grundbuchstabe + zwei Punkte
UMLAUTS = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}

_font_cache = {}


# ---------------------------------------------------------------- Text

def get_font(name):
    if name not in FONTS:
        name = "futural"
    if name not in _font_cache:
        f = HersheyFonts()
        f.load_default_font(name)
        f.normalize_rendering(100)
        # Großbuchstabenhöhe messen, damit "Höhe" = echte Höhe von H
        ys = [p[1] for s in f.strokes_for_text("H") for p in s]
        _font_cache[name] = (f, max(ys) - min(ys), min(ys))
    return _font_cache[name]


CORNER_DEG = 55  # stärkere Richtungsänderung = echte Ecke, wird nicht verrundet


def _turn(a, b, c):
    """Richtungsänderung in Grad am Punkt b."""
    a1 = math.atan2(b[1] - a[1], b[0] - a[0])
    a2 = math.atan2(c[1] - b[1], c[0] - b[0])
    return abs((math.degrees(a2 - a1) + 180) % 360 - 180)


def _chaikin(pts, closed, iterations=3):
    for _ in range(iterations):
        segs = list(zip(pts, pts[1:]))
        out = [] if closed else [pts[0]]
        for (ax, ay), (bx, by) in segs:
            out.append((0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by))
            out.append((0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by))
        if closed:
            out.append(out[0])
        else:
            out.append(pts[-1])
        pts = out
    return pts


def simplify(pts, tol=0.01):
    """Douglas-Peucker: entfernt Punkte, die weniger als tol mm von der Linie abweichen."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        best, idx = 0.0, None
        for i in range(a + 1, b):
            d = _seg_dist(pts[i], pts[a], pts[b])
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def smooth_stroke(s):
    return simplify(_smooth_stroke(s))


def _smooth_stroke(s):
    """Glättet die groben Hershey-Polygone (Raster ~0,5 mm bei 10 mm Schrift) zu runden Kurven.
    Ecken über CORNER_DEG bleiben scharf, Anfangs- und Endpunkte bleiben, wo sie sind."""
    s = [p for i, p in enumerate(s) if i == 0 or math.dist(p, s[i - 1]) > 1e-9]
    if len(s) < 3:
        return s
    closed = math.dist(s[0], s[-1]) < 1e-6
    n = len(s)
    corner = [False] * n
    for i in range(1, n - 1):
        corner[i] = _turn(s[i - 1], s[i], s[i + 1]) > CORNER_DEG
    if closed and _turn(s[-2], s[0], s[1]) <= CORNER_DEG:
        # geschlossene Kurve ohne Ecke an der Naht (z. B. "o"): Naht auf erste Ecke legen
        # oder - wenn es keine gibt - ringsum glätten
        idx = next((i for i in range(1, n - 1) if corner[i]), None)
        if idx is None:
            return _chaikin(s, closed=True)
        s = s[idx:-1] + s[:idx + 1]
        return _smooth_stroke(s)
    # an Ecken aufteilen, jedes Stück einzeln glätten
    out, start = [s[0]], 0
    for i in range(1, n):
        if i == n - 1 or corner[i]:
            piece = s[start:i + 1]
            out += _chaikin(piece, closed=False)[1:] if len(piece) >= 3 else piece[1:]
            start = i
    return out


def text_to_strokes(text, height, font_name, line_spacing=1.6, align="center", smooth=True):
    """Liefert eine Liste von Polylinien [(x,y), ...] in mm. Grundlinie der 1. Zeile bei y=0."""
    font, cap, base = get_font(font_name)
    k = height / cap
    lines_out = []

    for li, line in enumerate(text.replace("ß", "ss").split("\n")):
        plain = "".join(UMLAUTS.get(c, c) for c in line)
        line_strokes = []
        # Striche pro Zeichen zählen, um Umlaut-Punkte richtig zu platzieren
        all_strokes = [list(s) for s in font.strokes_for_text(plain)]
        idx = 0
        for orig, ch in zip(line, plain):
            n = sum(1 for _ in font.strokes_for_text(ch))
            glyph = all_strokes[idx: idx + n]
            idx += n
            pts = [p for s in glyph for p in s]
            if orig in UMLAUTS and pts:
                xs = [p[0] for p in pts]
                top = max(p[1] for p in pts)
                cx = (min(xs) + max(xs)) / 2
                gap = cap * 0.13
                d = cap * 0.035  # kleine Striche statt Punkte -> sauberer Einstich
                for dx in (-cap * 0.13, cap * 0.13):
                    glyph.append([(cx + dx - d, top + gap), (cx + dx + d, top + gap)])
            line_strokes.extend(glyph)

        y_off = -li * height * line_spacing
        scaled = [[(x * k, (y - base) * k + y_off) for x, y in s] for s in line_strokes if len(s) >= 2]
        if smooth:
            scaled = [smooth_stroke(s) for s in scaled]
        lines_out.append(scaled)

    # Zeilen zueinander ausrichten
    widths = []
    for ls in lines_out:
        xs = [p[0] for s in ls for p in s]
        widths.append((min(xs), max(xs)) if xs else (0, 0))
    full_w = max((b - a for a, b in widths), default=0)
    strokes = []
    for ls, (a, b) in zip(lines_out, widths):
        w = b - a
        shift = -a + {"left": 0, "center": (full_w - w) / 2, "right": full_w - w}[align]
        strokes += [[(x + shift, y) for x, y in s] for s in ls]
    return strokes


def missing_chars(text, font):
    f = get_font(font)[0]
    return sorted({c for c in text if c not in "\n ß" and c not in UMLAUTS
                   and not list(f.strokes_for_text(c))})


# ---------------------------------------------------------------- Geometrie

def bbox_of(strokes):
    pts = [p for s in strokes for p in s]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def transform(strokes, k=1.0, dx=0.0, dy=0.0):
    return [[(x * k + dx, y * k + dy) for x, y in s] for s in strokes]


def rounded_rect(w, h, r, seg=12):
    """Umriss einer Platte mit runden Ecken, linke untere Ecke (des Rechtecks) bei 0/0."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 0:
        return [[(0, 0), (w, 0), (w, h), (0, h), (0, 0)]]
    pts = []
    for cx, cy, a0 in ((w - r, r, -90), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    pts.append(pts[0])
    return [pts]


def is_closed(s):
    return len(s) >= 3 and math.dist(s[0], s[-1]) < 0.05


def _seg_dist(p, a, b):
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def edge_distance(pt, plate):
    """Abstand zum Werkstückrand: positiv = innen, negativ = außerhalb."""
    if plate["kind"] == "rect":
        w, h, r = plate["w"], plate["h"], plate["r"]
        r = max(0.0, min(r, w / 2, h / 2))
        qx = abs(pt[0] - w / 2) - (w / 2 - r)
        qy = abs(pt[1] - h / 2) - (h / 2 - r)
        return -(math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r)
    # freie Kontur: gerade/ungerade-Regel + kürzester Abstand zu einer Kante
    x, y = pt
    inside = False
    best = float("inf")
    for s in plate["strokes"]:
        for a, b in zip(s, s[1:]):
            if (a[1] > y) != (b[1] > y) and x < a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]):
                inside = not inside
            best = min(best, _seg_dist(pt, a, b))
    return best if inside else -best


def hatch(strokes, spacing):
    """Füllt geschlossene Konturen mit waagrechten Linien (gerade/ungerade-Regel, Löcher bleiben frei)."""
    closed = [s for s in strokes if is_closed(s)]
    bb = bbox_of(closed)
    if not bb or spacing <= 0:
        return []
    edges = [(a, b) for s in closed for a, b in zip(s, s[1:]) if a[1] != b[1]]
    out, flip = [], False
    y = bb[1] + spacing / 2
    while y < bb[3]:
        xs = sorted(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
                    for a, b in edges if (a[1] <= y < b[1]) or (b[1] <= y < a[1]))
        segs = [(xs[i], xs[i + 1]) for i in range(0, len(xs) - 1, 2) if xs[i + 1] - xs[i] > 1e-3]
        if flip:
            segs = [(b, a) for a, b in reversed(segs)]
        out += [[(a, y), (b, y)] for a, b in segs]
        flip = not flip
        y += spacing
    return out


def optimize_order(strokes, start=(0.0, 0.0)):
    """Nächster-Nachbar-Sortierung, damit der Fräser nicht kreuz und quer fährt."""
    remaining = strokes[:]
    out, pos = [], start
    while remaining:
        best_i, best_d, rev = 0, float("inf"), False
        for i, s in enumerate(remaining):
            for r, p in ((False, s[0]), (True, s[-1])):
                d = math.dist(pos, p)
                if d < best_d:
                    best_i, best_d, rev = i, d, r
        s = remaining.pop(best_i)
        s = s[::-1] if rev else s
        out.append(s)
        pos = s[-1]
    return out


# ---------------------------------------------------------------- G-Code

WCS = ("G54", "G55", "G56", "G57", "G58", "G59")


def make_gcode(jobs, safe_z, feed, plunge, rpm, passes, wcs="G54"):
    """jobs: Liste von (strokes, tiefe). Tiefe < 0 = über der Oberfläche (Luftschnitt).

    wcs: Werkstück-Koordinatensystem, in dem in VPanel der Nullpunkt gesetzt wurde.
    Ohne ausdrückliche Auswahl kann die SRM-20 in Maschinenkoordinaten fahren
    (-> fährt nach links unten und auf falsche Höhe)."""
    g = ["%",
         "G17 G21 G90",  # XY-Ebene, mm, absolut
         "G40 G49 G80",  # Radius-/Längenkorrektur und Zyklen aus
         wcs,            # Nullpunkt aus VPanel verwenden
         f"G00 Z{safe_z:.3f}",
         # Drehzahl laut Roland-Handbuch als ganze Zahl OHNE Dezimalpunkt (>= 100 = U/min),
         # erst setzen, dann Spindel mit M03 starten
         f"S{int(round(rpm))}",
         "M03"]
    # Vorschub IMMER mit Dezimalpunkt: "F240" würde als 0,240 mm/min gelesen
    # (konventionelle Interpretation, Einheit 0,001 mm/min) -> Fräse fährt mit Minimalspeed
    f_feed, f_plunge = f"F{feed:.1f}", f"F{plunge:.1f}"
    cut_len = travel = 0.0
    pos = (0.0, 0.0)
    plunges = 0
    for strokes, depth in jobs:
        if not strokes:
            continue
        n_pass = passes if depth > 0 else 1
        for p_i in range(1, n_pass + 1):
            z = -depth * p_i / n_pass
            down = False
            for s in strokes:
                x, y = s[0]
                # Schließt der Strich direkt an, bleibt der Fräser unten
                if not (down and math.dist(pos, (x, y)) < 0.01):
                    if down:
                        g.append(f"G00 Z{safe_z:.3f}")
                    g.append(f"G00 X{x:.3f} Y{y:.3f}")
                    g.append(f"G01 Z{z:.3f} {f_plunge}")
                    travel += math.dist(pos, (x, y))
                    plunges += 1
                    down = True
                for i, ((ax, ay), (bx, by)) in enumerate(zip(s, s[1:])):
                    g.append(f"G01 X{bx:.3f} Y{by:.3f}" + (f" {f_feed}" if i == 0 else ""))
                    cut_len += math.hypot(bx - ax, by - ay)
                pos = s[-1]
            g.append(f"G00 Z{safe_z:.3f}")
    g += ["M05", "G00 X0.000 Y0.000", "%"]
    # grobe Zeitschätzung (Eilgang ~ 1800 mm/min)
    minutes = cut_len / feed + travel / 1800 + plunges * (2 * safe_z + 0.5) / plunge
    return "\n".join(g) + "\n", minutes


# ---------------------------------------------------------------- Drucker

def list_printers():
    if not win32print:
        return []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    names = [p[2] for p in win32print.EnumPrinters(flags)]
    return sorted(names, key=lambda n: ("srm" not in n.lower(), n))


def send_raw(printer, data):
    h = win32print.OpenPrinter(printer)
    try:
        win32print.StartDocPrinter(h, 1, ("SRM-20 Gravur", None, "RAW"))
        win32print.StartPagePrinter(h)
        win32print.WritePrinter(h, data.encode("ascii"))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
    finally:
        win32print.ClosePrinter(h)


# ---------------------------------------------------------------- Dateien (Logo, Kontur, Vorlagen)

ASSETS = ("logo", "plate")


def load_json(name, default=None):
    try:
        return json.loads((DATA / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj), encoding="utf-8")


def load_asset(kind):
    a = load_json(f"{kind}.json")
    return a if a and a.get("strokes") else None


def presets():
    return DEFAULT_PRESETS + load_json("presets.json", [])


# ---------------------------------------------------------------- Aufbau des Schilds

def num(p, key, default, lo=None, hi=None):
    try:
        v = float(p.get(key, default))
    except (TypeError, ValueError):
        v = default
    if not math.isfinite(v):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def flag(p, key, default):
    """Wahrheitswert aus JSON: true/false, 1/0 oder Text wie "true", "false", "ja", "nein", "on", "off"."""
    v = p.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "ja", "on", "y", "j")
    return bool(v)


def build(p):
    text = str(p.get("text", ""))[:MAX_CHARS]
    font = p.get("font", "futural")
    align = p.get("align") if p.get("align") in ("left", "center", "right") else "center"
    height = num(p, "height", 10, 0.5, 100)
    depth = num(p, "depth", 0.2, 0.01, 5)
    logo_depth = num(p, "logo_depth", depth, 0.01, 5)
    safe_z = num(p, "safe_z", 2, 0.5, 30)
    feed = num(p, "feed", 240, 10, 1800)
    plunge = num(p, "plunge", 60, 5, 1800)
    rpm = num(p, "rpm", 7000, 3000, 7000)
    passes = int(num(p, "passes", 1, 1, 10))
    line_w = num(p, "line_w", 0.3, 0.05, 5)
    mode = p.get("mode") if p.get("mode") in ("engrave", "air", "outline") else "engrave"
    wcs = p.get("wcs") if p.get("wcs") in WCS else "G54"
    side = num(p, "margin_side", 3, 0)
    bottom = num(p, "text_bottom", 3, 0)
    top = num(p, "margin_top", 3, 0)
    gap = num(p, "logo_gap", 3, 0)
    warnings = []

    # --- Werkstück
    contour = load_asset("plate") if p.get("plate_src") == "file" else None
    if contour:
        plate_strokes = contour["strokes"]
        _, _, pw, ph = bbox_of(plate_strokes)  # beim Import auf 0/0 verschoben
        plate = {"kind": "file", "strokes": plate_strokes, "w": pw, "h": ph}
    else:
        pw = num(p, "plate_w", 70, 5, 1000)
        ph = num(p, "plate_h", 50, 5, 1000)
        pr = num(p, "plate_r", 3, 0, 500)
        plate_strokes = rounded_rect(pw, ph, pr)
        plate = {"kind": "rect", "w": pw, "h": ph, "r": pr}
    if pw > WORK_X or ph > WORK_Y:
        warnings.append(f"Werkstück ({pw:.0f} × {ph:.0f} mm) ist größer als der Arbeitsbereich der SRM-20 "
                        f"({WORK_X:.0f} × {WORK_Y:.0f} mm).")

    # --- Text: zentriert, Unterkante "bottom" mm über der Werkstückkante
    smooth = flag(p, "smooth", True)
    text_s = text_to_strokes(text, height, font, align=align, smooth=smooth) if text.strip() else []
    tb = bbox_of(text_s)
    real_h = height
    if tb and flag(p, "autoshrink", True):
        avail = pw - 2 * side
        tw = tb[2] - tb[0]
        if tw > avail > 0:
            real_h = height * avail / tw
            text_s = text_to_strokes(text, real_h, font, align=align, smooth=smooth)
            tb = bbox_of(text_s)
            warnings.append(f"Text zu breit – Schrifthöhe automatisch auf {real_h:.1f} mm verkleinert.")
    if tb:
        text_s = transform(text_s, 1, pw / 2 - (tb[0] + tb[2]) / 2, bottom - tb[1])
        tb = bbox_of(text_s)
    miss = missing_chars(text, font)
    if miss:
        warnings.append("Nicht in der Schrift enthalten (wird ausgelassen): " + " ".join(miss))

    # --- Logo: in den freien Bereich über dem Text eingepasst
    logo_s, logo_area = [], None
    asset = load_asset("logo") if flag(p, "logo_on", True) else None
    if asset:
        y_lo = tb[3] + gap if tb else bottom
        area = (side, y_lo, pw - side, ph - top)
        aw, ah = area[2] - area[0], area[3] - area[1]
        lb = bbox_of(asset["strokes"])
        if aw > 1 and ah > 1:
            lw, lh = max(lb[2] - lb[0], 1e-6), max(lb[3] - lb[1], 1e-6)
            k = min(aw / lw, ah / lh) * num(p, "logo_scale", 100, 1, 1000) / 100
            cx = (area[0] + area[2]) / 2 + num(p, "logo_dx", 0)
            cy = (area[1] + area[3]) / 2 + num(p, "logo_dy", 0)
            logo_s = transform(asset["strokes"], k, cx - (lb[0] + lb[2]) / 2 * k, cy - (lb[1] + lb[3]) / 2 * k)
            if flag(p, "logo_fill", False):
                fill = hatch(logo_s, num(p, "fill_step", line_w * 0.8, 0.05, 10))
                if not fill:
                    warnings.append("Logo hat keine geschlossenen Flächen – Füllen nicht möglich.")
                logo_s += fill
        else:
            warnings.append("Kein Platz für das Logo – Text kleiner machen oder Ränder verringern.")
        logo_area = area

    # --- Randprüfung
    pts = [pt for s in text_s + logo_s for pt in s]
    if pts:
        worst = min(edge_distance(pt, plate) for pt in pts)
        if worst < 0:
            warnings.append("Achtung: Teile der Gravur liegen AUSSERHALB des Werkstücks!")
        elif worst < EDGE_MIN:
            warnings.append(f"Gravur liegt nur {worst:.2f} mm vom Werkstückrand entfernt.")

    # --- G-Code
    text_o = optimize_order(text_s)
    logo_o = optimize_order(logo_s, text_o[-1][-1] if text_o else (0.0, 0.0))
    if mode == "air":  # Luftschnitt: Fräser fährt 1 mm ÜBER der Oberfläche
        gcode, minutes = make_gcode([(text_o, -1.0), (logo_o, -1.0)], max(safe_z, 3), feed, plunge, rpm, 1, wcs)
    elif mode == "outline":  # nur Werkstückumriss 1 mm über der Oberfläche abfahren
        gcode, minutes = make_gcode([(plate_strokes, -1.0)], max(safe_z, 3), feed, plunge, rpm, 1, wcs)
    else:
        gcode, minutes = make_gcode([(text_o, depth), (logo_o, logo_depth)], safe_z, feed, plunge, rpm, passes, wcs)

    return dict(text=text_s, logo=logo_s, plate=plate_strokes, plate_size=(pw, ph), logo_area=logo_area,
                text_height=real_h if tb else None, text_bbox=tb, gcode=gcode, minutes=minutes,
                warnings=warnings, has_work=bool(text_s or logo_s), mode=mode)


# ---------------------------------------------------------------- Web

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


def rnd(strokes):
    return [[(round(x, 3), round(y, 3)) for x, y in s] for s in strokes]


@app.get("/")
def index():
    return send_file(BASE / "index.html")


@app.get("/api/info")
def info():
    assets = {}
    for kind in ASSETS:
        a = load_asset(kind)
        assets[kind] = {"name": a["name"], "notes": a.get("notes", [])} if a else None
    return jsonify(fonts=FONTS, printers=list_printers(), windows=bool(win32print),
                   presets=presets(), assets=assets)


@app.post("/api/preview")
def preview():
    r = build(request.json or {})
    return jsonify(text=rnd(r["text"]), logo=rnd(r["logo"]), plate=rnd(r["plate"]),
                   plate_size=r["plate_size"], logo_area=r["logo_area"], text_height=r["text_height"],
                   text_bbox=r["text_bbox"], minutes=r["minutes"], warnings=r["warnings"],
                   lines=r["gcode"].count("\n"), gcode=r["gcode"])


@app.post("/api/send")
def send():
    p = request.json or {}
    if not win32print:
        return jsonify(ok=False, error="pywin32 fehlt oder kein Windows – senden nicht möglich."), 400
    printer = p.get("printer")
    if printer not in list_printers():
        return jsonify(ok=False, error="Drucker nicht gefunden."), 400
    r = build(p)
    if r["mode"] != "outline" and not r["has_work"]:
        return jsonify(ok=False, error="Nichts zu gravieren."), 400
    try:
        send_raw(printer, r["gcode"])
    except Exception as e:  # Spooler-Fehler an die Oberfläche geben
        return jsonify(ok=False, error=str(e)), 500
    return jsonify(ok=True, minutes=r["minutes"])


@app.post("/api/upload/<kind>")
def upload(kind):
    if kind not in ASSETS:
        return jsonify(ok=False, error="Unbekannter Typ."), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(ok=False, error="Keine Datei."), 400
    try:
        strokes, notes = importer.load(f.filename, f.read())
    except importer.ImportFailed as e:
        return jsonify(ok=False, error=str(e)), 400
    if kind == "plate":
        closed = [s for s in strokes if is_closed(s)]
        if not closed:
            return jsonify(ok=False, error="Keine geschlossene Kontur gefunden – der Werkstückumriss "
                                           "muss eine geschlossene Linie sein."), 400
        if len(closed) < len(strokes):
            notes.append(f"{len(strokes) - len(closed)} offene Linien ignoriert.")
        strokes = closed
    x0, y0, x1, y1 = bbox_of(strokes)
    strokes = transform(strokes, 1, -x0, -y0)  # linke untere Ecke -> 0/0
    save_json(f"{kind}.json", {"name": f.filename, "strokes": rnd(strokes), "notes": notes})
    return jsonify(ok=True, name=f.filename, size=(round(x1 - x0, 2), round(y1 - y0, 2)), notes=notes)


@app.delete("/api/upload/<kind>")
def remove_upload(kind):
    if kind in ASSETS:
        (DATA / f"{kind}.json").unlink(missing_ok=True)
    return jsonify(ok=True)


@app.post("/api/presets")
def add_preset():
    p = request.json or {}
    name = re.sub(r"\s+", " ", str(p.get("name", ""))).strip()[:60]
    if not name:
        return jsonify(ok=False, error="Name fehlt."), 400
    if any(x["name"] == name for x in DEFAULT_PRESETS):
        return jsonify(ok=False, error="Name ist schon vergeben."), 400
    own = [x for x in load_json("presets.json", []) if x["name"] != name]
    own.append({"name": name, "w": num(p, "w", 70, 5, 1000), "h": num(p, "h", 50, 5, 1000),
                "r": num(p, "r", 3, 0, 500)})
    save_json("presets.json", own)
    return jsonify(ok=True, presets=presets())


@app.delete("/api/presets")
def del_preset():
    name = request.args.get("name", "")
    save_json("presets.json", [x for x in load_json("presets.json", []) if x["name"] != name])
    return jsonify(ok=True, presets=presets())


if __name__ == "__main__":
    if not win32print:
        print("Hinweis: pywin32 nicht gefunden – Vorschau geht, Senden nicht.", file=sys.stderr)
    print("SRM-20 Gravur läuft auf http://localhost:5000")
    app.run(host="0.0.0.0", port=5000)
