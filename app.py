"""
SRM-20 Gravur – Text eingeben, Vorschau ansehen, direkt an die Roland SRM-20 senden.

Start:  python app.py   ->  Browser: http://localhost:5000
Voraussetzung: Roland-Treiber installiert, SRM-20 in VPanel auf "NC-Code" gestellt,
               Nullpunkt (X/Y und Z auf Werkstückoberfläche) in VPanel gesetzt.
"""
import math
import sys

from flask import Flask, jsonify, request
from HersheyFonts import HersheyFonts

try:
    import win32print  # pywin32 – nur unter Windows verfügbar
except ImportError:
    win32print = None

# Arbeitsbereich SRM-20 (X x Y in mm)
WORK_X, WORK_Y = 203.2, 152.4
MAX_CHARS = 200

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


def text_to_strokes(text, height, font_name, line_spacing=1.6, align="left"):
    """Liefert eine Liste von Polylinien [(x,y), ...] in mm."""
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
        scaled = [[((x) * k, (y - base) * k + y_off) for x, y in s] for s in line_strokes if len(s) >= 2]
        lines_out.append(scaled)

    # Zeilen ausrichten
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


def place(strokes, anchor):
    """Verschiebt den Text relativ zum Nullpunkt."""
    pts = [p for s in strokes for p in s]
    if not pts:
        return strokes, (0, 0, 0, 0)
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    if anchor == "center":
        dx, dy = -(x0 + x1) / 2, -(y0 + y1) / 2
    else:  # links unten
        dx, dy = -x0, -y0
    moved = [[(x + dx, y + dy) for x, y in s] for s in strokes]
    return moved, (x0 + dx, y0 + dy, x1 + dx, y1 + dy)


def optimize_order(strokes):
    """Nächster-Nachbar-Sortierung, damit der Fräser nicht kreuz und quer fährt."""
    remaining = strokes[:]
    out, pos = [], (0.0, 0.0)
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


def make_gcode(strokes, depth, safe_z, feed, plunge, rpm, passes):
    g = ["%", "G90 G21 G17", f"M03 S{int(rpm)}", f"G00 Z{safe_z:.3f}"]
    cut_len = travel = 0.0
    pos = (0.0, 0.0)
    plunges = 0
    down = False
    for p_i in range(1, passes + 1):
        z = -depth * p_i / passes
        for s in strokes:
            x, y = s[0]
            # Schließt der Strich direkt an, bleibt der Fräser unten
            if not (down and math.dist(pos, (x, y)) < 0.01):
                if down:
                    g.append(f"G00 Z{safe_z:.3f}")
                g.append(f"G00 X{x:.3f} Y{y:.3f}")
                g.append(f"G01 Z{z:.3f} F{plunge:.0f}")
                travel += math.dist(pos, (x, y))
                plunges += 1
                down = True
            for i, ((ax, ay), (bx, by)) in enumerate(zip(s, s[1:])):
                g.append(f"G01 X{bx:.3f} Y{by:.3f}" + (f" F{feed:.0f}" if i == 0 else ""))
                cut_len += math.hypot(bx - ax, by - ay)
            pos = s[-1]
        g.append(f"G00 Z{safe_z:.3f}")
        down = False
    g += [f"G00 Z{safe_z:.3f}", "M05", "G00 X0 Y0", "%"]
    # grobe Zeitschätzung (Eilgang ~ 1800 mm/min)
    minutes = cut_len / feed + travel / 1800 + plunges * (2 * (safe_z + depth)) / plunge
    return "\n".join(g) + "\n", minutes


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


# ---------------------------------------------------------------- Web

app = Flask(__name__)


def build(params):
    text = str(params.get("text", ""))[:MAX_CHARS]
    height = max(0.5, float(params.get("height", 5)))
    depth = max(0.01, float(params.get("depth", 0.2)))
    safe_z = max(0.5, float(params.get("safe_z", 2)))
    feed = max(10, float(params.get("feed", 240)))
    plunge = max(5, float(params.get("plunge", 60)))
    rpm = max(3000, min(7000, float(params.get("rpm", 7000))))
    passes = max(1, min(10, int(params.get("passes", 1))))
    font = params.get("font", "futural")
    align = params.get("align", "left") if params.get("align") in ("left", "center", "right") else "left"
    anchor = params.get("anchor", "bottomleft")
    air = bool(params.get("air", False))

    strokes = text_to_strokes(text, height, font, align=align)
    strokes, bbox = place(strokes, anchor)
    strokes = optimize_order(strokes)
    if air:  # Luftschnitt: Fräser fährt 1 mm ÜBER der Oberfläche (Z+1)
        gcode, minutes = make_gcode(strokes, -1.0, max(safe_z, 3), feed, plunge, rpm, 1)
    else:
        gcode, minutes = make_gcode(strokes, depth, safe_z, feed, plunge, rpm, passes)

    warnings = []
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if w > WORK_X or h > WORK_Y:
        warnings.append(f"Text ({w:.1f} × {h:.1f} mm) ist größer als der Arbeitsbereich der SRM-20.")
    missing = sorted({c for c in text if c not in "\n ß" and c not in UMLAUTS
                      and not list(get_font(font)[0].strokes_for_text(c))})
    if missing:
        warnings.append("Nicht in der Schrift enthalten (wird ausgelassen): " + " ".join(missing))
    return dict(strokes=strokes, bbox=bbox, gcode=gcode, minutes=minutes, warnings=warnings, air=air)


@app.get("/")
def index():
    return PAGE


@app.get("/api/info")
def info():
    return jsonify(fonts=FONTS, printers=list_printers(), windows=bool(win32print))


@app.post("/api/preview")
def preview():
    r = build(request.json or {})
    return jsonify(strokes=r["strokes"], bbox=r["bbox"], minutes=r["minutes"],
                   warnings=r["warnings"], lines=r["gcode"].count("\n"), gcode=r["gcode"])


@app.post("/api/send")
def send():
    p = request.json or {}
    if not win32print:
        return jsonify(ok=False, error="pywin32 fehlt oder kein Windows – senden nicht möglich."), 400
    printer = p.get("printer")
    if printer not in list_printers():
        return jsonify(ok=False, error="Drucker nicht gefunden."), 400
    r = build(p)
    if not r["strokes"]:
        return jsonify(ok=False, error="Kein Text."), 400
    try:
        send_raw(printer, r["gcode"])
    except Exception as e:  # Spooler-Fehler an die Oberfläche geben
        return jsonify(ok=False, error=str(e)), 500
    return jsonify(ok=True, minutes=r["minutes"])


PAGE = r"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SRM-20 Gravur</title>
<style>
:root{--bg:#f4f3ef;--card:#fff;--ink:#1c1c1a;--mut:#6b6a64;--line:#dcdad3;--acc:#c2410c;--ok:#15803d;--warn:#b45309}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 system-ui,Segoe UI,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:baseline;gap:14px}
header h1{font-size:19px;margin:0}header span{color:var(--mut);font-size:13px}
main{display:grid;grid-template-columns:340px 1fr;gap:20px;padding:20px 24px;max-width:1300px}
@media(max-width:820px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
label{display:block;font-size:12px;color:var(--mut);margin:10px 0 3px;text-transform:uppercase;letter-spacing:.04em}
textarea,input,select{width:100%;padding:8px 10px;border:1px solid var(--line);border-radius:6px;font:inherit;background:#fff}
textarea{font-size:20px;min-height:90px;resize:vertical}
.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.chk{display:flex;gap:8px;align-items:center;margin-top:12px;font-size:14px}.chk input{width:auto}
button{font:inherit;border:0;border-radius:7px;padding:11px 14px;cursor:pointer}
.go{background:var(--acc);color:#fff;width:100%;font-weight:600;font-size:16px;margin-top:16px}
.go:disabled{opacity:.45;cursor:not-allowed}
.sec{background:transparent;border:1px solid var(--line);margin-top:8px;width:100%}
#svgwrap{background:#fbfaf7;border:1px solid var(--line);border-radius:8px;height:420px;position:relative}
svg{width:100%;height:100%}
.stats{display:flex;gap:22px;flex-wrap:wrap;margin:12px 0 4px;font-size:14px}.stats b{font-size:17px}
#warn{color:var(--warn);font-size:14px}#msg{margin-top:10px;font-size:14px}
details{margin-top:12px}pre{max-height:260px;overflow:auto;background:#1c1c1a;color:#e8e6df;padding:10px;border-radius:6px;font-size:12px}
.hint{font-size:12.5px;color:var(--mut);margin-top:12px;line-height:1.5}
</style></head><body>
<header><h1>SRM-20 Gravur</h1><span>Text → G-Code → Fräse</span></header>
<main>
<section class="card">
  <label>Text</label>
  <textarea id="text" placeholder="Text eingeben…">Hallo Welt</textarea>
  <label>Schrift</label><select id="font"></select>
  <div class="row">
    <div><label>Höhe (mm)</label><input id="height" type="number" value="5" step="0.5" min="0.5"></div>
    <div><label>Tiefe (mm)</label><input id="depth" type="number" value="0.2" step="0.05" min="0.01"></div>
  </div>
  <div class="row">
    <div><label>Ausrichtung</label><select id="align"><option value="left">Links</option><option value="center">Mitte</option><option value="right">Rechts</option></select></div>
    <div><label>Nullpunkt ist</label><select id="anchor"><option value="bottomleft">Links unten</option><option value="center">Textmitte</option></select></div>
  </div>
  <details><summary style="cursor:pointer;margin-top:12px">Fräsparameter</summary>
    <div class="row">
      <div><label>Vorschub (mm/min)</label><input id="feed" type="number" value="240"></div>
      <div><label>Eintauchen (mm/min)</label><input id="plunge" type="number" value="60"></div>
    </div>
    <div class="row">
      <div><label>Drehzahl (U/min)</label><input id="rpm" type="number" value="7000" max="7000"></div>
      <div><label>Sicherheits-Z (mm)</label><input id="safe_z" type="number" value="2" step="0.5"></div>
    </div>
    <label>Durchgänge</label><input id="passes" type="number" value="1" min="1" max="10">
  </details>
  <label class="chk"><input type="checkbox" id="air"> Luftschnitt (1 mm über Oberfläche, zum Testen)</label>
  <label>Fräse (Windows-Drucker)</label><select id="printer"></select>
  <button class="go" id="send">An Fräse senden</button>
  <button class="sec" id="dl">G-Code herunterladen (.nc)</button>
  <div id="msg"></div>
  <p class="hint">Vorher in VPanel: Befehlssatz <b>NC-Code</b>, X/Y-Nullpunkt und Z-Nullpunkt auf der Werkstückoberfläche setzen. Abbrechen über VPanel oder die VIEW-Taste an der Maschine.</p>
</section>
<section class="card">
  <div id="svgwrap"><svg id="svg"></svg></div>
  <div class="stats"><div>Größe <b id="size">–</b></div><div>Dauer ca. <b id="time">–</b></div><div>Zeilen <b id="lines">–</b></div></div>
  <div id="warn"></div>
  <details><summary style="cursor:pointer">G-Code ansehen</summary><pre id="code"></pre></details>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
const ids=["text","font","height","depth","align","anchor","feed","plunge","rpm","safe_z","passes","air"];
let last=null,timer=null;
function params(){const p={};ids.forEach(i=>{const e=$(i);p[i]=e.type==="checkbox"?e.checked:e.value});p.printer=$("printer").value;return p}
async function info(){
  const r=await (await fetch("/api/info")).json();
  $("font").innerHTML=Object.entries(r.fonts).map(([k,v])=>`<option value="${k}">${v}</option>`).join("");
  if(r.printers.length){$("printer").innerHTML=r.printers.map(n=>`<option>${n}</option>`).join("")}
  else{$("printer").innerHTML="<option value=''>keine Drucker gefunden</option>";$("send").disabled=true;
    if(!r.windows)$("msg").textContent="Senden nur unter Windows mit pywin32 möglich – Vorschau und Download funktionieren."}
  update();
}
function schedule(){clearTimeout(timer);timer=setTimeout(update,200)}
async function update(){
  const r=await (await fetch("/api/preview",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(params())})).json();
  last=r;draw(r);
  const [x0,y0,x1,y1]=r.bbox;
  $("size").textContent=r.strokes.length?`${(x1-x0).toFixed(1)} × ${(y1-y0).toFixed(1)} mm`:"–";
  const s=Math.round(r.minutes*60);$("time").textContent=r.strokes.length?(s<60?s+" s":Math.floor(s/60)+" min "+(s%60)+" s"):"–";
  $("lines").textContent=r.lines;$("code").textContent=r.gcode;
  $("warn").innerHTML=r.warnings.map(w=>"⚠ "+w).join("<br>");
}
function draw(r){
  const svg=$("svg");const [x0,y0,x1,y1]=r.bbox;
  const w=Math.max(x1-x0,1),h=Math.max(y1-y0,1),m=Math.max(w,h)*0.12+2;
  const vx=Math.min(x0,0)-m,vy=-Math.max(y1,0)-m,vw=Math.max(x1,0)-Math.min(x0,0)+2*m,vh=Math.max(y1,0)-Math.min(y0,0)+2*m;
  svg.setAttribute("viewBox",`${vx} ${vy} ${vw} ${vh}`);
  const sw=Math.max(vw,vh)/300,tool=Math.max(+$("height").value*0.06,sw);
  let out=`<line x1="${vx}" y1="0" x2="${vx+vw}" y2="0" stroke="#c9c6bd" stroke-width="${sw}"/>
  <line x1="0" y1="${vy}" x2="0" y2="${vy+vh}" stroke="#c9c6bd" stroke-width="${sw}"/>
  <circle cx="0" cy="0" r="${sw*3}" fill="#c2410c"/>`;
  out+=`<g fill="none" stroke="#1c1c1a" stroke-width="${tool}" stroke-linecap="round" stroke-linejoin="round">`;
  for(const s of r.strokes)out+=`<polyline points="${s.map(p=>p[0]+","+(-p[1])).join(" ")}"/>`;
  svg.innerHTML=out+"</g>";
}
ids.forEach(i=>{$(i).addEventListener("input",schedule);$(i).addEventListener("change",schedule)});
$("dl").onclick=()=>{if(!last)return;const a=document.createElement("a");
  a.href=URL.createObjectURL(new Blob([last.gcode],{type:"text/plain"}));a.download="gravur.nc";a.click()};
$("send").onclick=async()=>{
  const p=params();if(!p.text.trim())return;
  const what=p.air?"LUFTSCHNITT":"GRAVUR";
  if(!confirm(`${what} starten?\n\n"${p.text}"\nTiefe: ${p.air?"+1 mm (Luft)":p.depth+" mm"}\n\nNullpunkt gesetzt? NC-Code-Modus aktiv?`))return;
  $("send").disabled=true;$("msg").textContent="Sende…";
  const r=await (await fetch("/api/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(p)})).json();
  $("msg").innerHTML=r.ok?`<span style="color:var(--ok)">✓ An Fräse gesendet.</span>`:`<span style="color:var(--acc)">Fehler: ${r.error}</span>`;
  setTimeout(()=>$("send").disabled=false,3000);
};
info();
</script></body></html>"""


if __name__ == "__main__":
    if not win32print:
        print("Hinweis: pywin32 nicht gefunden – Vorschau geht, Senden nicht.", file=sys.stderr)
    print("SRM-20 Gravur läuft auf http://localhost:5000")
    app.run(host="0.0.0.0", port=5000)
