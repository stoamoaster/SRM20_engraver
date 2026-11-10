"""
SRM-20 Gravur – Rechenkern: Text setzen, Geometrie, Schild aufbauen, G-Code erzeugen.

Dieses Modul kennt weder HTTP noch Drucker noch Dateien im Ordner data/.
Einstieg ist build(params, logo, contour): params kommt fertig geprüft aus params.parse().
Nullpunkt: X/Y = linke untere Ecke des Werkstücks, Z = Oberseite des Werkstücks.
"""
import math
from pathlib import Path

from HersheyFonts import HersheyFonts

BASE = Path(__file__).resolve().parent

# Arbeitsbereich SRM-20 (X x Y in mm)
WORK_X, WORK_Y = 203.2, 152.4
MAX_CHARS = 200
EDGE_MIN = 0.5  # mm – näher am Werkstückrand gibt es eine Warnung

FONT_DIR = BASE / "fonts"
# Schlüssel -> (Anzeigename, Art, Datei bzw. Hershey-Name)
# SVG-Schriften: fein gezeichnete Single-Line-Schriften (siehe fonts/LIZENZEN.md)
# Hershey: alte Plotter-Schriften auf grobem Raster (~0,5 mm bei 10 mm Höhe), werden geglättet
FONT_DEFS = {
    "relief":      ("Relief SingleLine (empfohlen)", "svg", "ReliefSingleLine.svg"),
    "readability": ("EMS Readability (schlicht)", "svg", "EMSReadability.svg"),
    "tech":        ("EMS Tech (technisch, Handschrift)", "svg", "EMSTech.svg"),
    "osmotron":    ("EMS Osmotron (rund, geometrisch)", "svg", "EMSOsmotron.svg"),
    "allure":      ("EMS Allure (Schreibschrift)", "svg", "EMSAllure.svg"),
    "futural":     ("Hershey Futura leicht", "hershey", "futural"),
    "futuram":     ("Hershey Futura mittel (doppelte Linie)", "hershey", "futuram"),
    "rowmans":     ("Hershey Roman einfach", "hershey", "rowmans"),
    "rowmand":     ("Hershey Roman doppelt", "hershey", "rowmand"),
    "scripts":     ("Hershey Schreibschrift", "hershey", "scripts"),
    "timesr":      ("Hershey Times", "hershey", "timesr"),
}
DEFAULT_FONT = "relief"
FONTS = {k: v[0] for k, v in FONT_DEFS.items()
         if v[1] == "hershey" or (FONT_DIR / v[2]).exists()}

# Fehlen Umlaute in der Schrift -> Grundbuchstabe + zwei Punkte
UMLAUTS = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}

_font_cache = {}


# ---------------------------------------------------------------- Text

def font_key(name):
    return name if name in FONTS else (DEFAULT_FONT if DEFAULT_FONT in FONTS else "futural")


def get_font(name):
    """Hershey: (font, versalhöhe, grundlinie). SVG: SvgFont-Objekt."""
    name = font_key(name)
    if name not in _font_cache:
        kind, src = FONT_DEFS[name][1:]
        if kind == "svg":
            import svgfont
            _font_cache[name] = svgfont.SvgFont(FONT_DIR / src)
        else:
            f = HersheyFonts()
            f.load_default_font(src)
            f.normalize_rendering(100)
            # Großbuchstabenhöhe messen, damit "Höhe" = echte Höhe von H
            ys = [p[1] for s in f.strokes_for_text("H") for p in s]
            _font_cache[name] = (f, max(ys) - min(ys), min(ys))
    return _font_cache[name]


def is_svg_font(name):
    return FONT_DEFS[font_key(name)][1] == "svg"


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


def _umlaut_marks(glyph_pts, cap):
    """Zwei kurze Striche über einem Buchstaben (für Schriften ohne Umlaute)."""
    xs = [p[0] for p in glyph_pts]
    top = max(p[1] for p in glyph_pts)
    cx = (min(xs) + max(xs)) / 2
    gap, d = cap * 0.13, cap * 0.035  # kleine Striche statt Punkte -> sauberer Einstich
    return [[(cx + dx - d, top + gap), (cx + dx + d, top + gap)] for dx in (-cap * 0.13, cap * 0.13)]


def _svg_line(font, line, k, width=1.0, spacing=0.0):
    """Eine Zeile mit einer SVG-Schrift setzen (mm, Grundlinie y=0).
    width = waagrechte Streckung (1 = normal), spacing = zusätzlicher Zeichenabstand in mm.
    Liefert eine Liste von Zeichen-Gruppen [Striche], nach Schrift-Metrik + Kerning positioniert;
    Leerzeichen sind leere Gruppen."""
    groups, x, prev = [], 0.0, None   # x in Schrift-Einheiten (bereits gestreckt)
    extra = spacing / k

    def put(c):
        return [[(x + px * width, py) for px, py in s] for s in font.strokes(c)]

    for ch in line:
        use, marks = ch, False
        if not font.has(ch):
            if ch in UMLAUTS and font.has(UMLAUTS[ch]):
                use, marks = UMLAUTS[ch], True
            elif ch == "ß" and font.has("s"):
                for c in "ss":  # Notlösung
                    groups.append(put(c))
                    x += font.advance(c) * width + extra
                prev = "s"
                continue
        if prev is not None:
            x -= font.kerning(prev, use) * width
        glyph = put(use)
        if marks and glyph:
            glyph += _umlaut_marks([p for s in glyph for p in s], font.cap)
        groups.append(glyph)
        x += font.advance(use) * width + extra
        prev = use
    return [[simplify([(px * k, py * k) for px, py in s]) for s in g] for g in groups]


def _hershey_line(font, cap, base, line, k, width=1.0, spacing=0.0, smooth=True):
    """Eine Zeile mit einer Hershey-Schrift setzen -> Zeichen-Gruppen wie _svg_line."""
    plain = "".join(UMLAUTS.get(c, c) for c in line)
    # Striche pro Zeichen zählen, um die Zeichen auseinanderzuhalten (und Umlaut-Punkte zu setzen)
    all_strokes = [list(s) for s in font.strokes_for_text(plain)]
    groups, idx = [], 0
    for j, (orig, ch) in enumerate(zip(line, plain)):
        n = sum(1 for _ in font.strokes_for_text(ch))
        glyph = all_strokes[idx: idx + n]
        idx += n
        pts = [p for s in glyph for p in s]
        if orig in UMLAUTS and pts:
            glyph += _umlaut_marks(pts, cap)
        shift = j * spacing / (k * width)  # Zeichenabstand in Schrift-Einheiten
        g = [[((x + shift) * k * width, (y - base) * k) for x, y in s] for s in glyph if len(s) >= 2]
        groups.append([smooth_stroke(s) for s in g] if smooth else g)
    return groups


# ---- optischer Zeichenabstand (Prinzip wie HT Letterspacer) ----
OPT_BANDS = 30        # Anzahl waagrechter Streifen
OPT_ZONE = (-0.35, 1.35)  # Streifen-Bereich in Vielfachen der Versalhöhe (Unterlängen bis Akzente)
OPT_DEPTH = 0.22      # tiefere Einbuchtungen (z. B. beim T, L, r) zählen nur bis zu dieser Tiefe (× Höhe)
OPT_MIN_GAP = 0.35    # engster Abstand mindestens dieser Anteil der Ziel-Lücke
OPT_WORD = 0.18       # Wortabstand (× Höhe × Breite), zusätzlich zur Ziel-Lücke
OPT_TRACKING = 35     # Standard-Laufweite in % der Höhe (≈ gleiche Textbreite wie die Schrift-Metrik)


def _profile(strokes, y0, y1, n):
    """Pro Streifen: linkester und rechtester Tintenpunkt (None = Streifen leer)."""
    h = (y1 - y0) / n
    L, R = [math.inf] * n, [-math.inf] * n
    for s in strokes:
        for (ax, ay), (bx, by) in zip(s, s[1:]):
            lo, hi = min(ay, by), max(ay, by)
            if hi < y0 or lo > y1:
                continue
            i0 = max(0, int((lo - y0) / h))
            i1 = min(n - 1, int((hi - y0) / h))
            for i in range(i0, i1 + 1):
                ya, yb = y0 + i * h, y0 + (i + 1) * h
                if ay == by:
                    xa, xb = ax, bx
                else:
                    t0, t1 = sorted(((ya - ay) / (by - ay), (yb - ay) / (by - ay)))
                    t0, t1 = max(0.0, t0), min(1.0, t1)
                    if t0 > t1:
                        continue
                    xa, xb = ax + (bx - ax) * t0, ax + (bx - ax) * t1
                L[i] = min(L[i], xa, xb)
                R[i] = max(R[i], xa, xb)
    return L, R


def _optical_offset(RA, LB, gap, depth, min_gap):
    """Versatz von Zeichen B gegenüber A (beide im eigenen Koordinatensystem), sodass
    ½·engste Lücke + ½·mittlere Lücke = gap."""
    maxR = max((r for r in RA if r > -math.inf), default=None)
    minL = min((l for l in LB if l < math.inf), default=None)
    if maxR is None or minL is None:
        return gap
    c = []
    for ra, lb in zip(RA, LB):
        if ra == -math.inf and lb == math.inf:
            continue  # Streifen bei beiden leer -> zählt nicht
        ra = maxR - depth if ra == -math.inf else max(ra, maxR - depth)
        lb = minL + depth if lb == math.inf else min(lb, minL + depth)
        c.append(lb - ra)
    if not c:
        return gap - (minL - maxR)
    d = gap - 0.5 * (min(c) + sum(c) / len(c))
    return max(d, min_gap - min(c))  # nie enger als min_gap (keine Berührung)


def _optical_layout(groups, height, width, tracking, spacing):
    """Setzt die Zeichen-Gruppen einer Zeile mit optisch gleichmäßigen Abständen neu."""
    gap = tracking / 100 * height
    depth, min_gap = OPT_DEPTH * height, OPT_MIN_GAP * gap
    y0, y1 = OPT_ZONE[0] * height, OPT_ZONE[1] * height
    out, prev, x, pending = [], None, 0.0, 0.0  # prev = (Profil R, Versatz)
    for g in groups:
        if not g:  # Leerzeichen
            pending += OPT_WORD * height * width + gap + spacing
            continue
        bb = bbox_of(g)
        g = [[(px - bb[0], py) for px, py in s] for s in g]  # Tinte beginnt bei x = 0
        L, R = _profile(g, y0, y1, OPT_BANDS)
        if prev is None:
            x = 0.0
        else:
            x = prev[1] + _optical_offset(prev[0], L, gap, depth, min_gap) + spacing + pending
        pending = 0.0
        out += [[(px + x, py) for px, py in s] for s in g]
        prev = (R, x)
    return out


def text_to_strokes(text, height, font_name, line_spacing=1.6, align="center", smooth=True,
                    width=1.0, spacing=0.0, optical=False, tracking=OPT_TRACKING):
    """Liefert eine Liste von Polylinien [(x,y), ...] in mm. Grundlinie der 1. Zeile bei y=0.
    width: Schriftbreite (1 = normal), spacing: zusätzlicher Zeichenabstand in mm.
    optical: Abstände nach Form der Buchstaben statt nach Schrift-Metrik; tracking = Lücke in % der Höhe."""
    if is_svg_font(font_name):
        font = get_font(font_name)
        k = height / font.cap
        make = lambda line: _svg_line(font, line, k, width, 0.0 if optical else spacing)
        lines = text.split("\n")
    else:
        font, cap, base = get_font(font_name)
        k = height / cap
        make = lambda line: _hershey_line(font, cap, base, line, k, width, 0.0 if optical else spacing, smooth)
        lines = text.replace("ß", "ss").split("\n")

    lines_out = []
    for li, line in enumerate(lines):
        groups = make(line)
        if optical:
            strokes = _optical_layout(groups, height, width, tracking, spacing)
        else:
            strokes = [s for g in groups for s in g]
        y_off = -li * height * line_spacing
        lines_out.append([[(x, y + y_off) for x, y in s] for s in strokes])
    return _align_lines(lines_out, align)


def _align_lines(lines_out, align):
    """Zeilen zueinander ausrichten (links/mittig/rechts)."""
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
    if is_svg_font(font):
        f = get_font(font)
        return sorted({c for c in text if c not in "\n " and not f.has(c)
                       and not (c in UMLAUTS and f.has(UMLAUTS[c])) and not (c == "ß" and f.has("s"))})
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
# VIEW-/Parkposition in WERKSTÜCKkoordinaten (gewähltes System, z. B. G54),
# an der SRM-20 gemessen: dort steht die Fräse nach Drücken der VIEW-Taste
PARK_X, PARK_Y, PARK_Z = 33.7, 121.8, 57.5


def make_gcode(jobs, safe_z, feed, plunge, rpm, passes, wcs="G54", park=None):
    """jobs: Liste von (strokes, tiefe). Tiefe < 0 = über der Oberfläche (Luftschnitt).

    park: None = am Ende zum Werkstück-Nullpunkt (X0 Y0) fahren.
    (x, y, z) = Parkposition im Werkstück-Koordinatensystem: erst Z hoch, dann X/Y.

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
    if park:
        g += ["M05",
              f"G00 Z{max(park[2], safe_z):.3f}",       # zuerst nur Z nach oben
              f"G00 X{park[0]:.3f} Y{park[1]:.3f}",      # dann X/Y in die VIEW-/Parkposition
              "%"]
    else:
        g += ["M05", "G00 X0.000 Y0.000", "%"]
    # grobe Zeitschätzung (Eilgang ~ 1800 mm/min)
    minutes = cut_len / feed + travel / 1800 + plunges * (2 * safe_z + 0.5) / plunge
    return "\n".join(g) + "\n", minutes


# ---------------------------------------------------------------- Aufbau des Schilds

# Warnungen mit diesen Codes verhindern den Start über die API (außer mit "force": true)
BLOCKING = ("outside", "plate_too_large")


def rnd(strokes):
    return [[(round(x, 3), round(y, 3)) for x, y in s] for s in strokes]


def build(p, logo=None, contour=None):
    """Baut das Schild aus geprüften Parametern (siehe params.parse).

    logo:    Linien des Logos oder None (kein Logo)
    contour: geschlossene Linien des Werkstück-Umrisses (linke untere Ecke bei 0/0)
             oder None (Platte mit runden Ecken aus plate_w / plate_h / plate_r)
    """
    text, font, mode = p["text"], font_key(p["font"]), p["mode"]
    height, depth, safe_z = p["height"], p["depth"], p["safe_z"]
    side, bottom = p["margin_side"], p["text_bottom"]
    park = (p["park_x"], p["park_y"], p["park_z"]) if p["park"] else None
    warnings = []

    def warn(code, message):
        warnings.append({"code": code, "message": message})

    # --- Werkstück
    if contour:
        plate_strokes = contour
        _, _, pw, ph = bbox_of(plate_strokes)  # beim Import auf 0/0 verschoben
        plate = {"kind": "file", "strokes": plate_strokes, "w": pw, "h": ph}
    else:
        pw, ph, pr = p["plate_w"], p["plate_h"], p["plate_r"]
        plate_strokes = rounded_rect(pw, ph, pr)
        plate = {"kind": "rect", "w": pw, "h": ph, "r": pr}
    if pw > WORK_X or ph > WORK_Y:
        warn("plate_too_large", f"Werkstück ({pw:.0f} × {ph:.0f} mm) ist größer als der Arbeitsbereich "
                                f"der SRM-20 ({WORK_X:.0f} × {WORK_Y:.0f} mm).")

    # --- Text: zentriert, Unterkante "bottom" mm über der Werkstückkante
    style = dict(align=p["align"], smooth=p["smooth"], width=p["width_pct"] / 100,
                 spacing=p["letter_spacing"], optical=p["spacing_mode"] != "font",
                 tracking=p["tracking"])
    text_s = text_to_strokes(text, height, font, **style) if text.strip() else []
    tb = bbox_of(text_s)
    real_h = height
    if tb and p["autoshrink"]:
        avail = pw - 2 * side
        prev = None
        for _ in range(6):  # Breite = a·Höhe + fester Zeichenabstand -> nach 2 Schritten exakt
            tw = tb[2] - tb[0]
            if not tw > avail + 0.01 or avail <= 0:
                break
            if prev and prev[1] != tw:
                new_h = real_h + (avail - tw) * (real_h - prev[0]) / (tw - prev[1])
            else:
                new_h = real_h * avail / tw
            prev = (real_h, tw)
            real_h = max(0.5, new_h * 0.999)
            text_s = text_to_strokes(text, real_h, font, **style)
            tb = bbox_of(text_s)
        if real_h < height:
            warn("text_shrunk", f"Text zu breit – Schrifthöhe automatisch auf {real_h:.1f} mm verkleinert.")
    if tb:
        text_s = transform(text_s, 1, pw / 2 - (tb[0] + tb[2]) / 2, bottom - tb[1])
        tb = bbox_of(text_s)
    miss = missing_chars(text, font)
    if miss:
        warn("missing_chars", "Nicht in der Schrift enthalten (wird ausgelassen): " + " ".join(miss))

    # --- Logo: in den freien Bereich über dem Text eingepasst
    logo_s, logo_area = [], None
    if logo:
        y_lo = tb[3] + p["logo_gap"] if tb else bottom
        area = (side, y_lo, pw - side, ph - p["margin_top"])
        aw, ah = area[2] - area[0], area[3] - area[1]
        lb = bbox_of(logo)
        if aw > 1 and ah > 1:
            lw, lh = max(lb[2] - lb[0], 1e-6), max(lb[3] - lb[1], 1e-6)
            k = min(aw / lw, ah / lh) * p["logo_scale"] / 100
            cx = (area[0] + area[2]) / 2 + p["logo_dx"]
            cy = (area[1] + area[3]) / 2 + p["logo_dy"]
            logo_s = transform(logo, k, cx - (lb[0] + lb[2]) / 2 * k, cy - (lb[1] + lb[3]) / 2 * k)
            if p["logo_fill"]:
                fill = hatch(logo_s, p["fill_step"])
                if not fill:
                    warn("logo_no_fill", "Logo hat keine geschlossenen Flächen – Füllen nicht möglich.")
                logo_s += fill
        else:
            warn("logo_no_space", "Kein Platz für das Logo – Text kleiner machen oder Ränder verringern.")
        logo_area = area

    # --- Randprüfung
    pts = [pt for s in text_s + logo_s for pt in s]
    if pts:
        worst = min(edge_distance(pt, plate) for pt in pts)
        if worst < 0:
            warn("outside", "Achtung: Teile der Gravur liegen AUSSERHALB des Werkstücks!")
        elif worst < EDGE_MIN:
            warn("near_edge", f"Gravur liegt nur {worst:.2f} mm vom Werkstückrand entfernt.")

    # --- G-Code
    cut = (p["feed"], p["plunge"], p["rpm"])
    text_o = optimize_order(text_s)
    logo_o = optimize_order(logo_s, text_o[-1][-1] if text_o else (0.0, 0.0))
    if mode == "air":  # Luftschnitt: Fräser fährt 1 mm ÜBER der Oberfläche
        gcode, minutes = make_gcode([(text_o, -1.0), (logo_o, -1.0)], max(safe_z, 3), *cut, 1, p["wcs"], park)
    elif mode == "outline":  # nur Werkstückumriss 1 mm über der Oberfläche abfahren
        gcode, minutes = make_gcode([(plate_strokes, -1.0)], max(safe_z, 3), *cut, 1, p["wcs"], park)
    else:
        gcode, minutes = make_gcode([(text_o, depth), (logo_o, p["logo_depth"])], safe_z, *cut,
                                    p["passes"], p["wcs"], park)

    has_work = bool(text_s or logo_s)
    blocking = [w["code"] for w in warnings
                if w["code"] in BLOCKING and not (mode == "outline" and w["code"] == "outside")]
    return dict(text=text_s, logo=logo_s, plate=plate_strokes, plate_size=(pw, ph), logo_area=logo_area,
                text_height=real_h if tb else None, text_bbox=tb, gcode=gcode, minutes=minutes,
                warnings=warnings, blocking=blocking, has_work=has_work,
                startable=mode == "outline" or has_work, mode=mode)
