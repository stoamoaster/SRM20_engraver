"""
Import von Konturen aus SVG, DXF und DWG -> Liste von Polylinien [(x, y), ...] in mm.

DXF:  direkt über ezdxf (Linien, Bögen, Kreise, Polylinien, Splines, Ellipsen, Blöcke, Schraffur-Ränder)
DWG:  braucht den kostenlosen "ODA File Converter" (wird von ezdxf automatisch benutzt),
      sonst im CAD-Programm als DXF speichern.
SVG:  über svgelements (Pfade, Rechtecke, Kreise, Polygone, Transformationen)
Texte in DXF/SVG werden nicht übernommen -> im Programm vorher in Kurven/Pfade umwandeln.
"""
import io
import math
import os
import tempfile
from collections import Counter

TOL = 0.02  # mm – maximale Abweichung beim Annähern von Bögen durch Geraden

# DXF $INSUNITS -> Faktor nach mm (0 = ohne Einheit -> als mm behandeln)
DXF_UNITS = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 9: 0.0254, 10: 914.4, 13: 0.001, 14: 100.0}


class ImportFailed(Exception):
    pass


def load(filename, data):
    """Liest eine Datei und liefert (strokes, hinweise)."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext == ".svg":
        strokes, skipped = _svg(data)
    elif ext in (".dxf", ".dwg"):
        strokes, skipped = _cad(data, ext)
    else:
        raise ImportFailed("File type not supported – please use SVG, DXF or DWG.")

    strokes = [s for s in (_dedupe(s) for s in strokes) if len(s) >= 2]
    if not strokes:
        raise ImportFailed("No usable lines found in the file.")
    notes = []
    if skipped:
        notes.append("Not imported: " + ", ".join(f"{n}× {t}" for t, n in skipped.most_common())
                     + " (convert text to curves/paths first)")
    return strokes, notes


def _dedupe(pts):
    out = []
    for p in pts:
        p = (round(float(p[0]), 4), round(float(p[1]), 4))
        if not out or math.dist(out[-1], p) > 1e-4:
            out.append(p)
    return out


# ------------------------------------------------------------------ DXF / DWG

def _cad(data, ext):
    try:
        import ezdxf
        from ezdxf import path as ezpath
        from ezdxf import recover
        from ezdxf.disassemble import recursive_decompose
    except ImportError:
        raise ImportFailed("Package 'ezdxf' missing – run start.bat again.")

    fd, tmp = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if ext == ".dwg":
            from ezdxf.addons import odafc
            if not odafc.is_installed():
                raise ImportFailed(
                    "DWG files need the free \"ODA File Converter\" "
                    "(opendesign.com → Guest Files). Easier: save as DXF in your CAD program.")
            doc = odafc.readfile(tmp)
        else:
            doc, _auditor = recover.readfile(tmp)
    except ImportFailed:
        raise
    except Exception as e:
        raise ImportFailed(f"File could not be read: {e}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    k = DXF_UNITS.get(int(doc.header.get("$INSUNITS", 0) or 0), 1.0)
    hidden = {l.dxf.name.lower() for l in doc.layers if l.is_off() or l.is_frozen()}

    strokes, skipped = [], Counter()
    for e in recursive_decompose(doc.modelspace()):
        t = e.dxftype()
        if e.dxf.get("layer", "0").lower() in hidden:
            continue
        if t in ("POINT", "VIEWPORT", "IMAGE", "WIPEOUT"):
            continue
        try:
            p = ezpath.make_path(e)
        except Exception:
            skipped[t] += 1
            continue
        subs = p.sub_paths() if p.has_sub_paths else [p]
        for sub in subs:
            pts = [(v.x * k, v.y * k) for v in sub.flattening(TOL / k)]
            if len(pts) >= 2:
                strokes.append(pts)
    return strokes, skipped


# ------------------------------------------------------------------ SVG

def _svg(data):
    try:
        from svgelements import SVG, Close, Line, Move, Shape
    except ImportError:
        raise ImportFailed("Package 'svgelements' missing – run start.bat again.")
    try:
        svg = SVG.parse(io.BytesIO(data), reify=True)
    except Exception as e:
        raise ImportFailed(f"SVG could not be read: {e}")

    k = 25.4 / 96  # svgelements rechnet in px (96 dpi)

    def mm(pt):
        return (pt.x * k, -pt.y * k)  # SVG: y nach unten -> umdrehen

    strokes, skipped = [], Counter()
    for el in svg.elements():
        if not isinstance(el, Shape):
            name = type(el).__name__
            if name in ("Text", "SVGText", "Image", "SVGImage"):
                skipped[name.replace("SVG", "")] += 1
            continue
        if el.values.get("visibility") in ("hidden", "collapse") or el.values.get("display") == "none":
            continue
        cur = []
        for seg in el.segments():
            if isinstance(seg, Move):
                if len(cur) >= 2:
                    strokes.append(cur)
                cur = [mm(seg.end)] if seg.end is not None else []
                continue
            if seg.end is None:
                continue
            if not cur and seg.start is not None:
                cur = [mm(seg.start)]
            if isinstance(seg, (Line, Close)):
                cur.append(mm(seg.end))
            else:  # Bezier, Bogen
                length = seg.length(error=1e-4) * k
                n = max(8, min(400, int(length / 0.15) + 1))
                cur += [mm(seg.point(i / n)) for i in range(1, n + 1)]
        if len(cur) >= 2:
            strokes.append(cur)
    return strokes, skipped
