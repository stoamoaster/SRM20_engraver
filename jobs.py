"""
Aufträge: berechnen (prepared), starten, Zustand verfolgen, abbrechen.

Zustände:
  prepared   berechnet, noch nicht gestartet
  queued     in der Windows-Warteschlange, wartet
  running    wird an die Fräse übertragen
  error      hängt in der Warteschlange (z. B. Fräse aus) – läuft weiter, sobald das Problem behoben ist
  done       vollständig an die Fräse übertragen
  failed     konnte nicht gesendet werden
  cancelled  abgebrochen

Die Aufträge liegen nur im Arbeitsspeicher und sind nach einem Neustart des Servers weg.
"""
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime

import machine

KEEP = 100                              # so viele Aufträge werden aufgehoben
ACTIVE = ("queued", "running", "error")  # belegt die Fräse
POLL_SECONDS = 2.0

_jobs = OrderedDict()
_lock = threading.RLock()


class JobError(Exception):
    """Auftrag kann nicht gestartet/abgebrochen werden. code = stabiler Fehlercode für die API."""

    def __init__(self, status, code, message, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Job:
    def __init__(self, params, result):
        self.id = uuid.uuid4().hex[:12]
        self.params, self.result = params, result
        self.state, self.message = "prepared", None
        self.created, self.started, self.finished = _now(), None, None
        self.printer = self.spool_id = None
        self.simulated = False


def create(params, result):
    job = Job(params, result)
    with _lock:
        _jobs[job.id] = job
        # alte, abgeschlossene Aufträge vergessen
        for old in [j for j in _jobs.values() if j.state not in ACTIVE][:max(0, len(_jobs) - KEEP)]:
            del _jobs[old.id]
    return job


def get(job_id):
    with _lock:
        return _jobs.get(job_id)


def all_jobs():
    with _lock:
        return list(reversed(_jobs.values()))


def active(exclude=None):
    with _lock:
        return [j for j in _jobs.values() if j.state in ACTIVE and j is not exclude]


def _refresh(job):
    with _lock:
        if job.state not in ACTIVE:
            return
        printer, spool_id = job.printer, job.spool_id
    state, message = machine.spool_state(printer, spool_id)
    with _lock:
        if job.state not in ACTIVE:  # inzwischen abgebrochen
            return
        job.state, job.message = state, message
        if state == "done":
            job.finished = _now()


def _watch(job):
    while job.state in ACTIVE:
        time.sleep(POLL_SECONDS)
        try:
            _refresh(job)
        except Exception as e:  # Abfrage des Spoolers darf den Auftrag nicht kippen
            job.message = str(e)


def start(job, printer=None, force=False, queue=False):
    """Schickt einen berechneten Auftrag an die Fräse. Die Fräse läuft danach sofort los."""
    with _lock:
        if job.state != "prepared":
            raise JobError(409, "already_started", f"Job has already been started (state: {job.state}).")
        r = job.result
        if not r["startable"]:
            raise JobError(422, "nothing_to_engrave", "Nothing to engrave – no text and no logo.")
        if not r["check"]["ok"]:  # G-Code fährt in einen Spannbereich: nie senden, auch nicht mit force
            texts = [w["message"] for w in r["warnings"] if w["code"] == "clamp_collision"]
            raise JobError(409, "clamp_collision", " ".join(texts) or "G-code violates a clamp zone.",
                           violations=r["check"]["violations"])
        if r["blocking"] and not force:
            texts = [w["message"] for w in r["warnings"] if w["code"] in r["blocking"]]
            raise JobError(409, "blocked_by_warning",
                           "Start refused: " + " ".join(texts) + " Use \"force\": true to start anyway.",
                           warnings=r["blocking"])
        if not machine.can_send():
            raise JobError(503, "machine_unavailable", "pywin32 missing or not on Windows – cannot send.")
        chosen = machine.pick_printer(printer)
        if not chosen:
            raise JobError(503, "printer_not_found",
                           f"Printer \"{printer}\" not found." if printer else
                           "No printer with \"SRM\" in its name found – specify the printer field.",
                           printers=machine.list_printers())
        busy = active(exclude=job)
        if busy and not queue:
            raise JobError(409, "machine_busy",
                           f"The machine is still busy with job {busy[0].id}. "
                           "Use \"queue\": true to queue the new job behind it.",
                           active_job=busy[0].id)
        job.state, job.printer, job.started = "queued", chosen, _now()  # reserviert die Fräse
    try:
        spool_id = machine.send(chosen, r["gcode"])
    except Exception as e:
        with _lock:
            job.state, job.message, job.finished = "failed", str(e), _now()
        raise JobError(502, "send_failed", f"Sending failed: {e}")
    with _lock:
        job.spool_id, job.simulated = spool_id, machine.SIMULATE
    _refresh(job)
    if job.state in ACTIVE:
        threading.Thread(target=_watch, args=(job,), daemon=True).start()
    return job


def cancel(job):
    """Bricht ab: ein wartender Auftrag wird aus der Windows-Warteschlange genommen.
    Liefert True, wenn er dort noch entfernt werden konnte."""
    with _lock:
        if job.state in ("done", "failed", "cancelled"):
            raise JobError(409, "already_finished", f"Job is already finished (state: {job.state}).")
        was_active = job.state in ACTIVE
        job.state, job.finished = "cancelled", _now()
        job.message = None
    removed = machine.cancel(job.printer, job.spool_id) if was_active else False
    if was_active and not removed:
        job.message = ("The job had already reached the machine and could not be removed from the queue "
                       "– stop it in VPanel or with the VIEW button on the machine.")
    return removed
