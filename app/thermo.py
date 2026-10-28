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
import json
import os
import re
import secrets
import struct
import threading
import time
import zlib

import store

_DIR = os.path.dirname(os.path.abspath(__file__))
THERMO_PATH = os.path.join(_DIR, "thermo.json")
WIFI_PATH = os.path.join(_DIR, "thermo_wifi.json")          # gemerktes WLAN fuer weitere Thermometer (Name + Passwort), nur auf Wunsch des Administrators
CFG_SIZE, CFG_MAGIC, CFG_VER = 4096, b"BNXC", 1             # Konfigurations-Partition des Geraets (Format: src/config_store.h im Thermometer-Projekt)
_lock = threading.RLock()

DEFAULT_INTERVAL_MIN = 15
MISSED_INTERVALS = 3                # so viele Intervalle ohne Meldung: Geraet gilt als offline (Sensorwert = "nicht erreichbar")
BAT_NO_MEASURE_V = 1.0              # darunter ist keine Batteriemessung verdrahtet (USB-Betrieb liefert Zufallswerte, siehe Uebergabe-Notiz)
LIMITS = {"temp": (-60.0, 80.0), "hum": (0.0, 100.0)}
CAL_MAX_AGE_S = 300                 # Abgleich nur mit frischer Messung (das Geraet misst nach RESET sofort neu)
CAL_MAX_OFF = {"temp": 10.0, "hum": 30.0}   # groessere Abweichungen sind kein Messfehler des Sensors, sondern ein Hinweis auf eine falsche Referenz

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


def calibrate(tid: str, ref_temp=None, ref_hum=None, reset: bool = False) -> dict:
    """Abgleich auf Referenzwerte: Korrekturwert = Referenz - Rohwert der letzten Messung (nur wenn frisch). reset=True loescht den Abgleich.
    -> {"calib": {...}, "age_s": ...}; wirft ThermoError mit deutscher Meldung."""
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d:
            raise ThermoError("Thermometer nicht gefunden")
        if reset:
            d.pop("calib", None)
            _save(items)
            return {"calib": {"temp": None, "hum": None}, "age_s": None}
        last = d.get("last") or {}
        ls = d.get("last_seen")
        if ls is None or not last:
            raise ThermoError("Das Thermometer hat noch keine Messung gemeldet.")
        age = int(time.time() - ls)
        if age > CAL_MAX_AGE_S:
            raise ThermoError(f"Der letzte Messwert ist {age // 60} Minuten alt. Zum Abgleichen die RESET-Taste am Thermometer drücken (es misst sofort neu), warten bis es sich meldet und dann erneut versuchen.")
        cal = dict(d.get("calib") or {})
        given = False
        for key, ref, label, unit in (("temp", ref_temp, "Temperatur", "°C"), ("hum", ref_hum, "Luftfeuchte", "%")):
            if ref is None or ref == "":
                continue
            try:
                r = float(str(ref).replace(",", "."))
            except ValueError:
                raise ThermoError(f"{label}: bitte eine Zahl eintragen.")
            if key not in last:
                raise ThermoError(f"Für {label} liegt keine Messung vor.")
            off = round(r - float(last[key]), 2)
            if abs(off) > CAL_MAX_OFF[key]:
                raise ThermoError(f"{label}: Abweichung {off:+.1f} {unit} ist zu groß für einen Messfehler. Stimmt die Referenz, und hat das Thermometer lange genug neben der Referenz gelegen?")
            cal[key] = off
            given = True
        if not given:
            raise ThermoError("Bitte mindestens einen Referenzwert eintragen.")
        d["calib"] = cal
        _save(items)
    return {"calib": {"temp": cal.get("temp"), "hum": cal.get("hum")}, "age_s": age}


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


def rekey(tid: str, name: str | None = None, interval=None) -> tuple[dict, str] | None:
    """Vorhandenes Thermometer NEU einrichten (z. B. neu geflasht): behaelt ID, Sensoren, Aufzeichnung, Regeln, Abgleich. Es bekommt einen neuen Schluessel;
    der ALTE gilt weiter, bis sich das Geraet zum ersten Mal mit dem neuen meldet (schlaegt das Flashen fehl, laeuft das alte Geraet unveraendert weiter).
    -> (Geraet, Klartext-Schluessel) oder None, wenn es die ID nicht gibt."""
    token = new_token()
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d:
            return None
        d["pending_hash"] = _hash(token)
        d["low_n"] = 0
        d.pop("attempt", None)
        if name is not None and name.strip():
            d["name"] = name.strip()[:40]
        if interval is not None:
            d["interval"] = _interval(interval)
        _save(items)
        dev = dict(d)
    _make_sensors(dev)                                                  # fehlende Sensoren (falls einer geloescht wurde) wieder anlegen
    if name is not None and name.strip():
        rename(tid, name=name.strip())
    return public(dev), token


def public(dev: dict) -> dict:
    """Ohne Schluessel-Hash, mit Status fuer die Oberflaeche."""
    now = time.time()
    ls = dev.get("last_seen")
    iv = int(dev.get("interval") or DEFAULT_INTERVAL_MIN)
    run_iv = max(iv, int(dev.get("interval_ack") or 0))                  # Das Geraet laeuft noch mit dem zuletzt gemeldeten Intervall, bis es den neuen Wert geholt hat
    cal = dev.get("calib") or {}
    raw = dict(dev.get("last") or {})
    cor = dict(raw)
    if "temp" in cor:
        cor["temp"] = round(cor["temp"] + float(cal.get("temp") or 0), 2)
    if "hum" in cor:
        cor["hum"] = round(min(100.0, max(0.0, cor["hum"] + float(cal.get("hum") or 0))), 2)
    at = dev.get("attempt") or {}
    attempt = {"age_s": int(now - at["ts"]), "ip": at.get("ip", ""), "why": at.get("why", "")} if at.get("ts") and now - at["ts"] < 3600 else None
    return {"id": dev["id"], "name": dev.get("name") or dev["id"], "interval": iv, "created": dev.get("created"), "last_seen": ls, "fw": dev.get("fw"), "attempt": attempt,
            "age_s": None if ls is None else int(now - ls), "online": ls is not None and now - ls <= run_iv * 60 * MISSED_INTERVALS + 120,
            "last": cor, "raw": raw, "meta": dict(dev.get("meta") or {}), "calib": {"temp": cal.get("temp"), "hum": cal.get("hum")}, "sensors": [sensor_id(dev["id"], m) for m in METRICS]}


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


def remove(tid: str) -> bool:
    with _lock:
        items = _load()
        keep = [x for x in items if x.get("id") != tid]
        if len(keep) == len(items):
            return False
        _save(keep)
    try:                                                                  # offene Meldungen dieses Geraets abschliessen (sonst blieben sie im Meldungs-Zustand haengen)
        import notify
        notify.event("thermo_off:" + tid, False, "", None, flag="thermo_offline")
        notify.event("thermo_bat:" + tid, False, "", None, flag="thermo_battery")
    except Exception:                                                     # noqa: BLE001
        pass
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


def note_attempt(tid: str, ip: str, why: str) -> None:
    """Merkt sich den letzten gescheiterten Versuch eines BEKANNTEN Geraets (Diagnose: kommt die Anfrage an, und warum wurde sie abgelehnt?). Nur in der Anzeige, nie als Antwort an den Absender."""
    if not ID_RE.match(tid or ""):
        return
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        if not d:
            return
        d["attempt"] = {"ts": time.time(), "ip": str(ip)[:45], "why": why}
        _save(items)


def ingest(tid: str, token: str, body: dict, ip: str = "") -> tuple[int, dict]:
    """Messung annehmen. -> (HTTP-Status, Antwort). 401 = Schluessel falsch/Geraet unbekannt (gleiche Antwort, damit man IDs nicht abklopfen kann)."""
    if not ID_RE.match(tid or ""):
        return 401, {"error": "unauthorized"}
    if not token:
        note_attempt(tid, ip, "ohne Schlüssel")
        return 401, {"error": "unauthorized"}
    with _lock:
        items = _load()
        d = next((x for x in items if x.get("id") == tid), None)
        h = _hash(token) if d else ""
        is_new = bool(d) and bool(d.get("pending_hash")) and hmac.compare_digest(str(d["pending_hash"]), h)
        if not d or not (is_new or hmac.compare_digest(str(d.get("token_hash") or ""), h)):
            if d:
                d["attempt"] = {"ts": time.time(), "ip": str(ip)[:45], "why": "falscher Schlüssel"}
                _save(items)
            return 401, {"error": "unauthorized"}
        if not isinstance(body, dict):
            d["attempt"] = {"ts": time.time(), "ip": str(ip)[:45], "why": "keine gültigen Daten"}
            _save(items)
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
            d["low_n"] = (int(d.get("low_n") or 0) + 1) if battery_state(b) == "low" else 0       # Meldung "Batterie bald wechseln" erst nach 2 Meldungen in Folge
        r = _num(body.get("rssi"), -127.0, 0.0)
        if r is not None:
            last["rssi"] = r
        if not got:
            d["attempt"] = {"ts": time.time(), "ip": str(ip)[:45], "why": "keine gültigen Messwerte"}
            _save(items)
            return 400, {"error": "keine gueltigen Messwerte"}
        d["last"], d["last_seen"] = last, time.time()
        d.pop("attempt", None)
        if is_new:                                                            # das Geraet kennt den neuen Schluessel: der alte ist ab jetzt ungueltig
            d["token_hash"] = d.pop("pending_hash")
            d.pop("interval_ack", None)
        meta = dict(d.get("meta") or {})                                      # Diagnose ab Firmware 1.1: laufende Nummer der Aufwachen und Grund des Starts
        n = _num(body.get("n"), 0, 4294967295)
        rr = _num(body.get("rr"), 0, 20)
        if n is not None:
            meta["n"] = int(n)
        if rr is not None:
            meta["rr"] = int(rr)
        ap = str(body.get("ap") or "").strip().lower()                        # Access Point (BSSID) ab Firmware 1.1.1
        if re.match(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", ap):
            meta["ap"] = ap
        if meta:
            d["meta"] = meta
        fw = str(body.get("fw") or "")[:20]
        if fw:
            d["fw"] = fw
        interval = int(d.get("interval") or DEFAULT_INTERVAL_MIN)
        d["interval_ack"] = interval                                    # so schlaeft das Geraet ab jetzt (Grundlage fuer "meldet sich nicht mehr")
        _save(items)
    return 200, {"ok": True, "interval": interval}


def read_value(sen: dict):
    """Aktueller Wert eines Thermometer-Sensors oder None (Geraet meldet sich nicht mehr / keine Messung / keine Batteriemessung)."""
    d = get(str(sen.get("address") or ""))
    if not d or d.get("last_seen") is None:
        return None
    iv = max(int(d.get("interval") or DEFAULT_INTERVAL_MIN), int(d.get("interval_ack") or 0))
    if time.time() - d["last_seen"] > iv * 60 * MISSED_INTERVALS + 120:
        return None
    v = (d.get("last") or {}).get(sen.get("datapoint"))
    if v is None:
        return None
    if sen.get("datapoint") == "bat" and v < BAT_NO_MEASURE_V:
        return None
    off = float((d.get("calib") or {}).get(sen.get("datapoint")) or 0)             # Abgleich (nur Temperatur/Feuchte)
    if off and sen.get("datapoint") in ("temp", "hum"):
        v = v + off
        if sen.get("datapoint") == "hum":
            v = min(100.0, max(0.0, v))
    return v


IPV4_RE = re.compile(r"^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$")


def wifi_get() -> dict:
    d = store._load_json_recovering(WIFI_PATH, lambda: {})
    return d if isinstance(d, dict) and d.get("ssid") else {}


def wifi_set(ssid: str, password: str) -> None:
    store._dump_json(WIFI_PATH, {"ssid": ssid, "pass": password}, indent=1)


def wifi_clear() -> bool:
    try:
        os.remove(WIFI_PATH)
        return True
    except OSError:
        return False


def wifi_public() -> dict:
    """Fuer die Oberflaeche: Name des gemerkten WLANs - das Passwort verlaesst den Server nie."""
    w = wifi_get()
    return {"saved": bool(w), "ssid": w.get("ssid", ""), "has_pass": bool(w.get("pass"))}


def build_cfg(cfg: dict) -> bytes:
    """Konfigurations-Partition (4096 Byte): "BNXC", Version, Laenge, JSON, CRC32 - bytegleich zur Referenz make_cfg.py des Thermometer-Projekts."""
    payload = json.dumps(cfg, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > CFG_SIZE - 12:
        raise ThermoError("Konfiguration zu groß")
    blob = CFG_MAGIC + struct.pack("<BBH", CFG_VER, 0, len(payload)) + payload + struct.pack("<I", zlib.crc32(payload))
    return blob + b"\xff" * (CFG_SIZE - len(blob))


def check_wifi_input(ssid, password, server, ip) -> tuple:
    """Eingaben fuer die Konfiguration pruefen -> (ssid, passwort, server, ip oder None). Wirft ThermoError mit deutscher Meldung."""
    ssid = str(ssid or "")
    if not ssid.strip():
        raise ThermoError("Bitte den WLAN-Namen eintragen.")
    if len(ssid.encode("utf-8")) > 32:
        raise ThermoError("Der WLAN-Name ist zu lang (höchstens 32 Zeichen).")
    password = str(password or "")
    if password and not 8 <= len(password) <= 63:
        raise ThermoError("Das WLAN-Passwort muss 8 bis 63 Zeichen haben (oder leer bei einem offenen WLAN).")
    server = str(server or "").strip().rstrip("/")
    if not re.match(r"^http://[^/\s]+$", server):
        raise ThermoError("Die Adresse von BlueNexus muss so aussehen: http://192.168.x.x:5005 (nur http, ohne Pfad).")
    fixed = None
    if isinstance(ip, dict) and ip.get("addr"):
        a, g = str(ip.get("addr", "")).strip(), str(ip.get("gw", "")).strip()
        m = str(ip.get("mask") or "255.255.255.0").strip()
        d = str(ip.get("dns") or g).strip()
        if not all(IPV4_RE.match(x) for x in (a, g, m, d)):
            raise ThermoError("Feste IP: bitte gültige Adressen eintragen (z. B. 192.168.2.60).")
        fixed = {"addr": a, "gw": g, "mask": m, "dns": d}
    return ssid, password, server, fixed


def battery_state(v) -> str:
    """Grobe Anzeige fuer Lithium-Zellen: 'ok' (> 3,1 V), 'low' (< 3,0 V, bald wechseln), 'warn' dazwischen; '' ohne Messung."""
    if not isinstance(v, (int, float)) or v < BAT_NO_MEASURE_V:
        return ""
    return "ok" if v > 3.1 else ("low" if v < 3.0 else "warn")


# ---------------------------------------------------------------- Ueberwachung: Telegram/Pushover-Meldungen
BAT_LOW_CONFIRM = 2                 # so viele Meldungen in Folge mit Batterie unter 3,0 V, dann "bald wechseln"


def check_all(now: float | None = None) -> None:
    """Meldet per Telegram/Pushover (Einstellungen -> Meldungen): Thermometer meldet sich nicht mehr (3 Intervalle) bzw. wieder; Batterie bald wechseln (< 3,0 V, zweimal in Folge)."""
    import notify
    now = now or time.time()
    for d in load():
        iv = max(int(d.get("interval") or DEFAULT_INTERVAL_MIN), int(d.get("interval_ack") or 0))
        ls = d.get("last_seen")
        name = d.get("name") or d["id"]
        if ls is not None:                                      # frisch angelegte Thermometer ohne erste Meldung melden nichts
            silent_min = (now - ls) / 60.0
            offline = now - ls > iv * 60 * MISSED_INTERVALS + 120
            notify.event("thermo_off:" + d["id"], offline,
                         f"🌡️ Thermometer „{name}“ meldet sich seit {int(silent_min)} min nicht mehr (erwartet alle {iv} min). Batterie, WLAN oder Gerät prüfen.",
                         f"🌡️ Thermometer „{name}“ meldet sich wieder.", flag="thermo_offline")
        bat = (d.get("last") or {}).get("bat")
        low = int(d.get("low_n") or 0) >= BAT_LOW_CONFIRM and battery_state(bat) == "low"
        notify.event("thermo_bat:" + d["id"], low,
                     f"🔋 Thermometer „{name}“: Batterie bald wechseln ({str(round(bat, 2)).replace('.', ',') if isinstance(bat, (int, float)) else '?'} V).",
                     f"🔋 Thermometer „{name}“: Batterie wieder in Ordnung.", flag="thermo_battery")


_mon: dict = {"t": None}


def start_monitor(active=lambda: True, every_s: float = 60.0) -> None:
    """Hintergrundprozess: prueft jede Minute, ob ein Thermometer sich nicht mehr meldet oder die Batterie schwach ist."""
    if _mon["t"] is not None:
        return

    def loop():
        time.sleep(30)                                          # nach dem Start erst einmal Ruhe (Geraete melden sich erst wieder)
        while True:
            try:
                if active():
                    check_all()
            except Exception as e:                              # noqa: BLE001
                import logging
                logging.getLogger("thermo").warning("Thermometer-Überwachung: %s", e)
            time.sleep(every_s)

    _mon["t"] = threading.Thread(target=loop, name="thermo-monitor", daemon=True)
    _mon["t"].start()
