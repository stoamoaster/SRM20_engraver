"""
Verbindung zur Fräse: Die SRM-20 hängt als Windows-Drucker am PC, der G-Code geht als RAW-Druckauftrag hinaus.

Simulation: Umgebungsvariable SRM20_SIMULATE=1 -> es wird nichts gesendet, der G-Code landet
stattdessen in data/simulated/. Damit lässt sich eine externe App ohne Fräse entwickeln.
"""
import os
import threading
import time

try:
    import pywintypes
    import win32print  # pywin32 – nur unter Windows verfügbar
except ImportError:
    win32print = None

import store

SIMULATE = os.environ.get("SRM20_SIMULATE", "").strip().lower() in ("1", "true", "yes", "ja", "on")
SIM_PRINTER = "Simulation (kein Versand)"

# Statusbits eines Windows-Druckauftrags (JOB_STATUS_*)
_PAUSED, _ERROR, _DELETING, _SPOOLING, _PRINTING = 0x1, 0x2, 0x4, 0x8, 0x10
_OFFLINE, _PAPEROUT, _PRINTED, _DELETED, _BLOCKED, _INTERVENTION = 0x20, 0x40, 0x80, 0x100, 0x200, 0x400
_PROBLEMS = {_ERROR: "Fehler", _OFFLINE: "Fräse offline oder nicht verbunden", _PAPEROUT: "Gerät nicht bereit",
             _BLOCKED: "Warteschlange blockiert", _INTERVENTION: "Eingriff am Gerät nötig"}

_cache = {"t": 0.0, "names": []}
_lock = threading.Lock()
_sim_no = 0


class MachineError(Exception):
    pass


def can_send():
    return SIMULATE or bool(win32print)


def list_printers(max_age=10.0):
    """Windows-Drucker, Einträge mit „SRM“ im Namen zuerst. Die Abfrage ist langsam -> kurz zwischenspeichern."""
    if not win32print:
        return []
    with _lock:
        if time.monotonic() - _cache["t"] > max_age or not _cache["names"]:
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            names = [p[2] for p in win32print.EnumPrinters(flags)]
            _cache.update(t=time.monotonic(), names=sorted(names, key=lambda n: ("srm" not in n.lower(), n)))
        return list(_cache["names"])


def pick_printer(name=None):
    """Drucker für einen Auftrag: ausdrücklich genannt, sonst SRM20_PRINTER, sonst der erste mit „SRM“ im Namen.
    Liefert None, wenn es den Drucker nicht gibt."""
    if SIMULATE:
        return SIM_PRINTER
    names = list_printers()
    name = name or os.environ.get("SRM20_PRINTER")
    if name:
        return name if name in names else None
    return next((n for n in names if "srm" in n.lower()), None)


def send(printer, gcode):
    """Schickt den G-Code los. Liefert die Auftragsnummer im Windows-Spooler (None in der Simulation)."""
    if SIMULATE:
        global _sim_no
        folder = store.DATA / "simulated"
        folder.mkdir(parents=True, exist_ok=True)
        with _lock:
            _sim_no += 1
            name = f"{time.strftime('%Y%m%d-%H%M%S')}-{_sim_no:03d}.nc"
        (folder / name).write_text(gcode, encoding="ascii")
        return None
    if not win32print:
        raise MachineError("pywin32 fehlt oder kein Windows – senden nicht möglich.")
    try:
        h = win32print.OpenPrinter(printer)
        try:
            spool_id = win32print.StartDocPrinter(h, 1, ("SRM-20 Gravur", None, "RAW"))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, gcode.encode("ascii"))
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            win32print.ClosePrinter(h)
    except pywintypes.error as e:
        raise MachineError(f"{e.strerror.strip()} (Windows-Fehler {e.winerror})")
    return spool_id


def spool_state(printer, spool_id):
    """Zustand eines gesendeten Auftrags im Windows-Spooler -> (zustand, hinweis).
    queued = wartet, running = wird übertragen, error = hängt (z. B. Fräse aus),
    done = nicht mehr in der Warteschlange, also vollständig an die Fräse übertragen."""
    if SIMULATE or spool_id is None:
        return "done", None
    try:
        h = win32print.OpenPrinter(printer)
        try:
            info = win32print.GetJob(h, spool_id, 1)
        finally:
            win32print.ClosePrinter(h)
    except pywintypes.error:
        return "done", None  # Auftrag gibt es nicht mehr
    st = info.get("Status") or 0
    if st & (_PRINTED | _DELETED):
        return "done", None
    for bit, text in _PROBLEMS.items():
        if st & bit:
            return "error", info.get("pStatus") or text
    if st & _PRINTING:
        return "running", None
    return "queued", "Warteschlange angehalten" if st & _PAUSED else None


def cancel(printer, spool_id):
    """Nimmt einen Auftrag aus der Windows-Warteschlange. True = entfernt.
    Was die Fräse schon erhalten hat, fräst sie weiter – dort hilft nur VPanel oder die VIEW-Taste."""
    if SIMULATE or spool_id is None or not win32print:
        return False
    try:
        h = win32print.OpenPrinter(printer)
        try:
            win32print.SetJob(h, spool_id, 0, None, win32print.JOB_CONTROL_DELETE)
        finally:
            win32print.ClosePrinter(h)
    except pywintypes.error:
        return False
    return True
