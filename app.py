"""
SRM-20 Gravur – Webserver: Weboberfläche und HTTP-API (JSON).

Start:  start.bat   (oder: python app.py)  ->  Browser: http://localhost:5000
Voraussetzung: Roland-Treiber installiert, SRM-20 in VPanel auf "NC-Code" gestellt.

API für andere Programme: /api/v1/…  (Beschreibung in API.md)
Die Weboberfläche benutzt die älteren Endpunkte /api/info, /api/preview, /api/send, /api/upload, /api/presets.

Einstellungen über Umgebungsvariablen:
  SRM20_HOST      Netzwerkadresse (Standard 0.0.0.0 = alle Netzwerkkarten)
  SRM20_PORT      Port (Standard 5000)
  SRM20_API_KEY   wenn gesetzt: Zugriffe von anderen Rechnern brauchen den Header X-API-Key
  SRM20_PRINTER   Druckername der Fräse, falls er nicht „SRM“ enthält
  SRM20_SIMULATE  1 = nichts senden, G-Code nach data/simulated/ schreiben
  SRM20_CORS      erlaubte Herkunft für Browser-Apps, z. B. http://localhost:3000 (oder *)
"""
import hmac
import ipaddress
import os
import re
import sys

from flask import Flask, Response, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

import engraving as E
import jobs
import machine
import params as P
import store

API_VERSION = "1.0"
API_KEY = os.environ.get("SRM20_API_KEY", "")
CORS = os.environ.get("SRM20_CORS", "")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024
app.json.sort_keys = False
app.json.ensure_ascii = False  # Umlaute lesbar statt ä


# ---------------------------------------------------------------- Gemeinsames

class ApiError(Exception):
    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def fail(status, code, message, **extra):
    """Fehlerantwort der API v1: {"ok": false, "error": {"code": …, "message": …, …}}"""
    return jsonify(ok=False, error={"code": code, "message": message, **extra}), status


@app.errorhandler(ApiError)
@app.errorhandler(jobs.JobError)
def _api_error(e):
    return fail(e.status, e.code, e.message, **e.extra)


@app.errorhandler(HTTPException)
def _http_error(e):
    if not request.path.startswith("/api/v1"):
        return e
    code = {404: "not_found", 405: "method_not_allowed", 413: "too_large"}.get(e.code, "http_error")
    return fail(e.code, code, {404: "This endpoint does not exist.", 405: "Method not allowed here.",
                               413: "Request too large (max. 25 MB)."}.get(e.code, e.description))


@app.errorhandler(Exception)
def _crash(e):
    app.logger.exception("Unexpected error")
    if request.path.startswith("/api/v1"):
        return fail(500, "internal_error", f"Internal error: {e}")
    return jsonify(ok=False, error=f"Internal error: {e}"), 500


def _is_local():
    try:
        return ipaddress.ip_address(request.remote_addr or "").is_loopback
    except ValueError:
        return False


@app.before_request
def _check_key():
    if not API_KEY or request.method == "OPTIONS" or not request.path.startswith("/api/") or _is_local():
        return None
    given = request.headers.get("X-API-Key", "")
    auth = request.headers.get("Authorization", "")
    if not given and auth.lower().startswith("bearer "):
        given = auth[7:].strip()
    if hmac.compare_digest(given.encode(), API_KEY.encode()):
        return None
    if request.path.startswith("/api/v1"):
        return fail(401, "unauthorized", "API key missing or wrong (header X-API-Key).")
    return jsonify(ok=False, error="API key missing or wrong (header X-API-Key)."), 401


@app.after_request
def _cors(resp):
    if CORS and request.path.startswith("/api/"):
        resp.headers["Access-Control-Allow-Origin"] = CORS
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key, Authorization"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return resp


def json_body(required=True):
    """JSON-Objekt aus dem Body, unabhängig vom Content-Type. Leerer Body = {} (wenn nicht Pflicht)."""
    if not request.get_data():
        if required:
            raise ApiError(400, "invalid_json", "The body is missing – a JSON object is expected.")
        return {}
    body = request.get_json(force=True, silent=True)
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "The body is not a valid JSON object.")
    return body


def stored_assets(p):
    """Gespeichertes Logo / gespeicherte Kontur so, wie es die Parameter verlangen."""
    logo = store.load_asset("logo") if p["logo_on"] else None
    contour = store.load_asset("plate") if p["plate_src"] == "file" else None
    return (logo["strokes"] if logo else None), (contour["strokes"] if contour else None)


def machine_info():
    printers = machine.list_printers()
    busy = jobs.active()
    return {"can_send": machine.can_send(), "simulate": machine.SIMULATE,
            "printer": machine.pick_printer(), "printers": printers,
            "busy": bool(busy), "active_jobs": [j.id for j in busy]}


# ---------------------------------------------------------------- API v1

CONTROL = ("start", "force", "queue", "printer", "logo", "plate_contour", "include")
INCLUDES = ("report", "params", "gcode", "geometry")
DEFAULT_INCLUDE = ("report",)  # der ausführliche Bericht kommt immer mit (außer bei der Auftragsliste)


def _includes(value):
    """include als Liste oder kommagetrennter Text: report, params, gcode, geometry.
    Der Bericht (report) ist immer dabei."""
    if value is None:
        return DEFAULT_INCLUDE
    items = value.split(",") if isinstance(value, str) else value
    if not isinstance(items, list) or any(not isinstance(i, str) for i in items):
        raise ApiError(422, "invalid_parameters", "Invalid parameters.",
                       details=[{"field": "include", "message": "allowed: " + ", ".join(INCLUDES)}])
    items = [i.strip() for i in items if i.strip()]
    bad = [i for i in items if i not in INCLUDES]
    if bad:
        raise ApiError(422, "invalid_parameters", "Invalid parameters.",
                       details=[{"field": "include", "message": "allowed: " + ", ".join(INCLUDES)}])
    return tuple(dict.fromkeys(DEFAULT_INCLUDE + tuple(items)))


MODES = {"engrave": "Engraving", "air": "Air cut (1 mm above the surface)",
         "outline": "Trace workpiece outline (1 mm above the surface)"}
STATES = {"prepared": "calculated, not started", "queued": "waiting in the queue",
          "running": "being transferred to the machine", "error": "stuck in the queue",
          "done": "completely transferred to the machine", "failed": "sending failed",
          "cancelled": "cancelled"}


def _duration(minutes):
    s = int(round(minutes * 60))
    return f"{s // 3600} h {s // 60 % 60} min {s % 60} s" if s >= 3600 else f"{s // 60} min {s % 60} s"


def _r(v, n=3):
    if v is None:
        return None
    if isinstance(v, (list, tuple)):
        return [_r(x, n) for x in v]
    return round(v, n)


def report(job):
    """Ausführlicher Bericht zu einem Auftrag: Laufzeit, Werkstück, Text, Logo, Spannbereiche,
    Fräsparameter, Werkzeugweg, G-Code-Kontrolle, Warnungen und ob/warum er startbar ist."""
    r, p = job.result, job.params
    src = getattr(job, "sources", {})
    st = r["stats"]
    sec = int(round(r["minutes"] * 60))
    finish = None
    if job.started:
        from datetime import datetime, timedelta
        finish = (datetime.fromisoformat(job.started) + timedelta(seconds=sec)).isoformat(timespec="seconds")
    pw, ph = r["plate_size"]
    tb = r["text_bbox"]
    text_on = bool(r["text"])
    logo_on = bool(r["logo"])

    # Startbar? Gründe sammeln
    reasons = []
    if not r["startable"]:
        reasons.append("Nothing to engrave – no text and no logo.")
    if not r["check"]["ok"]:
        reasons.append("G-code moves into a clamp zone (cannot be overridden).")
    if r["blocking"]:
        reasons.append("Blocking warning: " + ", ".join(r["blocking"]) + " – only with \"force\": true.")
    if job.state != "prepared":
        reasons.append(f"Job is no longer in state prepared (but {job.state}).")

    what = MODES[r["mode"]]
    label = (f"\"{p['text']}\"" if text_on else "") + (" + Logo" if logo_on else "")
    summary = (f"{what}{' ' + label.strip() if label.strip() and r['mode'] != 'outline' else ''} "
               f"on {pw:g} × {ph:g} mm, estimated runtime {_duration(r['minutes'])}, "
               f"{r['gcode'].count(chr(10))} G-code lines. "
               f"Clamp zones: {'active' if r['clamps'] else 'OFF'}, "
               f"G-code check: {'OK' if r['check']['ok'] else 'VIOLATED'}. "
               f"State: {STATES.get(job.state, job.state)}.")

    return {
        "summary": summary,
        "state": {"code": job.state, "text": STATES.get(job.state, job.state), "message": job.message,
                  "created": job.created, "started": job.started, "finished": job.finished,
                  "estimated_finish": finish, "printer": job.printer, "simulated": job.simulated},
        "runtime": {"seconds": sec, "minutes": round(r["minutes"], 2), "text": _duration(r["minutes"]),
                    "cutting_minutes": st["minutes_cut"], "travel_minutes": st["minutes_travel"],
                    "plunge_minutes": st["minutes_plunge"],
                    "note": f"Estimate: feed {p['feed']:g} mm/min, rapid ~{E.RAPID} mm/min assumed"},
        "start": {"can_start": job.state == "prepared" and not reasons,
                  "needs_force": bool(r["blocking"]), "blocked_reasons": reasons},
        "mode": {"code": r["mode"], "text": what},
        "plate": {"source": "contour from file" if p["plate_src"] == "file" else "plate with rounded corners",
                  "contour_name": src.get("plate"), "width": _r(pw), "height": _r(ph),
                  "corner_radius": p["plate_r"] if p["plate_src"] == "rect" else None,
                  "work_area": [E.WORK_X, E.WORK_Y]},
        "text": {"content": p["text"], "engraved": text_on, "font": p["font"],
                 "font_name": E.FONTS.get(p["font"], p["font"]),
                 "height_requested": p["height"], "height_used": _r(r["text_height"]),
                 "shrunk": bool(r["text_height"] and r["text_height"] < p["height"] - 1e-6),
                 "size": _r([tb[2] - tb[0], tb[3] - tb[1]]) if tb else None, "bbox": _r(tb),
                 "depth": p["depth"] if r["mode"] == "engrave" else None,
                 "spacing_mode": p["spacing_mode"], "align": p["align"]},
        "logo": {"engraved": logo_on, "name": src.get("logo") if logo_on else None,
                 "source": src.get("logo_source") if logo_on else None,
                 "area": _r(r["logo_area"]), "bbox": _r(E.bbox_of(r["logo"])) if logo_on else None,
                 "depth": p["logo_depth"] if logo_on and r["mode"] == "engrave" else None,
                 "fill": p["logo_fill"], "scale_pct": p["logo_scale"]},
        "clamps": {"active": bool(r["clamps"]),
                   "source": (None if not r["clamps"] else
                              "default" if all(str(getattr(job, "params_given", {}).get(k) or "").strip() == ""
                                                for k in ("clamp_d", "clamp_in", "clamp_y", "clamp_margin"))
                              else "custom"),
                   "diameter": p["clamp_d"], "reach_into_plate": p["clamp_in"],
                   "center_y": p["clamp_y"] if p["clamp_y"] is not None else _r(ph / 2),
                   "margin": p["clamp_margin"],
                   "zones": [{"side": side, "center": [c[0], c[1]], "radius": c[2], "radius_with_margin": c[3]}
                             for side, c in zip(("left", "right"), r["clamps"])]},
        "milling": {"depth_text": p["depth"], "depth_logo": p["logo_depth"], "passes": p["passes"],
                    "feed": p["feed"], "plunge": p["plunge"], "rpm": p["rpm"], "safe_z": p["safe_z"],
                    "wcs": p["wcs"],
                    "start_position": {"x": p["park_x"], "y": p["park_y"], "z": p["park_z"],
                                       "note": "The program always moves here first: Z first, then X/Y"},
                    "end_position": ({"x": p["park_x"], "y": p["park_y"], "z": p["park_z"]} if p["park"]
                                     else {"x": 0, "y": 0, "z": max(p["safe_z"], 3) if r["mode"] != "engrave"
                                           else p["safe_z"]})},
        "toolpath": {"gcode_lines": r["gcode"].count("\n"), "cut_length_mm": st["cut_mm"],
                     "travel_length_mm": st["travel_mm"], "plunges": st["plunges"], "z_min": st["z_min"]},
        "gcode_check": r["check"],
        "warnings": r["warnings"],
    }


def job_view(job, include=()):
    r = job.result
    d = {
        "id": job.id,
        "state": job.state,
        "message": job.message,
        "mode": r["mode"],
        "created": job.created, "started": job.started, "finished": job.finished,
        "printer": job.printer,
        "simulated": job.simulated,
        "minutes": round(r["minutes"], 2),
        "gcode_lines": r["gcode"].count("\n"),
        "warnings": r["warnings"],
        "can_start": job.state == "prepared" and r["startable"] and r["check"]["ok"],
        "needs_force": bool(r["blocking"]),
        "gcode_check": r["check"],
        "clamps": r["clamps"],
        "plate_size": [round(v, 3) for v in r["plate_size"]],
        "text_height": r["text_height"] and round(r["text_height"], 3),
        "text_bbox": r["text_bbox"] and [round(v, 3) for v in r["text_bbox"]],
        "logo_area": r["logo_area"] and [round(v, 3) for v in r["logo_area"]],
        "links": {"self": f"/api/v1/jobs/{job.id}", "start": f"/api/v1/jobs/{job.id}/start",
                  "cancel": f"/api/v1/jobs/{job.id}/cancel", "gcode": f"/api/v1/jobs/{job.id}/gcode"},
    }
    if "report" in include:
        d["report"] = report(job)
    if "params" in include:
        d["params"] = job.params
    if "gcode" in include:
        d["gcode"] = r["gcode"]
    if "geometry" in include:
        d["geometry"] = {"text": E.rnd(r["text"]), "logo": E.rnd(r["logo"]), "plate": E.rnd(r["plate"])}
    return d


def _find(job_id):
    job = jobs.get(job_id)
    if not job:
        raise ApiError(404, "job_not_found", f"Job {job_id} does not exist (anymore).")
    return job


def _start_options(body, errors):
    """start / force / queue / printer aus dem Body prüfen."""
    opt = {}
    for key in ("start", "force", "queue"):
        try:
            opt[key] = False if body.get(key) is None else P.to_bool(body[key])
        except P.Invalid as e:
            errors.append({"field": key, "message": str(e)})
    printer = body.get("printer")
    if printer is not None and (not isinstance(printer, str) or not printer.strip()):
        errors.append({"field": "printer", "message": "must be a printer name as a string"})
    opt["printer"] = printer
    return opt


@app.get("/api/v1")
@app.get("/api/v1/")
def v1_index():
    return jsonify(ok=True, name="SRM-20 Engraver", version=API_VERSION, endpoints={
        "GET /api/v1/status": "State: machine, printers, running jobs, stored logo/contour",
        "GET /api/v1/parameters": "all job parameters with type, default value and limits",
        "POST /api/v1/jobs": "calculate a job, with \"start\": true mill immediately",
        "GET /api/v1/jobs": "list of jobs",
        "GET /api/v1/jobs/<id>": "state of a job",
        "POST /api/v1/jobs/<id>/start": "mill a calculated job",
        "POST /api/v1/jobs/<id>/cancel": "cancel a job",
        "GET /api/v1/jobs/<id>/gcode": "G-code as plain text",
        "GET|PUT|DELETE /api/v1/assets/<logo|plate>": "store logo or workpiece contour permanently",
        "GET /api/v1/logos": "standard logos from the folder logos/ (in a job: \"logo\": {\"library\": \"name.svg\"})",
    })


@app.get("/api/v1/status")
def v1_status():
    return jsonify(ok=True, version=API_VERSION, machine=machine_info(),
                   assets={k: store.asset_info(k) for k in store.ASSETS})


@app.get("/api/v1/parameters")
def v1_parameters():
    return jsonify(ok=True, parameters=P.schema(), fonts=E.FONTS, presets=store.presets(),
                   work_area={"x": E.WORK_X, "y": E.WORK_Y})


@app.post("/api/v1/jobs")
def v1_create_job():
    body = json_body()
    p, errors = P.parse(body, strict=True, extra=CONTROL)
    opt = _start_options(body, errors)

    # Logo / Kontur direkt im Auftrag (gilt nur für diesen Auftrag), sonst die gespeicherten
    logo, contour = stored_assets(p)
    sources = {}
    for kind in ("logo", "plate"):
        a = store.load_asset(kind)
        if a:
            sources[kind], sources[kind + "_source"] = a["name"], "stored"
    for field, kind in (("logo", "logo"), ("plate_contour", "plate")):
        if body.get(field) is None:
            continue
        try:
            asset = store.asset_from_json(kind, body[field])
        except store.BadAsset as e:
            errors.append({"field": field, "message": str(e)})
            continue
        sources[kind] = asset["name"]
        sources[kind + "_source"] = ("standard logo (logos/)" if isinstance(body[field], dict)
                                     and body[field].get("library") else "sent with the job")
        if kind == "logo":
            logo = asset["strokes"] if p["logo_on"] else None
        else:
            contour = asset["strokes"]
    if p["plate_src"] == "file" and not contour:
        errors.append({"field": "plate_src", "message": "file requires a contour: send plate_contour "
                                                        "or store one first with PUT /api/v1/assets/plate"})
    if errors:
        raise ApiError(422, "invalid_parameters", "Invalid parameters – nothing calculated, nothing sent.",
                       details=errors)
    include = _includes(body.get("include"))

    job = jobs.create(p, E.build(p, logo, contour))
    job.sources = sources
    job.params_given = {k: body.get(k) for k in P.NAMES}
    if opt["start"]:
        try:
            jobs.start(job, opt["printer"], opt["force"], opt["queue"])
        except jobs.JobError as e:
            # Auftrag bleibt bestehen und kann später gestartet werden – Bericht kommt mit
            e.extra["job"] = job_view(job, DEFAULT_INCLUDE)
            raise
    resp = jsonify(ok=True, job=job_view(job, include))
    resp.status_code = 201
    resp.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return resp


@app.get("/api/v1/jobs")
def v1_list_jobs():
    return jsonify(ok=True, jobs=[job_view(j) for j in jobs.all_jobs()])


@app.get("/api/v1/jobs/<job_id>")
def v1_get_job(job_id):
    return jsonify(ok=True, job=job_view(_find(job_id), _includes(request.args.get("include"))))


@app.get("/api/v1/jobs/<job_id>/gcode")
def v1_job_gcode(job_id):
    return Response(_find(job_id).result["gcode"], mimetype="text/plain")


@app.post("/api/v1/jobs/<job_id>/start")
def v1_start_job(job_id):
    job = _find(job_id)
    body = json_body(required=False)
    errors = [{"field": k, "message": "unknown field"} for k in body if k not in ("force", "queue", "printer")]
    opt = _start_options(body, errors)
    if errors:
        raise ApiError(422, "invalid_parameters", "Invalid parameters – nothing sent.", details=errors)
    jobs.start(job, opt["printer"], opt["force"], opt["queue"])
    return jsonify(ok=True, job=job_view(job, DEFAULT_INCLUDE))


@app.post("/api/v1/jobs/<job_id>/cancel")
@app.delete("/api/v1/jobs/<job_id>")
def v1_cancel_job(job_id):
    job = _find(job_id)
    removed = jobs.cancel(job)
    return jsonify(ok=True, removed_from_queue=removed, job=job_view(job, DEFAULT_INCLUDE))


@app.get("/api/v1/logos")
def v1_logos():
    return jsonify(ok=True, folder=str(store.LOGO_DIR), logos=store.library_info())


@app.get("/api/v1/assets/<kind>")
def v1_get_asset(kind):
    if kind not in store.ASSETS:
        raise ApiError(404, "not_found", "Allowed: logo, plate.")
    info = store.asset_info(kind)
    if info and "geometry" in _includes(request.args.get("include")):
        info["strokes"] = store.load_asset(kind)["strokes"]
    return jsonify(ok=True, asset=info)


@app.put("/api/v1/assets/<kind>")
@app.post("/api/v1/assets/<kind>")
def v1_put_asset(kind):
    if kind not in store.ASSETS:
        raise ApiError(404, "not_found", "Allowed: logo, plate.")
    try:
        asset = store.asset_from_json(kind, json_body())
    except store.BadAsset as e:
        raise ApiError(422, "invalid_asset", str(e))
    store.save_asset(kind, asset)
    return jsonify(ok=True, asset={k: asset[k] for k in ("name", "notes", "size")})


@app.delete("/api/v1/assets/<kind>")
def v1_delete_asset(kind):
    if kind not in store.ASSETS:
        raise ApiError(404, "not_found", "Allowed: logo, plate.")
    store.delete_asset(kind)
    return jsonify(ok=True, asset=None)


# ---------------------------------------------------------------- Weboberfläche (ältere Endpunkte)

@app.get("/")
def index():
    return send_file(E.BASE / "index.html")


@app.get("/api/info")
def info():
    assets = {}
    for kind in store.ASSETS:
        a = store.load_asset(kind)
        assets[kind] = {"name": a["name"], "notes": a.get("notes", [])} if a else None
    return jsonify(fonts=E.FONTS, font_list=[[k, v] for k, v in E.FONTS.items()],
                   default_font=E.font_key(E.DEFAULT_FONT), printers=machine.list_printers(),
                   windows=machine.can_send(), presets=store.presets(), assets=assets,
                   library=store.library())


@app.get("/api/logos")
def logos():
    return jsonify(ok=True, logos=store.library())


@app.post("/api/logos/use")
def use_logo():
    """Standard-Logo als aktuelles Logo übernehmen."""
    try:
        asset = store.library_logo((request.json or {}).get("name"))
    except store.BadAsset as e:
        return jsonify(ok=False, error=str(e)), 400
    store.save_asset("logo", asset)
    return jsonify(ok=True, name=asset["name"], size=asset["size"], notes=asset["notes"])


@app.post("/api/logos")
def add_logo():
    """Datei als Standard-Logo in den Ordner logos/ legen (vorher prüfen, ob sie lesbar ist)."""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(ok=False, error="No file."), 400
    name = re.sub(r"[^\w.\- ]", "_", os.path.basename(f.filename)).strip(" .")[:100]
    if not name.lower().endswith(store.LOGO_EXT):
        return jsonify(ok=False, error="Only SVG, DXF or DWG."), 400
    data = f.read()
    try:
        asset = store.asset_from_file("logo", name, data)
    except store.BadAsset as e:
        return jsonify(ok=False, error=str(e)), 400
    if (store.LOGO_DIR / name).exists() and request.args.get("overwrite") != "1":
        return jsonify(ok=False, exists=True, error=f"\"{name}\" already exists in the standard logos."), 409
    store.LOGO_DIR.mkdir(exist_ok=True)
    (store.LOGO_DIR / name).write_bytes(data)
    store.save_asset("logo", asset)
    return jsonify(ok=True, name=name, size=asset["size"], notes=asset["notes"], logos=store.library())


@app.post("/api/preview")
def preview():
    p, _ = P.parse(request.json or {}, strict=False)
    r = E.build(p, *stored_assets(p))
    return jsonify(text=E.rnd(r["text"]), logo=E.rnd(r["logo"]), plate=E.rnd(r["plate"]),
                   plate_size=r["plate_size"], logo_area=r["logo_area"], text_height=r["text_height"],
                   text_bbox=r["text_bbox"], minutes=r["minutes"], warnings=[w["message"] for w in r["warnings"]],
                   lines=r["gcode"].count("\n"), gcode=r["gcode"], clamps=r["clamps"], check=r["check"])


@app.post("/api/send")
def send():
    raw = request.json or {}
    p, _ = P.parse(raw, strict=False)
    job = jobs.create(p, E.build(p, *stored_assets(p)))
    try:
        # wie bisher: keine Sperre bei Warnungen, mehrere Aufträge reihen sich ein
        jobs.start(job, raw.get("printer") or None, force=True, queue=True)
    except jobs.JobError as e:
        return jsonify(ok=False, error=e.message), 500 if e.code == "send_failed" else 400
    return jsonify(ok=True, minutes=job.result["minutes"], job=job.id)


@app.post("/api/upload/<kind>")
def upload(kind):
    if kind not in store.ASSETS:
        return jsonify(ok=False, error="Unknown type."), 400
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(ok=False, error="No file."), 400
    try:
        asset = store.asset_from_file(kind, f.filename, f.read())
    except store.BadAsset as e:
        return jsonify(ok=False, error=str(e)), 400
    store.save_asset(kind, asset)
    return jsonify(ok=True, name=asset["name"], size=asset["size"], notes=asset["notes"])


@app.delete("/api/upload/<kind>")
def remove_upload(kind):
    if kind in store.ASSETS:
        store.delete_asset(kind)
    return jsonify(ok=True)


@app.post("/api/presets")
def add_preset():
    p = request.json or {}
    name = re.sub(r"\s+", " ", str(p.get("name", ""))).strip()[:60]
    if not name:
        return jsonify(ok=False, error="Name missing."), 400
    if any(x["name"] == name for x in store.DEFAULT_PRESETS):
        return jsonify(ok=False, error="Name is already taken."), 400
    size, _ = P.parse({"plate_w": p.get("w"), "plate_h": p.get("h"), "plate_r": p.get("r")}, strict=False)
    own = [x for x in store.load_json("presets.json", []) if x["name"] != name]
    own.append({"name": name, "w": size["plate_w"], "h": size["plate_h"], "r": size["plate_r"]})
    store.save_json("presets.json", own)
    return jsonify(ok=True, presets=store.presets())


@app.delete("/api/presets")
def del_preset():
    name = request.args.get("name", "")
    store.save_json("presets.json", [x for x in store.load_json("presets.json", []) if x["name"] != name])
    return jsonify(ok=True, presets=store.presets())


if __name__ == "__main__":
    host = os.environ.get("SRM20_HOST", "0.0.0.0")
    port = int(os.environ.get("SRM20_PORT", "5000"))
    if machine.SIMULATE:
        print("SIMULATION: nothing is sent to the machine (G-code goes to data/simulated/).")
    elif not machine.can_send():
        print("Note: pywin32 not found – preview works, sending does not.", file=sys.stderr)
    if API_KEY:
        print("API key active: requests from other computers need the header X-API-Key.")
    print(f"SRM-20 Engraver running at http://localhost:{port}   (API: /api/v1, documentation in API.md)")
    app.run(host=host, port=port)
