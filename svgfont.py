"""
SVG-Schriften (<font>/<glyph d="...">) als Single-Line-Schrift lesen.

Glyphen liegen in Schrift-Einheiten (meist 1000 pro Geviert), y nach oben, Grundlinie bei y = 0.
Kurven (Bézier, Bögen) werden fein in Geraden zerlegt; Kerning-Paare (<hkern>) werden berücksichtigt.
"""
import math
import xml.etree.ElementTree as ET

from svgelements import Close, Line, Move, Path

NS = "{http://www.w3.org/2000/svg}"
STEP = 6.0  # Schrift-Einheiten pro Geradenstück auf Kurven (bei 10 mm Versalhöhe ~0,09 mm)


class SvgFont:
    def __init__(self, path):
        root = ET.parse(path).getroot()
        font = root.find(f".//{NS}font")
        if font is None:
            raise ValueError(f"{path}: keine <font> gefunden")
        self.default_adv = float(font.get("horiz-adv-x", 500))
        self.glyphs = {}   # Zeichen -> (d, Vorschub)
        names = {}         # glyph-name -> Zeichen
        for g in font.iter(f"{NS}glyph"):
            u = g.get("unicode")
            if not u or len(u) != 1:  # Ligaturen u. ä. auslassen
                continue
            self.glyphs[u] = (g.get("d") or "", float(g.get("horiz-adv-x", self.default_adv)))
            if g.get("glyph-name"):
                names[g.get("glyph-name")] = u

        self.kern = {}
        for k in font.iter(f"{NS}hkern"):
            left = self._chars(k.get("u1"), k.get("g1"), names)
            right = self._chars(k.get("u2"), k.get("g2"), names)
            val = float(k.get("k", 0))
            for a in left:
                for b in right:
                    self.kern[(a, b)] = val

        self._cache = {}
        ys = [y for s in self.strokes("H") for _, y in s]
        self.cap = (max(ys) - min(ys)) if ys else 700.0

    @staticmethod
    def _chars(ulist, glist, names):
        out = set()
        if ulist:
            out |= {ulist} if ulist == "," else {u for u in ulist.split(",") if len(u) == 1}
        if glist:
            out |= {names[g] for g in glist.split(",") if g in names}
        return out

    def has(self, ch):
        return ch in self.glyphs

    def advance(self, ch):
        return self.glyphs[ch][1] if ch in self.glyphs else self.default_adv

    def kerning(self, a, b):
        return self.kern.get((a, b), 0.0)

    def strokes(self, ch):
        """Polylinien eines Zeichens in Schrift-Einheiten."""
        if ch not in self._cache:
            d = self.glyphs.get(ch, ("", 0))[0]
            self._cache[ch] = _flatten(d) if d.strip() else []
        return self._cache[ch]


def _flatten(d):
    out, cur = [], []
    for seg in Path(d):
        if isinstance(seg, Move):
            if len(cur) >= 2:
                out.append(cur)
            cur = [(seg.end.x, seg.end.y)]
            continue
        if seg.end is None:
            continue
        if not cur and seg.start is not None:
            cur = [(seg.start.x, seg.start.y)]
        if isinstance(seg, (Line, Close)):
            cur.append((seg.end.x, seg.end.y))
        else:
            n = max(4, int(math.ceil(seg.length(error=1e-3) / STEP)))
            cur += [(p.x, p.y) for p in (seg.point(i / n) for i in range(1, n + 1))]
    if len(cur) >= 2:
        out.append(cur)
    # doppelte Punkte entfernen
    clean = []
    for s in out:
        c = [s[0]]
        for p in s[1:]:
            if math.dist(p, c[-1]) > 1e-6:
                c.append(p)
        if len(c) >= 2:
            clean.append(c)
    return clean
