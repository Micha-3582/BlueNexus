"""
Funkthermometer (ESP32-C3, Projekt "BlueNexus Aussenthermometer"): Register, Annahme der Messwerte, Sensoren.

Ablauf: Der Administrator richtet ein Thermometer ein (Einstellungen -> System -> Funkthermometer). BlueNexus erzeugt eine Geraete-ID und einen
zufaelligen Schluessel (Token); gespeichert wird nur der HASH des Schluessels. ID + Schluessel + WLAN-Daten landen im Browser in der
Konfiguration des Geraets (cfg.bin) - das WLAN-Passwort sieht der Server nie.
Das Geraet meldet sich alle paar Minuten mit `POST /api/sensor/<id>` (Kopfzeile `Authorization: Bearer <Schluessel>`, JSON
{"temp","hum","bat","rssi","fw"}). BlueNexus legt je Geraet vier Sensoren im normalen Sensor-Register an (Temperatur, Luftfeuchte, Batterie, Funkstaerke);
sie erscheinen wie alle anderen Sensoren (Dashboard, Verlaeufe, Regeln, Sichtbarkeit pro Konto).
Reine Logik + eine JSON-Datei (thermo.json).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time

import store

_DIR = os.path.dirname(os.path.abspath(__file__))
THERMO_PATH = os.path.join(_DIR, "thermo.json")
_lock = threading.RLock()

DEFAULT_INTERVAL_MIN = 15
MISSED_INTERVALS = 3                # so viele Intervalle ohne Meldung: Geraet gilt als offline (Sensorwert = "nicht erreichbar")
BAT_NO_MEASURE_V = 1.0              # darunter ist keine Batteriemessung verdrahtet (USB-Betrieb liefert Zufallswerte, siehe Uebergabe-Notiz)
LIMITS = {"temp": (-60.0, 80.0), "hum": (0.0, 100.0)}
ID_RE = re.compile(r"^t-[a-z0-9]{6,12}$")
# metric -> (Schluessel im Zustand, Sensorart, Bezeichnung, Einheit)
METRICS = {
    "temp": ("temp", "temperature", "Temperatur", "°C"),
    "hum": ("hum", "humidity", "Luftfeuchte", "%"),
    "bat": ("bat", "voltage", "Batterie", "V"),
    "rssi": ("rssi", "signal", "Funkstärke", "dBm"),
}


class ThermoError(Exception):
    pass


def _load() -> list[dict]:
    d = store._load_json_recovering(THERMO_PATH, lambda: [])
    return d if isinstance(d, list) else []


def _save(items: list[dict]) -> None:
    store._dump_json(THERMO_PATH, items, indent=1)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def sensor_id(tid: str, metric: str) -> str:
    return f"thermo-{tid}-{metric}"


def load() -> list[dict]:
    with _lock:
        return [dict(x) for x in _load()]


def get(tid: str) -> dict | None:
    return next((x for x in load() if x.get("id") == tid), None)


def new_token() -> str:
    return secrets.token_urlsafe(24)                    # 32 Zeichen, ~192 Bit Zufall (Vorgabe: mindestens 24 Zeichen)


def new_id() -> str:
    return "t-" + "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))


def _interval(v) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_MIN
    return max(1, min(1440, n))


def _make_sensors(dev: dict) -> list[dict]:
    import homematic
    sens = homematic.load_sensors()
    have = {s["id"] for s in sens}
    made = []
    for metric, (_k, kind, label, unit) in METRICS.items():
        sid = sensor_id(dev["id"], metric)
        if sid in have:
            continue
        s = {"id": sid, "kind": kind, "source": "thermo", "address": dev["id"], "interface": "thermo", "datapoint": metric, "binary": False, "unit": unit,
             "model": "Funkthermometer", "room": "", "name": f"{dev['name']} {label}", "show": True, "users": []}
        sens.append(s)
        made.append(s)
    if made:
        homematic._save_sensors(sens)
    return made


def create(name: str, interval=DEFAULT_INTERVAL_MIN) -> tuple[dict, str]:
    """Neues Thermometer: -> (Geraet ohne Schluessel, Klartext-Schluessel). Der Schluessel wird nur HIER im Klartext geliefert."""
    nm = (name or "").strip()[:40] or "Thermometer"
    token = new_token()
    with _lock:
        items = _load()
        ids = {x["id"] for x in items}
        tid = new_id()
        while tid in ids:
            tid = new_id()
        dev = {"id": tid, "name": nm, "token_hash": _hash(token), "interval": _interval(interval), "created": time.time(),
               "last_seen": None, "fw": None, "last": {}}
        items.append(dev)
        _save(items)
    _make_sensors(dev)
    return public(dev), token


def public(dev: dict) -> dict:
    """Ohne Schluessel-Hash, mit Status fuer die Oberflaeche."""
    now = time.time()
    ls = dev.get("last_seen")
    iv = int(dev.get("interval") or DEFAULT_INTERVAL_MIN)
    return {"id": dev["id"], "name": dev.get("name") or dev["id"], "interval": iv, "created": dev.get("created"), "last_seen": ls, "fw": dev.get("fw"),
            "age_s": None if ls is None else int(now - ls), "online": ls is not None and now - ls <= iv * 60 * MISSED_INTERVALS + 120,
            "last": dict(dev.get("last") or {}), "sensors": [sensor_id(dev["id"], m) for m in METRICS]}


def listing() -> list[dict]:
    return [public(x) for x in load()]


def rename(tid: str, name: str | None = None, interval=None) -> bool:
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d:
            return False
        if name is not None and name.strip():
            d["name"] = name.strip()[:40]
        if interval is not None:
            d["interval"] = _interval(interval)
        _save(items)
    import homematic                                        # Sensornamen mitfuehren (nur solche, die noch den automatischen Namen tragen)
    if name is not None and name.strip():
        sens = homematic.load_sensors()
        ch = False
        for s in sens:
            if s.get("source") == "thermo" and s.get("address") == tid and s.get("auto_name", True):
                lab = METRICS.get(s.get("datapoint"), (0, 0, "", ""))[2]
                s["name"] = f"{name.strip()[:40]} {lab}".strip()
                ch = True
        if ch:
            homematic._save_sensors(sens)
    return True


def new_key(tid: str) -> str | None:
    """Neuer Schluessel (das Geraet muss neu eingerichtet werden). -> Klartext oder None."""
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d:
            return None
        token = new_token()
        d["token_hash"] = _hash(token)
        d["last_seen"] = None
        _save(items)
    return token


def remove(tid: str) -> bool:
    with _lock:
        items = _load()
        keep = [x for x in items if x.get("id") != tid]
        if len(keep) == len(items):
            return False
        _save(keep)
    import homematic
    sens = homematic.load_sensors()
    left = [s for s in sens if not (s.get("source") == "thermo" and s.get("address") == tid)]
    if len(left) != len(sens):
        homematic._save_sensors(left)
    return True


def _num(v, lo: float, hi: float):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 2) if lo <= f <= hi and f == f else None


def ingest(tid: str, token: str, body: dict) -> tuple[int, dict]:
    """Messung annehmen. -> (HTTP-Status, Antwort). 401 = Schluessel falsch/Geraet unbekannt (gleiche Antwort, damit man IDs nicht abklopfen kann)."""
    if not ID_RE.match(tid or "") or not token:
        return 401, {"error": "unauthorized"}
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d or not hmac.compare_digest(str(d.get("token_hash") or ""), _hash(token)):
            return 401, {"error": "unauthorized"}
        if not isinstance(body, dict):
            return 400, {"error": "json erwartet"}
        last = dict(d.get("last") or {})
        got = False
        t = _num(body.get("temp"), *LIMITS["temp"])
        h = _num(body.get("hum"), *LIMITS["hum"])
        if t is not None:
            last["temp"] = t
            got = True
        if h is not None:
            last["hum"] = h
            got = True
        b = _num(body.get("bat"), 0.0, 10.0)
        if b is not None:
            last["bat"] = b
        r = _num(body.get("rssi"), -127.0, 0.0)
        if r is not None:
            last["rssi"] = r
        if not got:
            return 400, {"error": "keine gueltigen Messwerte"}
        d["last"], d["last_seen"] = last, time.time()
        fw = str(body.get("fw") or "")[:20]
        if fw:
            d["fw"] = fw
        _save(items)
        interval = int(d.get("interval") or DEFAULT_INTERVAL_MIN)
    return 200, {"ok": True, "interval": interval}


def read_value(sen: dict):
    """Aktueller Wert eines Thermometer-Sensors oder None (Geraet meldet sich nicht mehr / keine Messung / keine Batteriemessung)."""
    d = get(str(sen.get("address") or ""))
    if not d or d.get("last_seen") is None:
        return None
    iv = int(d.get("interval") or DEFAULT_INTERVAL_MIN)
    if time.time() - d["last_seen"] > iv * 60 * MISSED_INTERVALS + 120:
        return None
    v = (d.get("last") or {}).get(sen.get("datapoint"))
    if v is None:
        return None
    if sen.get("datapoint") == "bat" and v < BAT_NO_MEASURE_V:
        return None
    return v


def battery_state(v) -> str:
    """Grobe Anzeige fuer Lithium-Zellen: 'ok' (> 3,1 V), 'low' (< 3,0 V, bald wechseln), 'warn' dazwischen; '' ohne Messung."""
    if not isinstance(v, (int, float)) or v < BAT_NO_MEASURE_V:
        return ""
    return "ok" if v > 3.1 else ("low" if v < 3.0 else "warn")
