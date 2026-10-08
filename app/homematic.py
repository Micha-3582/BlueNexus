"""
Homematic / HomematicIP ueber die OpenCCU (auch RaspberryMatic / CCU3) - LOKAL per JSON-RPC
(`http://<ccu>/api/homematic.cgi`, gleiche Schnittstelle wie die CCU-Weboberflaeche selbst).
Keine Zusatzpakete (nur `requests`), keine Cloud.

Ablauf: Mit Benutzer/Passwort der CCU anmelden (`Session.login`), Geraete samt Namen/Raeumen holen
(`Device.listAllDetail`, `Room.getAll`), Schaltkanaele erkennen (Kanal mit schreibbarem `STATE` = Schalter,
mit schreibbarem `LEVEL` und Typ DIMMER = Dimmer) und lesen/schalten ueber `Interface.getValue` /
`Interface.setValue`. Leistung kommt - falls das Geraet misst - vom Messkanal desselben Geraets (`POWER`).

Jeder Schalt-/Dimmkanal ist ein eigener Eintrag (id = "hm-<adresse>", Adresse mit ":" -> "-").
Die Aufrufformen sind aus dem WebUI-Code der CCU abgelesen (webui.js): `valueKey`, `paramsetKey: "VALUES"`,
`type`/`value` bei setValue. Einschalten mit Sicherheits-Timer nutzt den Datenpunkt `ON_TIME` (Sekunden).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import socketserver
import threading
import time
import xmlrpc.client
from urllib.parse import quote
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer
from concurrent.futures import ThreadPoolExecutor

import requests

log = logging.getLogger("homematic")

CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic.json")
SENSORS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic_sensors.json")
CALL_TIMEOUT = 5.0
UNREACH_TTL_S = 30.0              # "Nicht erreichbar" je Geraet nur alle 30 s neu fragen (spart Aufrufe je Statusrunde)
SCAN_TTL_S = 900.0                # Suchergebnis so lange fuer "Hinzufuegen" merken
SKIP_INTERFACES = {"VirtualDevices"}     # CCU-Gruppen/Heizungsgruppen - keine echten Geraete

_http = requests.Session()
_lock = threading.Lock()
_session_id: dict[str, str] = {}                           # CCU-Basisadresse -> Sitzungs-ID
_unreach_cache: dict[tuple, tuple[float, bool]] = {}       # (interface, geraeteadresse) -> (gueltig bis, nicht erreichbar)
_scan_cache: dict[str, dict] = {}                          # adresse -> Kandidat
_scan_ts = 0.0
_sensor_scan: dict[str, dict] = {}                      # sensor-id -> Kandidat der letzten Sensor-Suche
_sensor_scan_ts = 0.0
_value_cache: dict[str, tuple[float, object]] = {}   # sensor-id -> (gueltig bis, Wert)
VALUE_TTL_S = 1.0
_pushed: dict[tuple, tuple[float, object]] = {}      # (schnittstelle, adresse, datenpunkt) -> (Zeit, Wert): Meldungen der CCU bzw. letzte Abfrage
PUSH_VALUE_TTL_S = 900.0          # mit Push gilt ein gemerkter Wert so lange; erst danach wird einmal nachgefragt (Sicherheitsnetz gegen verpasste Meldungen).
                                  # Bewusst lang: Ein Lese-Aufruf kann bei Netz-Aktoren (Burst) einen Funkbefehl ausloesen und fuellt den Duty Cycle der CCU
LATCH_MAX_S = 60.0                # kurze Impulse (Lichtschranke) merken: eine Meldung "aktiv" gilt fuer die Regeln noch so lange als nicht verpasst
POLL_VALUE_TTL_S = 10.0           # ohne Push: Werte so lange wiederverwenden (statt bei jeder Regelrunde/Seitenabfrage neu zu lesen)


class HomematicError(Exception):
    pass


# ---------------------------------------------------------------- Zugangsdaten
def load_credentials() -> dict:
    try:
        with open(CREDENTIALS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def credentials_public() -> dict:
    """Fuer die Einstellungen: ohne Passwort."""
    c = load_credentials()
    return {"configured": bool(c.get("host")), "host": c.get("host", ""), "user": c.get("user", ""),
            "password_set": bool(c.get("password"))}


def clear_credentials():
    """CCU-Zugang vergessen: Push-Anmeldung bei der CCU abmelden (solange die Adresse noch bekannt ist), dann Adresse, Benutzer, Passwort und alle
    Zwischenspeicher loeschen. Danach spricht die App die CCU nicht mehr an. Angelegte Homematic-Geraete bleiben in den Listen (ohne Zugang "nicht erreichbar")."""
    global _push_on
    c = load_credentials()
    if c.get("host"):
        try:
            _deinit_all(c)
        except Exception:                                 # noqa: BLE001 - CCU evtl. nicht erreichbar: trotzdem loeschen
            pass
    _push_on = False
    try:
        os.remove(CREDENTIALS_PATH)
    except FileNotFoundError:
        pass
    with _lock:
        _session_id.clear()
        _unreach_cache.clear()
        _value_cache.clear()
        _pushed.clear()
    _push_state.clear()
    _push_kick.set()


def _split_host(host: str) -> tuple[str, str]:
    """('http'|'https', ip) aus '192.168.2.22' bzw. 'https://192.168.2.22'. Nur private IPv4 (kein Web-Proxy-Missbrauch)."""
    raw = (host or "").strip().rstrip("/")
    scheme = "http"
    for s in ("https://", "http://"):
        if raw.lower().startswith(s):
            scheme, raw = s[:-3], raw[len(s):]
            break
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        raise HomematicError("Ungültige Adresse – bitte die IP der CCU eintragen, z. B. 192.168.2.22")
    if addr.version != 4 or not (addr.is_private and not addr.is_loopback):
        raise HomematicError("Nur IP-Adressen aus dem lokalen Netz erlaubt")
    return scheme, str(addr)


def save_credentials(host: str, user: str, password: str = ""):
    scheme, ip = _split_host(host)
    old = load_credentials()
    password = password or old.get("password", "")           # leer = unveraendert
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump({**old, "host": f"{scheme}://{ip}", "user": (user or "").strip(), "password": password}, f, indent=2)
    try:                                               # Zugangsdaten: nur der Besitzer darf lesen
        os.chmod(CREDENTIALS_PATH, 0o600)
    except OSError:
        pass
    with _lock:
        _session_id.clear()                                   # neue Zugangsdaten -> neu anmelden
        _unreach_cache.clear()


# ---------------------------------------------------------------- JSON-RPC
def _base(c: dict) -> str:
    if not c.get("host"):
        raise HomematicError("Homematic ist noch nicht eingerichtet (Smart Home → Geräte suchen → Homematic)")
    scheme, ip = _split_host(c["host"])
    return f"{scheme}://{ip}"


def _post(base: str, method: str, params: dict) -> dict:
    try:
        r = _http.post(f"{base}/api/homematic.cgi", json={"jsonrpc": "1.1", "method": method, "params": params, "id": 1},
                       timeout=CALL_TIMEOUT, verify=not base.startswith("https"))
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as e:
        raise HomematicError(f"CCU nicht erreichbar: {e}")
    if not isinstance(data, dict):
        raise HomematicError("Unerwartete Antwort der CCU")
    return data


def _login(c: dict, base: str) -> str:
    data = _post(base, "Session.login", {"username": c.get("user", ""), "password": c.get("password", "")})
    sid = data.get("result")
    if not sid or data.get("error"):
        raise HomematicError("Anmeldung an der CCU fehlgeschlagen – Benutzer und Passwort prüfen")
    with _lock:
        _session_id[base] = sid
    return sid


_paused_until = 0.0                      # Testpause: bis dahin spricht die App nicht mit der CCU (nur im Speicher, endet von selbst)
PAUSE_MAX_MIN = 60
_PAUSE_EXEMPT = ("Interface.listBidcosInterfaces",)            # die Diagnose selbst darf den Duty Cycle weiter lesen


def pause(minutes: float) -> float:
    """Zugriff auf die CCU fuer `minutes` Minuten sperren (Test: verursacht die App den Funkverkehr?). Rueckgabe: Sekunden Restzeit."""
    global _paused_until
    m = max(1.0, min(float(minutes), PAUSE_MAX_MIN))
    _paused_until = time.time() + m * 60
    return m * 60


def resume():
    global _paused_until
    _paused_until = 0.0


def paused_left() -> int:
    return max(0, int(_paused_until - time.time()))


def _call(method: str, params: dict | None = None):
    """JSON-RPC-Aufruf mit automatischer Anmeldung; bei abgelaufener Sitzung einmal neu anmelden."""
    if _paused_until and time.time() < _paused_until and method not in _PAUSE_EXEMPT:
        raise HomematicError(f"Homematic ist zum Test pausiert (noch {paused_left() // 60 + 1} Min) – Smart Home → Sonstiges → Funk-Diagnose")
    c = load_credentials()
    base = _base(c)
    for attempt in (0, 1):
        sid = _session_id.get(base) or _login(c, base)
        data = _post(base, method, {**(params or {}), "_session_id_": sid})
        err = data.get("error")
        if not err:
            _note_sent(method, params)
            return data.get("result")
        msg = str(err.get("message") or err) if isinstance(err, dict) else str(err)
        expired = "access denied" in msg.lower() or "session" in msg.lower()
        if attempt == 0 and expired:
            with _lock:
                _session_id.pop(base, None)
            continue
        raise HomematicError(f"CCU: {msg}")
    raise HomematicError("CCU: Anmeldung nicht möglich")


def test_connection() -> dict:
    """Anmelden und Geraeteanzahl zaehlen - fuer 'Zugang speichern & testen'."""
    devs = _call("Device.listAllDetail") or []
    real = [d for d in devs if d and d.get("interface") not in SKIP_INTERFACES]
    return {"devices": len(real)}


# ---------------------------------------------------------------- Suchen
def _param_desc(interface: str, address: str) -> dict[str, dict]:
    """VALUES-Parameter eines Kanals als {NAME: Beschreibung} (die CCU liefert eine Liste)."""
    res = _call("Interface.getParamsetDescription", {"interface": interface, "address": address, "paramsetKey": "VALUES"})
    if isinstance(res, dict):
        return {k: v for k, v in res.items() if isinstance(v, dict)}
    return {p.get("NAME"): p for p in (res or []) if isinstance(p, dict) and p.get("NAME")}


def _writable(p: dict | None) -> bool:
    try:
        return bool(p) and (int(p.get("OPERATIONS", 0)) & 2) == 2
    except (TypeError, ValueError):
        return False


def _is_default_name(name: str, address: str, dev_type: str) -> bool:
    n = (name or "").strip()
    return (not n) or address in n or n.startswith(dev_type)


def _probe_channel(item: dict) -> dict | None:
    """Prueft einen Kandidaten-Kanal; liefert den fertigen Eintrag oder None (nicht schaltbar)."""
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return None
    ctype = item["ctype"].upper()
    if "STATE" in desc and _writable(desc["STATE"]) and "BOOL" in str(desc["STATE"].get("TYPE", "")).upper():
        dp = "STATE"
    elif "DIMMER" in ctype and "LEVEL" in desc and _writable(desc["LEVEL"]):
        dp = "LEVEL"
    else:
        return None
    power_addr = ""
    for cand in item.get("power_candidates", []):
        try:
            if "POWER" in _param_desc(item["interface"], cand):
                power_addr = cand
                break
        except HomematicError:
            continue
    return {**{k: item[k] for k in ("address", "interface", "name", "model", "room", "channel")},
            "datapoint": dp, "power_addr": power_addr}


def discover(known_ids: set[str]) -> list[dict]:
    """Alle schaltbaren Kanaele der CCU (Schalter + Dimmer). Merkt sich das Ergebnis fuer `build_entries`."""
    global _scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or [])
               if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}                  # Kanal-ID -> Raumname (nicht kritisch)
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass                                    # Raumnamen sind nur Zierde - nie die Suche daran scheitern lassen
    items = []
    for dev in devices:
        chans = dev["channels"]
        dtype = str(dev.get("type") or "")
        power_candidates = [ch["address"] for ch in chans
                            if any(k in str(ch.get("channelType") or "").upper()
                                   for k in ("POWERMETER", "ENERGIE_METER", "ENERGY_METER"))]
        for ch in chans:
            ctype = str(ch.get("channelType") or "")
            up = ctype.upper()
            if not (("SWITCH" in up or "DIMMER" in up) and "TRANSMITTER" not in up and "SENSOR" not in up):
                continue
            addr = str(ch["address"])
            ch_name = str(ch.get("name") or "")
            dev_name = str(dev.get("name") or "")
            name = dev_name if _is_default_name(ch_name, addr, dtype) else ch_name
            items.append({"address": addr, "interface": dev["interface"], "ctype": ctype, "model": dtype,
                          "name": name or addr, "channel": ch.get("index"),
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), ""),
                          "power_candidates": power_candidates})
    with ThreadPoolExecutor(max_workers=8) as ex:
        found = [r for r in ex.map(_probe_channel, items) if r]
    found.sort(key=lambda f: (f["room"].lower(), f["name"].lower(), f["address"]))
    with _lock:
        _scan_cache.clear()
        _scan_cache.update({f["address"]: f for f in found})
        _scan_ts = time.time()
    for f in found:
        f["id"] = entry_id(f["address"])
        f["known"] = f["id"] in known_ids
    return found


# ---------------------------------------------------------------- Anlegen
def entry_id(address: str) -> str:
    return "hm-" + address.replace(":", "-")


def _icon_for(f: dict) -> str:
    n = f"{f.get('name', '')} {f.get('model', '')}".lower()
    if f["datapoint"] == "LEVEL" or any(w in n for w in ("licht", "lampe", "leuchte", "light", "led", "strahler")):
        return "💡"
    return "🔌"


def build_entries(addresses: list[str]) -> list[dict]:
    """Eintraege fuer die gewaehlten Adressen (aus dem letzten Suchergebnis; ist es alt, wird neu gesucht)."""
    if time.time() - _scan_ts > SCAN_TTL_S or any(a not in _scan_cache for a in addresses):
        discover(set())
    out = []
    for a in addresses:
        f = _scan_cache.get(a)
        if not f:
            raise HomematicError(f"Kanal {a} nicht gefunden (nicht schaltbar oder in der CCU entfernt)")
        out.append({"id": entry_id(a), "kind": "homematic", "address": a, "interface": f["interface"],
                    "datapoint": f["datapoint"], "power_addr": f["power_addr"], "mac": None, "gen": 0,
                    "channel": f["channel"], "model": f["model"], "name": f["name"], "room": f["room"],
                    "ip": a,                                   # Anzeige in der Geraeteliste: die CCU-Adresse
                    "icon": _icon_for(f)})
    return out


# ---------------------------------------------------------------- Werte lesen (Push-Wert, sonst CCU fragen)
def _get_value(interface: str, address: str, key: str):
    """Datenpunkt lesen. Ist der Push von der CCU aktiv und der Wert frisch (Meldung der CCU), kostet das keinen Aufruf;
    sonst wird die CCU gefragt (und der Wert gemerkt)."""
    hit = _pushed.get((interface, address, key))
    if hit and time.time() - hit[0] < (PUSH_VALUE_TTL_S if push_active() else POLL_VALUE_TTL_S):
        return hit[1]
    v = _call("Interface.getValue", {"interface": interface, "address": address, "valueKey": key})
    _pushed[(interface, address, key)] = (time.time(), v)
    return v


# ---------------------------------------------------------------- Status / Schalten
def _truthy(v) -> bool:
    """Wahrheitswert aus der CCU-Antwort - alte Funk-Geraete (BidCos) liefern teils Texte wie "false"/"0" statt echter Booleans."""
    if isinstance(v, str):
        return v.strip().lower() not in ("", "false", "0", "no", "off", "null", "none")
    return bool(v)


def _unreach(d: dict) -> bool:
    dev_addr = str(d["address"]).split(":")[0]
    key = (d["interface"], dev_addr)
    now = time.time()
    hit = _unreach_cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    try:
        v = _truthy(_get_value(d["interface"], dev_addr + ":0", "UNREACH"))
    except HomematicError:
        v = False                      # Kanal :0 nicht lesbar -> nicht als offline werten
    _unreach_cache[key] = (now + (PUSH_VALUE_TTL_S if push_active() else UNREACH_TTL_S), v)         # mit Push meldet die CCU Aenderungen selbst (UNREACH-Ereignis)
    return v


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': W|None}"""
    try:
        dp = d.get("datapoint", "STATE")
        v = _get_value(d["interface"], d["address"], dp)
        if _unreach(d):
            return {"online": False, "on": None, "power": None,
                    "error": "Die CCU meldet das Gerät als nicht erreichbar (UNREACH) – Funkverbindung/Strom prüfen"}
        on = _truthy(v) if dp == "STATE" else float(v or 0) > 0
        power = None
        if d.get("power_addr"):
            try:
                pv = _get_value(d["interface"], d["power_addr"], "POWER")
                power = None if pv is None else round(float(pv), 1)
            except (HomematicError, TypeError, ValueError):
                power = None
        return {"online": True, "on": on, "power": power}
    except (HomematicError, KeyError, TypeError, ValueError) as e:
        return {"online": False, "on": None, "power": None, "error": str(e) or e.__class__.__name__}


def _set_value(d: dict, key: str, typ: str, value):
    params = {"interface": d["interface"], "address": d["address"], "valueKey": key, "type": typ, "value": value}
    _pushed.pop((d["interface"], d["address"], key), None)          # gemerkter Wert ist ab jetzt ueberholt
    try:
        _call("Interface.setValue", params)
    except HomematicError:
        # Manche CCU-Staende erwarten Zahlen/Texte statt JSON-true/false - einmal in der anderen Schreibweise versuchen
        if typ == "bool":
            params["value"] = "1" if value else "0"
            _call("Interface.setValue", params)
        else:
            raise


def set_state(d: dict, on: bool, timer_s: int | None = None):
    """Schaltet/dimmt einen Kanal (Dimmer: 100 % bzw. aus). `timer_s` (nur Einschalten): eingebauter Rueckschalt-Timer
    des Geraets (`ON_TIME`, Sekunden) - nach Ablauf schaltet es von selbst aus; 0 hebt einen laufenden Timer auf."""
    dp = d.get("datapoint", "STATE")
    value = bool(on) if dp == "STATE" else (1.0 if on else 0.0)
    typ = "bool" if dp == "STATE" else "double"
    try:
        if on and timer_s is not None:
            # ON_TIME gemeinsam mit dem Einschalten schreiben (putParamset = eine Sendung); klappt das nicht
            # (z. B. Konto ohne Schreibrecht dafuer), wird ohne Timer geschaltet
            try:
                _call("Interface.putParamset", {
                    "interface": d["interface"], "address": d["address"], "paramsetKey": "VALUES",
                    "set": [{"name": "ON_TIME", "type": "double", "value": float(max(0, int(timer_s)))},
                            {"name": dp, "type": typ, "value": value}]})
            except HomematicError:
                _set_value(d, dp, typ, value)
        else:
            _set_value(d, dp, typ, value)
    except HomematicError as e:
        raise HomematicError(f"Schalten fehlgeschlagen: {e}")
    return status(d)


# ================================================================ Sensoren (nur lesen)
# Art -> (Anzeigename, Einheit, binaer?, [Datenpunkte in Reihenfolge der Vorliebe]).
# Binaere Sensoren liefern wahr/falsch und werden in den Regeln mit "TRUE/FALSE" benutzt, Messwerte mit unter/ueber.
SENSOR_KINDS = {
    "temperature": ("Temperatur", "°C", False, ["ACTUAL_TEMPERATURE", "TEMPERATURE"]),
    "humidity": ("Luftfeuchte", "%", False, ["HUMIDITY", "ACTUAL_HUMIDITY"]),
    "brightness": ("Helligkeit", "", False, ["ILLUMINATION", "BRIGHTNESS", "CURRENT_ILLUMINATION"]),
    "power": ("Leistung", "W", False, ["POWER"]),
    "contact": ("Fenster/Tür", "", True, ["STATE"]),                       # wahr = offen
    "motion": ("Bewegung", "", True, ["MOTION"]),                          # wahr = Bewegung erkannt
    "presence": ("Anwesenheit", "", True, ["PRESENCE_DETECTION_STATE"]),   # wahr = jemand da
    "key_short": ("Taste kurz gedrückt", "", True, ["PRESS_SHORT"]),       # Wandtaster/Fernbedienung: nur ueber den Push der CCU, kurz nach dem Druck TRUE (KEY_HOLD_S)
    "key_long": ("Taste lang gedrückt", "", True, ["PRESS_LONG"]),
    "key_long_release": ("Taste lang losgelassen", "", True, ["PRESS_LONG_RELEASE"]),     # manche Taster melden bei langem Druck nur das Loslassen
    "input": ("Eingang", "", True, ["STATE"]),                             # Eingangsmodule (z. B. HM-MOD-EM-8 mit Lichtschranke/Kontakt): wahr = Eingang aktiv
    "lock": ("Türschloss", "", True, ["LOCK_STATE"]),                      # wahr = verriegelt (HmIP-DLD: LOCK_STATE 1 = verriegelt, 2 = entriegelt)
}
# Welche kanaltypen zu welchen Sensorarten gehoeren koennen (Teilstrings des channelType)
_SENSOR_HINTS = [
    (("WEATHER", "CLIMATECONTROL", "THERMALCONTROL", "TEMPERATURE"), ("temperature", "humidity")),
    (("SHUTTER_CONTACT", "ROTARY_HANDLE", "WINDOW", "DOOR_SENSOR"), ("contact",)),
    (("MOTION_DETECTOR",), ("motion", "brightness")),
    (("PRESENCE_DETECTION",), ("presence", "brightness")),
    (("POWERMETER", "ENERGIE_METER", "ENERGY_METER"), ("power",)),
    (("LOCK",), ("lock",)),                                                   # Tuerschlossantrieb (nur Zustand lesen, nicht schalten)
    (("SWITCH_INTERFACE",), ("input",)),                                      # Funk-Sendemodule: jeder Kanal meldet seinen Eingang als STATE
]
# Zusaetzlich nach Geraetetyp (falls die CCU den Kanaltyp anders nennt)
KEY_CHANNEL_TYPES = ("KEY", "KEY_TRANSCEIVER", "MULTI_MODE_INPUT_TRANSMITTER")       # Tasterkanaele (genau, damit z. B. KEYMATIC oder VIRTUAL_KEY nicht passen)
KEY_HOLD_S = 5.0                  # so lange gilt ein Tastendruck als "gedrueckt" (laenger als der Regel-Takt von 2 s, damit er nie verpasst wird)
_SENSOR_DEVICE_HINTS = [(("HM-MOD-EM-8", "HM-SCI-3-FM"), ("input",))]


def load_sensors() -> list[dict]:
    try:
        with open(SENSORS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_sensors(items: list[dict]):
    with _lock, open(SENSORS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def reorder_sensors(ids: list[str]) -> None:
    """Neue Reihenfolge fuer die genannten Sensoren (sie belegen nur die Plaetze, die sie schon hatten)."""
    items = load_sensors()
    by_id = {s["id"]: s for s in items}
    ids = [i for i in ids if i in by_id]
    slots = sorted(n for n, s in enumerate(items) if s["id"] in set(ids))
    for slot, i in zip(slots, ids):
        items[slot] = by_id[i]
    _save_sensors(items)


def _reorder_items(items: list[dict], ids: list[str]) -> list[dict]:
    """Neue Reihenfolge fuer die genannten Eintraege (sie belegen nur die Plaetze, die sie schon hatten)."""
    by_id = {x["id"]: x for x in items}
    ids = [i for i in ids if i in by_id]
    slots = sorted(n for n, x in enumerate(items) if x["id"] in set(ids))
    for slot, i in zip(slots, ids):
        items[slot] = by_id[i]
    return items


def reorder_setpoints(ids: list[str]) -> None:
    _save_setpoints(_reorder_items(load_setpoints(), ids))


def reorder_locks(ids: list[str]) -> None:
    _save_locks(_reorder_items(load_locks(), ids))


def reorder_sounds(ids: list[str]) -> None:
    _save_sounds(_reorder_items(load_sounds(), ids))


def reorder_blinds(ids: list[str]) -> None:
    _save_blinds(_reorder_items(load_blinds(), ids))


def sensor_id(address: str, datapoint: str) -> str:
    return "hmS-" + address.replace(":", "-") + "-" + datapoint


def _probe_sensor_channel(item: dict) -> list[dict]:
    """Prueft einen Kandidaten-Kanal; liefert je lesbarem Datenpunkt einen Sensor-Eintrag."""
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return []
    out = []
    for kind in item["kinds"]:
        label, unit, binary, dps = SENSOR_KINDS[kind]
        need = 6 if kind.startswith("key_") else 1                      # Tasten: nur Meldung (Event) oder Schreiben, kein Lesen
        dp = next((d for d in dps if d in desc and (int(desc[d].get("OPERATIONS", 0) or 0) & need)), None)
        if not dp:
            continue
        if dp == "ILLUMINATION":
            unit = "lux"
        out.append({"id": sensor_id(item["address"], dp), "kind": kind, "address": item["address"],
                    "interface": item["interface"], "datapoint": dp, "unit": unit, "binary": binary,
                    "model": item["model"], "room": item["room"],
                    "name": f"{item['name']} – {label}"})
    return out


def discover_sensors(known_ids: set[str]) -> list[dict]:
    """Alle lesbaren Sensoren der CCU (Temperatur, Luftfeuchte, Fenster/Tuer, Bewegung, Anwesenheit, Helligkeit,
    Leistung). Merkt sich das Ergebnis fuer `build_sensors`."""
    global _sensor_scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or [])
               if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass
    items = []
    for dev in devices:
        dtype, dev_name = str(dev.get("type") or ""), str(dev.get("name") or "")
        for ch in dev["channels"]:
            up = str(ch.get("channelType") or "").upper()
            kinds = []
            for hints, ks in _SENSOR_HINTS:
                if any(h in up for h in hints):
                    kinds.extend(k for k in ks if k not in kinds)
            if up in KEY_CHANNEL_TYPES:
                kinds.extend(k for k in ("key_short", "key_long", "key_long_release") if k not in kinds)
            for hints, ks in _SENSOR_DEVICE_HINTS:
                if any(h in dtype.upper() for h in hints):
                    kinds.extend(k for k in ks if k not in kinds)
            if not kinds or "SWITCH_VIRTUAL" in up:
                continue
            addr, ch_name = str(ch["address"]), str(ch.get("name") or "")
            name = dev_name if _is_default_name(ch_name, addr, dtype) else ch_name
            items.append({"address": addr, "interface": dev["interface"], "kinds": kinds, "model": dtype,
                          "name": name or addr,
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), "")})
    with ThreadPoolExecutor(max_workers=8) as ex:
        found = [s for res in ex.map(_probe_sensor_channel, items) for s in res]
    found.sort(key=lambda f: (f["room"].lower(), f["name"].lower(), f["id"]))
    with _lock:
        _sensor_scan.clear()
        _sensor_scan.update({f["id"]: f for f in found})
        _sensor_scan_ts = time.time()
    for f in found:
        f["known"] = f["id"] in known_ids
    return found


def build_sensors(ids: list[str]) -> list[dict]:
    if time.time() - _sensor_scan_ts > SCAN_TTL_S or any(i not in _sensor_scan for i in ids):
        discover_sensors(set())
    out = []
    for i in ids:
        f = _sensor_scan.get(i)
        if not f:
            raise HomematicError("Sensor nicht gefunden (in der CCU entfernt?)")
        item = {k: f[k] for k in ("id", "kind", "address", "interface", "datapoint", "unit", "binary", "model", "room", "name")}
        if f["kind"] == "contact":
            item["invert"] = True                            # Standard fuer Fenster/Tueren: TRUE = geschlossen (gruen), FALSE = offen (rot); abwaehlbar
        out.append(item)
    return out


_edges: dict[tuple, dict] = {}                         # (Schnittstelle, Adresse, Datenpunkt) -> {"t": Zeit der letzten TRUE-Meldung, "f": ... FALSE} (nur beobachtete Geraete)
_latch_used: dict[str, int] = {}                       # Sensor-ID -> laufende Nummer der Meldungen, bis zu der ein Impuls den Regeln schon gemeldet wurde
_edge_seq = 0                                          # zaehlt jede beobachtete Meldung (genauer als Uhrzeiten)


def read_sensor(sen: dict, latch: bool = False):
    """Aktueller Wert: Zahl (Messwert), True/False (binaer) oder None (nicht lesbar/Geraet nicht erreichbar).
    latch=True (nur fuer die Regeln): Ein sehr kurzer Impuls (Lichtschranke: TRUE und gleich wieder FALSE) wird den Regeln trotzdem EINMAL als TRUE gemeldet,
    auch wenn er schon wieder vorbei ist, bevor die Regelschleife nachschaut. Die Anzeige (latch=False) bleibt unberuehrt."""
    val = _read_sensor_now(sen)
    if latch and sen.get("binary") and sen.get("source") not in ("zigbee", "camera") and not str(sen.get("kind", "")).startswith("key_") \
            and sen.get("datapoint") != "LOCK_STATE":
        now, sid = time.time(), sen["id"]
        if val is True or sid not in _latch_used:
            _latch_used[sid] = _edge_seq                      # laeuft gerade bzw. erste Abfrage (Ausgangspunkt): nichts nachzuliefern
        else:
            e = _edges.get((sen["interface"], sen["address"], sen["datapoint"])) or {}
            ts, seq = e.get("f" if sen.get("invert") else "t") or (0.0, 0)
            if seq and now - ts < LATCH_MAX_S and seq > _latch_used.get(sid, 0):
                _latch_used[sid] = _edge_seq
                return True
    return val


def _read_sensor_now(sen: dict):
    now = time.time()
    if str(sen.get("kind", "")).startswith("key_"):                    # Taste: TRUE, wenn die CCU in den letzten KEY_HOLD_S Sekunden einen Druck gemeldet hat (ohne Push: unbekannt)
        if not push_active():
            return None
        dps = [sen["datapoint"]] + (["PRESS_CONT"] if sen.get("kind") == "key_long" else [])      # "lang gedrueckt": auch PRESS_CONT (Taste wird gehalten) zaehlt - manche Taster melden PRESS_LONG nicht
        for dp in dps:
            ph = _pushed.get((sen["interface"], sen["address"], dp))
            if ph and now - ph[0] < KEY_HOLD_S and _truthy(ph[1]):
                return True
        return False
    hit = _value_cache.get(sen["id"])
    if hit and hit[0] > now and sen.get("source") != "camera":      # Kamera-Erkennung hat ihren eigenen kurzen Zwischenspeicher (0,5 s) - nicht noch eine Sekunde dazu
        return hit[1]
    try:
        if sen.get("source") == "zigbee":                      # Zigbee-Sensor (Phoscon/deCONZ) im selben Register
            import zigbee
            v = zigbee.read_value(sen)
            unreach = v is None
        elif sen.get("source") == "camera":                    # Reolink-Kamera: Bewegung/Person/Fahrzeug/Tier
            import camera
            v = camera.read_motion(sen)
            unreach = v is None
        else:
            v = _get_value(sen["interface"], sen["address"], sen["datapoint"])
            unreach = _unreach(sen)
        if unreach or v is None:
            val = None
        elif sen.get("binary"):
            if sen.get("datapoint") == "LOCK_STATE":                       # Aufzaehlung: 0 unbekannt, 1 verriegelt, 2 entriegelt (auch als Text)
                t = str(v).strip().upper()
                val = True if t in ("1", "LOCKED") else False if t in ("2", "UNLOCKED") else None
            else:
                val = _truthy(v) if isinstance(v, (bool, str)) and not str(v).strip().isdigit() else bool(float(v))          # Drehgriff: 0 zu, 1 gekippt, 2 offen -> offen = wahr
            if val is not None and sen.get("invert"):
                val = not val                              # Sensor andersherum verschaltet: Bedeutung von TRUE/FALSE vertauschen
        else:
            val = round(float(v), 1)
    except (HomematicError, KeyError, TypeError, ValueError):
        val = None
    _value_cache[sen["id"]] = (now + VALUE_TTL_S, val)
    return val


def read_values(sensors: list[dict], latch: bool = False) -> dict[str, object]:
    """{sensor-id: Wert} fuer mehrere Sensoren (parallel)."""
    if not sensors:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(sensors))) as ex:
        vals = list(ex.map(lambda s: read_sensor(s, latch), sensors))
    return {s["id"]: v for s, v in zip(sensors, vals)}


def sensors_scan() -> list[dict]:
    return discover_sensors({s["id"] for s in load_sensors()})


def add_sensors(ids: list[str]) -> list[dict]:
    """Legt die gewaehlten Sensoren an (schon vorhandene bleiben unveraendert)."""
    new = build_sensors(ids)
    items = load_sensors()
    have = {s["id"] for s in items}
    added = [{**s, "users": []} for s in new if s["id"] not in have]        # neu: zunaechst nur fuer Administratoren sichtbar
    _save_sensors(items + added)
    return added


def update_sensor(sensor_id_: str, name: str | None = None, show: bool | None = None, invert: bool | None = None,
                  icon: str | None = None) -> bool:
    items = load_sensors()
    for s in items:
        if s["id"] == sensor_id_:
            if name is not None:
                s["name"] = name.strip()[:60] or s["name"]
            if show is not None:
                s["show"] = bool(show)
            if icon is not None:
                icon = icon.strip()
                if 0 < len(icon) <= 12:
                    s["icon"] = icon
            if invert is not None:
                s["invert"] = bool(invert)
                _value_cache.pop(s["id"], None)           # neuer Wert gleich mit der neuen Bedeutung
            _save_sensors(items)
            return True
    return False


def remove_sensor(sensor_id_: str) -> bool:
    items = load_sensors()
    keep = [s for s in items if s["id"] != sensor_id_]
    if len(keep) == len(items):
        return False
    _save_sensors(keep)
    return True


def list_sensors_with_values(live: bool = True) -> list[dict]:
    """Angelegte Sensoren inkl. aktuellem Wert ('value': Zahl | True/False | None = nicht lesbar). live=False: ohne Abfrage (value immer None)."""
    items = load_sensors()
    vals = read_values(items) if live else {}
    return [{**s, "value": vals.get(s["id"])} for s in items]


# ================================================================ Thermostate (Solltemperatur setzen)
# Heizkoerper-/Wandthermostate (HmIP: SET_POINT_TEMPERATURE, BidCos: SET_TEMPERATURE). Eigenes Register, denn es sind keine Schalter.
# Regeln der Art "Ablauf" setzen damit die Solltemperatur ("alle Thermostate auf 25 Grad"); der Wert wird auf den Bereich des Geraets begrenzt
# (z. B. 0 Grad -> 4,5 Grad = "aus").
SETPOINTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic_setpoints.json")
_SETPOINT_KEYS = ("SET_POINT_TEMPERATURE", "SET_TEMPERATURE")
_SETPOINT_HINTS = ("CLIMATECONTROL", "THERMALCONTROL", "HEATING")
_setpoint_scan: dict[str, dict] = {}
_setpoint_scan_ts = 0.0


def load_setpoints() -> list[dict]:
    try:
        with open(SETPOINTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_setpoints(items: list[dict]):
    with _lock, open(SETPOINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def setpoint_id(address: str) -> str:
    return "hmT-" + address.replace(":", "-")


def _probe_setpoint_channel(item: dict) -> dict | None:
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return None
    for key in _SETPOINT_KEYS:
        p = desc.get(key)
        if _writable(p):
            try:
                lo, hi = float(p.get("MIN", 4.5)), float(p.get("MAX", 30.5))
            except (TypeError, ValueError):
                lo, hi = 4.5, 30.5
            return {**item, "id": setpoint_id(item["address"]), "datapoint": key, "min": lo, "max": hi}
    return None


def discover_setpoints(known_ids: set[str]) -> list[dict]:
    global _setpoint_scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or []) if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass
    items = []
    for dev in devices:
        dtype, dev_name = str(dev.get("type") or ""), str(dev.get("name") or "")
        for ch in dev["channels"]:
            up = str(ch.get("channelType") or "").upper()
            if not any(h in up for h in _SETPOINT_HINTS):
                continue
            addr, ch_name = str(ch["address"]), str(ch.get("name") or "")
            items.append({"address": addr, "interface": dev["interface"], "model": dtype,
                          "name": (dev_name if _is_default_name(ch_name, addr, dtype) else ch_name) or addr,
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), "")})
    with ThreadPoolExecutor(max_workers=8) as ex:
        found = [f for f in ex.map(_probe_setpoint_channel, items) if f]
    found.sort(key=lambda f: (f["room"].lower(), f["name"].lower(), f["id"]))
    with _lock:
        _setpoint_scan.clear()
        _setpoint_scan.update({f["id"]: f for f in found})
        _setpoint_scan_ts = time.time()
    for f in found:
        f["known"] = f["id"] in known_ids
    return found


def setpoints_scan() -> list[dict]:
    return discover_setpoints({s["id"] for s in load_setpoints()})


def add_setpoints(ids: list[str]) -> list[dict]:
    if time.time() - _setpoint_scan_ts > SCAN_TTL_S or any(i not in _setpoint_scan for i in ids):
        discover_setpoints(set())
    items = load_setpoints()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _setpoint_scan.get(i)
        if not f:
            raise HomematicError("Thermostat nicht gefunden (in der CCU entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "address", "interface", "datapoint", "min", "max", "model", "room", "name")}
        items.append(item)
        added.append(item)
    if added:
        _save_setpoints(items)
    return added


def update_setpoint(sp_id: str, name: str | None = None) -> bool:
    items = load_setpoints()
    for s in items:
        if s["id"] == sp_id:
            if name is not None:
                s["name"] = name.strip()[:60] or s["name"]
            _save_setpoints(items)
            return True
    return False


def remove_setpoint(sp_id: str) -> bool:
    items = load_setpoints()
    keep = [s for s in items if s["id"] != sp_id]
    if len(keep) == len(items):
        return False
    _save_setpoints(keep)
    return True


def list_setpoints_with_values(live: bool = True) -> list[dict]:
    """Thermostate inkl. aktueller Solltemperatur (None = nicht lesbar). live=False: ohne Abfrage."""
    items = load_setpoints()
    if not live:
        return [{**s, "value": None} for s in items]

    def cur(s):
        if s.get("source") == "zigbee":
            import zigbee
            return zigbee.read_setpoint(s)
        try:
            return round(float(_get_value(s["interface"], s["address"], s["datapoint"])), 1)
        except (HomematicError, TypeError, ValueError):
            return None
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(items)))) as ex:
        vals = list(ex.map(cur, items))
    return [{**s, "value": v} for s, v in zip(items, vals)]


def set_setpoints(ids: list[str], value: float) -> list[tuple]:
    """Solltemperatur setzen ('*' = alle angelegten Thermostate). Rueckgabe: [(name, gesetzter Wert, Fehlertext|None)]."""
    items = load_setpoints()
    chosen = items if "*" in ids else [s for s in items if s["id"] in ids]
    out = []
    for s in chosen:
        v = min(float(s.get("max", 30.5)), max(float(s.get("min", 4.5)), float(value)))
        if s.get("source") == "zigbee":
            import zigbee
            try:
                out.append((s["name"], zigbee.set_setpoint(s, value), None))
            except zigbee.ZigbeeError as e:
                out.append((s["name"], v, str(e)))
            continue
        try:
            _call("Interface.setValue", {"interface": s["interface"], "address": s["address"], "valueKey": s["datapoint"], "type": "double", "value": v})
            _pushed.pop((s["interface"], s["address"], s["datapoint"]), None)
            out.append((s["name"], v, None))
        except HomematicError as e:
            out.append((s["name"], v, str(e)))
    for i in ids:
        if i != "*" and not any(s["id"] == i for s in items):
            out.append((i, float(value), "Thermostat nicht mehr vorhanden"))
    return out


# ================================================================ Tuerschloesser (HmIP-DLD): verriegeln / entriegeln / oeffnen
# Eigenes Register. Sicherheit: Ein Schloss darf von Regeln nur ENTRIEGELT/GEOEFFNET werden, wenn dort ausdruecklich "allow_open" gesetzt ist
# (Standard: nein); Verriegeln ist immer erlaubt. Nur in Regeln der Art "Ablauf", nie im Trockenlauf.
LOCKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic_locks.json")
LOCK_LEVELS = {"lock": 0, "unlock": 1, "open": 2}        # LOCK_TARGET_LEVEL: 0 verriegeln, 1 entriegeln, 2 Tuer oeffnen (Falle ziehen)
_lock_scan: dict[str, dict] = {}
_lock_scan_ts = 0.0


def load_locks() -> list[dict]:
    try:
        with open(LOCKS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_locks(items: list[dict]):
    with _lock, open(LOCKS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def lock_id(address: str) -> str:
    return "hmK-" + address.replace(":", "-")


def _probe_lock_channel(item: dict) -> dict | None:
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return None
    if _writable(desc.get("LOCK_TARGET_LEVEL")):
        return {**item, "id": lock_id(item["address"])}
    return None


def discover_locks(known_ids: set[str]) -> list[dict]:
    global _lock_scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or []) if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass
    items = []
    for dev in devices:
        dtype, dev_name = str(dev.get("type") or ""), str(dev.get("name") or "")
        for ch in dev["channels"]:
            if "LOCK" not in str(ch.get("channelType") or "").upper():
                continue
            addr, ch_name = str(ch["address"]), str(ch.get("name") or "")
            items.append({"address": addr, "interface": dev["interface"], "model": dtype,
                          "name": (dev_name if _is_default_name(ch_name, addr, dtype) else ch_name) or addr,
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), "")})
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = [f for f in ex.map(_probe_lock_channel, items) if f]
    with _lock:
        _lock_scan.clear()
        _lock_scan.update({f["id"]: f for f in found})
        _lock_scan_ts = time.time()
    for f in found:
        f["known"] = f["id"] in known_ids
    return found


def locks_scan() -> list[dict]:
    return discover_locks({x["id"] for x in load_locks()})


def add_locks(ids: list[str]) -> list[dict]:
    if time.time() - _lock_scan_ts > SCAN_TTL_S or any(i not in _lock_scan for i in ids):
        discover_locks(set())
    items = load_locks()
    have = {x["id"] for x in items}
    added = []
    for i in ids:
        f = _lock_scan.get(i)
        if not f:
            raise HomematicError("Türschloss nicht gefunden (in der CCU entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "address", "interface", "model", "room", "name")}
        item["allow_open"] = False                         # Entriegeln/Oeffnen durch Regeln ist erst nach ausdruecklicher Freigabe moeglich
        items.append(item)
        added.append(item)
    if added:
        _save_locks(items)
    return added


def update_lock(lid: str, name: str | None = None, allow_open: bool | None = None) -> bool:
    items = load_locks()
    for x in items:
        if x["id"] == lid:
            if name is not None and name.strip():
                x["name"] = name.strip()[:60]
            if allow_open is not None:
                x["allow_open"] = bool(allow_open)
            _save_locks(items)
            return True
    return False


def remove_lock(lid: str) -> bool:
    items = load_locks()
    keep = [x for x in items if x["id"] != lid]
    if len(keep) == len(items):
        return False
    _save_locks(keep)
    return True


def lock_state(x: dict):
    """True = verriegelt, False = entriegelt, None = unbekannt/nicht lesbar."""
    try:
        t = str(_get_value(x["interface"], x["address"], "LOCK_STATE")).strip().upper()
        if _unreach(x):
            return None
        return True if t in ("1", "LOCKED") else False if t in ("2", "UNLOCKED") else None
    except (HomematicError, KeyError, TypeError, ValueError):
        return None


def list_locks_with_state(live: bool = True) -> list[dict]:
    items = load_locks()
    if not live:
        return [{**x, "locked": None} for x in items]
    return [{**x, "locked": lock_state(x)} for x in items]


def lock_action(lid: str, action: str) -> str:
    """'lock' | 'unlock' | 'open'. Entriegeln/Oeffnen nur mit Freigabe (allow_open). Rueckgabe: Name des Schlosses."""
    if action not in LOCK_LEVELS:
        raise HomematicError("Unbekannte Schloss-Aktion")
    x = next((y for y in load_locks() if y["id"] == lid), None)
    if not x:
        raise HomematicError("Türschloss existiert nicht mehr")
    if action != "lock" and not x.get("allow_open"):
        raise HomematicError(f"{x['name']}: Entriegeln/Öffnen durch Regeln ist nicht freigegeben (Smart Home → Sicherheit)")
    params = {"interface": x["interface"], "address": x["address"], "valueKey": "LOCK_TARGET_LEVEL", "value": LOCK_LEVELS[action]}
    _pushed.pop((x["interface"], x["address"], "LOCK_STATE"), None)
    try:
        _call("Interface.setValue", {**params, "type": "int"})
    except HomematicError:
        _call("Interface.setValue", {**params, "type": "integer"})            # manche CCU-Staende erwarten den langen Typnamen
    return x["name"]


# ================================================================ Soundmodule (Funk-Gong / Signalaktor akustisch, z. B. HM-OU-CM-PCB, HM-OU-CFM-TW)
# Eigenes Register. Abgespielt wird ueber den Datenpunkt SUBMIT des Tonkanals: "Lautstaerke,Wiederholungen,Dauer,Titelnummer"
# (Lautstaerke 0..1, Dauer 108000 = Titel vollstaendig abspielen). Nur in Regeln der Art "Ablauf" und im Test-Knopf, nie im Trockenlauf.
SOUNDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic_sounds.json")
SOUND_DURATION = 108000
SOUND_ICON = "🔔"
_sound_scan: dict[str, dict] = {}
_sound_scan_ts = 0.0


def load_sounds() -> list[dict]:
    try:
        with open(SOUNDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_sounds(items: list[dict]):
    with _lock, open(SOUNDS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def sound_users_registry():
    """(laden, speichern) der Soundmodule fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load_sounds, _save_sounds


def sound_id(address: str) -> str:
    return "hmA-" + address.replace(":", "-")


def _probe_sound_channel(item: dict) -> dict | None:
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return None
    if _writable(desc.get("SUBMIT")):
        return {**item, "id": sound_id(item["address"]), "icon": SOUND_ICON}
    return None


def discover_sounds(known_ids: set[str]) -> list[dict]:
    global _sound_scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or []) if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass
    items = []
    for dev in devices:
        dtype, dev_name = str(dev.get("type") or ""), str(dev.get("name") or "")
        for ch in dev["channels"]:
            up = str(ch.get("channelType") or "").upper()
            if "LED" in up or "MAINTENANCE" in up:
                continue
            if not (any(h in up for h in ("SOUND", "ACOUSTIC", "CHIME", "GONG", "SIGNAL")) or dtype.upper().startswith("HM-OU-C")):
                continue
            addr, ch_name = str(ch["address"]), str(ch.get("name") or "")
            items.append({"address": addr, "interface": dev["interface"], "model": dtype,
                          "name": (dev_name if _is_default_name(ch_name, addr, dtype) else ch_name) or addr,
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), "")})
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = [f for f in ex.map(_probe_sound_channel, items) if f]
    with _lock:
        _sound_scan.clear()
        _sound_scan.update({f["id"]: f for f in found})
        _sound_scan_ts = time.time()
    for f in found:
        f["known"] = f["id"] in known_ids
    return found


def sounds_scan() -> list[dict]:
    return discover_sounds({x["id"] for x in load_sounds()})


def add_sounds(ids: list[str]) -> list[dict]:
    if time.time() - _sound_scan_ts > SCAN_TTL_S or any(i not in _sound_scan for i in ids):
        discover_sounds(set())
    items = load_sounds()
    have = {x["id"] for x in items}
    added = []
    for i in ids:
        f = _sound_scan.get(i)
        if not f:
            raise HomematicError("Soundmodul nicht gefunden (in der CCU entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "address", "interface", "model", "room", "name")}
        item["icon"] = SOUND_ICON
        item["users"] = []                            # neu: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(item)
        added.append(item)
    if added:
        _save_sounds(items)
    return added


def update_sound(sid: str, name: str | None = None, icon: str | None = None) -> bool:
    items = load_sounds()
    for x in items:
        if x["id"] == sid:
            if name is not None and name.strip():
                x["name"] = name.strip()[:60]
            if icon is not None and 0 < len(icon.strip()) <= 12:
                x["icon"] = icon.strip()
            _save_sounds(items)
            return True
    return False


def remove_sound(sid: str) -> bool:
    items = load_sounds()
    keep = [x for x in items if x["id"] != sid]
    if len(keep) == len(items):
        return False
    _save_sounds(keep)
    return True


def sound_params(track, volume=100, repeats=1) -> tuple[int, int, int]:
    """Prueft Titelnummer (1-255), Lautstaerke (0-100 %), Wiederholungen (1-20)."""
    try:
        t, v, r = int(float(track)), float(volume), int(float(repeats))
    except (TypeError, ValueError):
        raise HomematicError("Sound: Titel, Lautstärke und Wiederholungen müssen Zahlen sein")
    if not 1 <= t <= 255:
        raise HomematicError("Sound: Titelnummer zwischen 1 und 255")
    if not 0 <= v <= 100:
        raise HomematicError("Sound: Lautstärke zwischen 0 und 100 %")
    if not 1 <= r <= 20:
        raise HomematicError("Sound: Wiederholungen zwischen 1 und 20")
    return t, int(round(v)), r


def sound_value(track, volume=100, repeats=1) -> str:
    t, v, r = sound_params(track, volume, repeats)
    return f"{v / 100:g},{r},{SOUND_DURATION},{t}"


def sound_play(sid: str, track, volume=100, repeats=1) -> str:
    """Spielt Titel `track` auf dem Soundmodul. Rueckgabe: Name des Moduls."""
    value = sound_value(track, volume, repeats)
    x = next((y for y in load_sounds() if y["id"] == sid), None)
    if not x:
        raise HomematicError("Soundmodul existiert nicht mehr")
    _call("Interface.setValue", {"interface": x["interface"], "address": x["address"], "valueKey": "SUBMIT", "type": "string", "value": value})
    return x["name"]


# ================================================================ Rollladen / Jalousien (z. B. HM-LC-Bl1PBU-FM, HmIP-BROLL)
# Eigenes Register. Position = Datenpunkt LEVEL (CCU: 0.0 = ganz zu ... 1.0 = ganz auf; hier immer in Prozent: 0 % zu, 100 % auf), Anhalten = STOP.
# Bedienen auf der Seite (Smart Home -> Aktoren) und als Schritt "Rollladen" in Regeln der Art "Ablauf" (nie im Trockenlauf).
BLINDS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "homematic_blinds.json")
BLIND_ICON = "🪟"
_blind_scan: dict[str, dict] = {}
_blind_scan_ts = 0.0


def load_blinds() -> list[dict]:
    try:
        with open(BLINDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_blinds(items: list[dict]):
    with _lock, open(BLINDS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def blind_users_registry():
    """(laden, speichern) der Rollladen fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load_blinds, _save_blinds


def blind_id(address: str) -> str:
    return "hmR-" + address.replace(":", "-")


def _probe_blind_channel(item: dict) -> dict | None:
    try:
        desc = _param_desc(item["interface"], item["address"])
    except HomematicError:
        return None
    if _writable(desc.get("LEVEL")) and _writable(desc.get("STOP")):          # Dimmer haben kein STOP
        return {**item, "id": blind_id(item["address"]), "icon": BLIND_ICON}
    return None


def discover_blinds(known_ids: set[str]) -> list[dict]:
    global _blind_scan_ts
    devices = [d for d in (_call("Device.listAllDetail") or []) if d and d.get("interface") not in SKIP_INTERFACES and d.get("channels")]
    rooms: dict[str, str] = {}
    try:
        for room in _call("Room.getAll") or []:
            for cid in room.get("channelIds") or []:
                rooms[str(cid)] = room.get("name") or ""
    except (HomematicError, AttributeError, TypeError):
        pass
    items = []
    for dev in devices:
        dtype, dev_name = str(dev.get("type") or ""), str(dev.get("name") or "")
        for ch in dev["channels"]:
            up = str(ch.get("channelType") or "").upper()
            if not any(h in up for h in ("BLIND", "SHUTTER", "ROLLER", "JALOUS", "COVER")):
                continue
            addr, ch_name = str(ch["address"]), str(ch.get("name") or "")
            items.append({"address": addr, "interface": dev["interface"], "model": dtype,
                          "name": (dev_name if (_is_default_name(ch_name, addr, dtype) or (dev_name and ch_name.startswith(dev_name + ":"))) else ch_name) or addr,
                          "room": rooms.get(str(ch.get("id")), "") or rooms.get(str(dev.get("id")), "")})
    with ThreadPoolExecutor(max_workers=4) as ex:
        found = [f for f in ex.map(_probe_blind_channel, items) if f]
    with _lock:
        _blind_scan.clear()
        _blind_scan.update({f["id"]: f for f in found})
        _blind_scan_ts = time.time()
    for f in found:
        f["known"] = f["id"] in known_ids
    return found


def blinds_scan() -> list[dict]:
    return discover_blinds({x["id"] for x in load_blinds()})


def add_blinds(ids: list[str]) -> list[dict]:
    if time.time() - _blind_scan_ts > SCAN_TTL_S or any(i not in _blind_scan for i in ids):
        discover_blinds(set())
    items = load_blinds()
    have = {x["id"] for x in items}
    added = []
    for i in ids:
        f = _blind_scan.get(i)
        if not f:
            raise HomematicError("Rollladen nicht gefunden (in der CCU entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "address", "interface", "model", "room", "name")}
        item["icon"] = BLIND_ICON
        item["users"] = []                            # neu: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(item)
        added.append(item)
    if added:
        _save_blinds(items)
    return added


def update_blind(bid: str, name: str | None = None, icon: str | None = None) -> bool:
    items = load_blinds()
    for x in items:
        if x["id"] == bid:
            if name is not None and name.strip():
                x["name"] = name.strip()[:60]
            if icon is not None and 0 < len(icon.strip()) <= 12:
                x["icon"] = icon.strip()
            _save_blinds(items)
            return True
    return False


def remove_blind(bid: str) -> bool:
    items = load_blinds()
    keep = [x for x in items if x["id"] != bid]
    if len(keep) == len(items):
        return False
    _save_blinds(keep)
    return True


def blind_level(x: dict):
    """Position in Prozent (0 = zu, 100 = auf) oder None (nicht lesbar/Geraet nicht erreichbar)."""
    try:
        v = _get_value(x["interface"], x["address"], "LEVEL")
        if _unreach(x):
            return None
        return int(round(max(0.0, min(1.0, float(v))) * 100))
    except (HomematicError, KeyError, TypeError, ValueError):
        return None


def list_blinds_with_level(live: bool = True) -> list[dict]:
    items = load_blinds()
    if not live:
        return [{**x, "level": None} for x in items]
    with ThreadPoolExecutor(max_workers=min(6, len(items) or 1)) as ex:
        levels = list(ex.map(blind_level, items))
    return [{**x, "level": lv} for x, lv in zip(items, levels)]


def blind_check_level(level) -> int:
    try:
        v = float(level)
    except (TypeError, ValueError):
        raise HomematicError("Rollladen: Position muss eine Zahl von 0 bis 100 sein")
    if not 0 <= v <= 100:
        raise HomematicError("Rollladen: Position zwischen 0 % (zu) und 100 % (auf)")
    return int(round(v))


def _blind_item(bid: str) -> dict:
    x = next((y for y in load_blinds() if y["id"] == bid), None)
    if not x:
        raise HomematicError("Rollladen existiert nicht mehr")
    return x


def blind_set(bid: str, level) -> str:
    """Faehrt den Rollladen auf `level` Prozent (0 zu, 100 auf). Rueckgabe: Name."""
    pct = blind_check_level(level)
    x = _blind_item(bid)
    _call("Interface.setValue", {"interface": x["interface"], "address": x["address"], "valueKey": "LEVEL", "type": "double", "value": pct / 100})
    _pushed.pop((x["interface"], x["address"], "LEVEL"), None)
    return x["name"]


def blind_stop(bid: str) -> str:
    """Haelt den Rollladen an. Rueckgabe: Name."""
    x = _blind_item(bid)
    _call("Interface.setValue", {"interface": x["interface"], "address": x["address"], "valueKey": "STOP", "type": "bool", "value": True})
    _pushed.pop((x["interface"], x["address"], "LEVEL"), None)
    return x["name"]


# ================================================================ Funk-Diagnose (Duty Cycle: wer fuellt den Funk?)
# Zaehlt (nur im Speicher) alle Meldungen der CCU (Push) und alle Befehle, die diese App an die CCU schickt - damit sich zeigen laesst, welches Geraet
# viel funkt und ob die App selbst (z. B. Sicherheits-Timer) viel sendet. Den Duty Cycle selbst liefert das Funkmodul der CCU (BidCos-RF).
TRAFFIC_WINDOW_S = 600.0                 # Meldungen der CCU: letzte 10 Minuten
SENT_WINDOW_S = 3600.0                   # Befehle der App: letzte Stunde
_traffic: list = []                      # (Zeit, Geraeteadresse, Datenpunkt) - ohne PONG
_sent: list = []                         # (Zeit, Geraeteadresse, Art) - Art: "timer" (Sicherheits-Timer/ON_TIME) | "befehl"
_reads: list = []                        # (Zeit, Geraeteadresse) - Lese-Aufrufe der App an die CCU (getValue)
_cmd_log: list = []                      # letzte Befehle: {ts, address, what}
TRAFFIC_MAX = 6000
BURST_GAP_S = 1.5                        # Werte desselben Geraetes im Abstand von weniger als 1,5 s = ein Funktelegramm
_traffic_since = time.time()              # seit wann gezaehlt wird (App-Start) - Grundlage fuer Meldungen pro Minute


def _note_traffic(base: str, key: str, now: float):
    _traffic.append((now, base, key))
    if len(_traffic) > TRAFFIC_MAX:
        del _traffic[:len(_traffic) - TRAFFIC_MAX]


def _note_sent(method: str, params: dict | None):
    """Befehl/Lese-Aufruf an die CCU gezaehlt (von _call aufgerufen)."""
    p = params or {}
    if method == "Interface.getValue":
        _reads.append((time.time(), str(p.get("address") or "?").split(":")[0]))
        del _reads[:-TRAFFIC_MAX]
        return
    if method not in ("Interface.setValue", "Interface.putParamset"):
        return
    timer = method == "Interface.putParamset" and any((x or {}).get("name") == "ON_TIME" for x in (p.get("set") or []))
    _sent.append((time.time(), str(p.get("address") or "?").split(":")[0], "timer" if timer else "befehl"))
    del _sent[:-TRAFFIC_MAX]
    what = ("Timer + " if timer else "") + (", ".join(f"{x.get('name')}={x.get('value')}" for x in (p.get("set") or []) if x.get("name") != "ON_TIME") if method == "Interface.putParamset"
                                           else f"{p.get('valueKey')}={p.get('value')}")
    _cmd_log.append({"ts": time.time(), "address": str(p.get("address") or "?"), "what": what[:80]})
    del _cmd_log[:-40]


def _device_names() -> dict[str, str]:
    """Geraeteadresse (ohne Kanal) -> bekannter Name aus allen Registern."""
    import shelly
    names: dict[str, str] = {}
    regs = [d for d in shelly.load_devices() if d.get("kind") == "homematic"] + load_sensors() + load_locks() + load_sounds() + load_blinds() + load_setpoints()
    for x in regs:
        a = str(x.get("address") or "").split(":")[0]
        if a and x.get("name") and a not in names:
            names[a] = x["name"]
    return names


def _duty_cycles() -> tuple[list[dict], str]:
    """Duty Cycle der BidCos-Funkmodule (0-100 %). Rueckgabe: (Liste, Fehlertext). Das HmIP-Funkmodul meldet keinen Wert dafuer."""
    try:
        res = _call("Interface.listBidcosInterfaces", {"interface": "BidCos-RF"})
    except HomematicError as e:
        return [], str(e)
    out = []
    for it in res if isinstance(res, list) else []:
        if not isinstance(it, dict):
            continue
        low = {str(k).lower(): v for k, v in it.items()}
        dc = next((low[k] for k in ("dutycycle", "duty_cycle") if k in low), None)
        try:
            dc = None if dc is None else int(round(float(dc)))
        except (TypeError, ValueError):
            dc = None
        out.append({"name": str(low.get("description") or low.get("address") or "Funkmodul"), "address": str(low.get("address") or ""),
                    "duty": dc, "connected": bool(low["connected"]) if "connected" in low else None})
    return out, "" if out else "Die CCU meldet keine BidCos-Funkmodule (oder keinen Duty Cycle)."


def radio_report() -> dict:
    """Alles fuer die Funk-Diagnose: Duty Cycle, gespraechigste Geraete (Meldungen der CCU) und Befehle der App."""
    now = time.time()
    names = _device_names()
    duty, duty_err = _duty_cycles()
    recent = [t for t in _traffic if now - t[0] <= TRAFFIC_WINDOW_S]
    per: dict[str, dict] = {}
    for ts, base, key in sorted(recent):
        e = per.setdefault(base, {"count": 0, "keys": {}, "bursts": 0, "last": None})
        e["count"] += 1
        e["keys"][key] = e["keys"].get(key, 0) + 1
        if e["last"] is None or ts - e["last"] > BURST_GAP_S:        # ein Telegramm enthaelt meist mehrere Werte (Temperatur, Soll, Modus, Ventil ...)
            e["bursts"] += 1
        e["last"] = ts
    span = min(TRAFFIC_WINDOW_S, max(30.0, now - _traffic_since))          # kurz nach dem Start nicht durch zu wenig Zeit teilen
    minutes = span / 60.0
    devices = sorted(({"address": b, "name": names.get(b, ""), "count": e["count"], "telegrams": e["bursts"], "per_min": round(e["bursts"] / minutes, 1),
                       "top_key": max(e["keys"], key=e["keys"].get),
                       "top_keys": [f"{k} ×{n}" for k, n in sorted(e["keys"].items(), key=lambda kv: -kv[1])[:3]]} for b, e in per.items()),
                     key=lambda d: (-d["telegrams"], -d["count"]))[:12]
    sent = [t for t in _sent if now - t[0] <= SENT_WINDOW_S]
    sdev: dict[str, int] = {}
    for _, base, _kind in sent:
        sdev[base] = sdev.get(base, 0) + 1
    top_sent = [{"address": b, "name": names.get(b, ""), "count": n} for b, n in sorted(sdev.items(), key=lambda kv: -kv[1])[:6]]
    rd = [t for t in _reads if now - t[0] <= TRAFFIC_WINDOW_S]
    rdev: dict[str, int] = {}
    for _, base in rd:
        rdev[base] = rdev.get(base, 0) + 1
    reads = {"total": len(rd), "per_min": round(len(rd) / minutes, 1),
             "top": [{"address": b, "name": names.get(b, ""), "count": n} for b, n in sorted(rdev.items(), key=lambda kv: -kv[1])[:6]]}
    cmds = [{"ts": c["ts"], "address": c["address"], "name": names.get(c["address"].split(":")[0], ""), "what": c["what"]} for c in reversed(_cmd_log[-15:])]
    return {"push": push_active(), "paused_s": paused_left(), "reads": reads, "commands": cmds, "duty": duty, "duty_error": duty_err, "window_min": int(TRAFFIC_WINDOW_S // 60), "counted_min": round(span / 60.0, 1), "events": len(recent),
            "devices_seen": len(per), "devices": devices,
            "sent": {"total": len(sent), "timer": sum(1 for t in sent if t[2] == "timer"), "top": top_sent}}


# ================================================================ Push: XML-RPC-Rueckkanal der CCU (wie ioBroker hm-rpc)
# Die App meldet sich per `init` bei den Funk-Schnittstellen der CCU an; die CCU schickt dann nur bei Aenderungen ein `event`.
# Faellt der Rueckkanal aus (Port gesperrt, CCU neu gestartet ...), fragt die App wie bisher ab - die Regeln laufen immer weiter.
PUSH_PORT_DEFAULT = 8703
PUSH_ID_PREFIX = "victron-"
PUSH_CYCLE_S = 30.0               # Anmeldung pruefen / ping
PUSH_INIT_EVERY_S = 300.0         # Anmeldung alle 5 Minuten auffrischen
PUSH_ALIVE_MAX_S = 100.0          # laenger keine Meldung (auch kein PONG) = Rueckkanal gilt als ausgefallen
RPC_PORTS = {"BidCos-RF": 2001, "HmIP-RF": 2010, "BidCos-Wired": 2000}
NOISY_KEYS = {"POWER", "ENERGY_COUNTER", "FREQUENCY", "VOLTAGE", "CURRENT", "RSSI_DEVICE", "RSSI_PEER", "PONG"}     # wecken die Regeln nicht
_push_on = False
_push_state: dict[str, dict] = {}
_push_server = None
_push_server_port = 0
_push_thread = None
_push_stop = threading.Event()
_push_kick = threading.Event()
_inited: dict[str, str] = {}                              # schnittstelle -> url, mit der sie angemeldet ist
_watch: set[str] = set()                                  # Geraeteadressen, die aktive Regeln brauchen
_listeners: list = []
_recent_events: list = []                                 # letzte Meldungen der CCU (zur Fehlersuche): (Zeit, Schnittstelle, Adresse, Datenpunkt, Wert)
RECENT_EVENTS_MAX = 80
_last_wake = 0.0
_events_seen = 0


def add_listener(fn):
    """fn() wird aufgerufen, wenn die CCU eine fuer Regeln relevante Aenderung meldet."""
    _listeners.append(fn)


def set_watch(addresses):
    global _watch
    _watch = {str(a).split(":")[0] for a in addresses}


def recent_events() -> list[dict]:
    """Letzte Meldungen der CCU, neueste zuerst; bekannte Sensoren/Geraete mit Namen (zur Fehlersuche bei Tasten)."""
    names = {(s.get("address"), s.get("datapoint")): s.get("name") for s in load_sensors()}
    out = []
    for ts, iface, addr, key, val in reversed(_recent_events):
        out.append({"ts": ts, "interface": iface, "address": addr, "key": key, "value": val if isinstance(val, (bool, int, float, str)) else str(val),
                    "sensor": names.get((addr, key)) or ""})
    return out


def push_active() -> bool:
    if not _push_on:
        return False
    now = time.time()
    return any(st.get("ok") and now - st.get("ts", 0) < 3 * PUSH_CYCLE_S for st in _push_state.values())


def _on_event(interface_id, address, key, value):
    global _events_seen, _last_wake, _edge_seq
    iface = str(interface_id)
    iface = iface[len(PUSH_ID_PREFIX):] if iface.startswith(PUSH_ID_PREFIX) else iface
    now = time.time()
    _push_state.setdefault(iface, {})["alive"] = now
    _events_seen += 1
    if key == "PONG":
        return ""
    address, key = str(address), str(key)
    _note_traffic(address.split(":")[0], key, now)
    _pushed[(iface, address, key)] = (now, value)
    if key not in NOISY_KEYS:
        _recent_events.append((now, iface, address, key, value))
        del _recent_events[:-RECENT_EVENTS_MAX]
    base = address.split(":")[0]
    if key == "UNREACH":
        _unreach_cache[(iface, base)] = (now + PUSH_VALUE_TTL_S, _truthy(value))
    if base in _watch and key not in NOISY_KEYS:
        _edge_seq += 1
        _edges.setdefault((iface, address, key), {})["t" if _truthy(value) else "f"] = (now, _edge_seq)      # auch ein Impuls, der gleich wieder endet, bleibt fuer die Regeln sichtbar
        _value_cache.clear()                              # Sensorwerte neu lesen (aus dem Push-Speicher)
        if now - _last_wake >= 0.3:
            _last_wake = now
            for fn in list(_listeners):
                try:
                    fn()
                except Exception:                         # noqa: BLE001
                    pass
    return ""


class _Handler(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/", "/RPC2")

    def do_POST(self):
        try:
            allowed = _split_host(load_credentials().get("host", ""))[1]
        except HomematicError:
            allowed = None
        if self.client_address[0] != allowed:             # nur die CCU selbst darf melden
            self.send_error(403)
            return
        super().do_POST()

    def log_message(self, *a):
        pass


class _Server(socketserver.ThreadingMixIn, SimpleXMLRPCServer):
    daemon_threads = True
    allow_reuse_address = True


def _make_server(port: int):
    srv = _Server(("0.0.0.0", port), requestHandler=_Handler, allow_none=True, logRequests=False)
    srv.register_introspection_functions()
    srv.register_multicall_functions()                    # die CCU schickt Meldungen gebuendelt (system.multicall)
    srv.register_function(_on_event, "event")
    srv.register_function(lambda *a: [], "listDevices")
    for name in ("newDevices", "deleteDevices", "updateDevice", "replaceDevice", "readdedDevice"):
        srv.register_function(lambda *a: "", name)
    return srv


def _ensure_listener(port: int):
    global _push_server, _push_server_port
    if _push_server and _push_server_port == port:
        return
    if _push_server:
        _push_server.shutdown()
        _push_server.server_close()
        _push_server = None
    srv = _make_server(port)                              # OSError (Port belegt) geht an den Aufrufer
    threading.Thread(target=srv.serve_forever, daemon=True, name="homematic-push").start()
    _push_server, _push_server_port = srv, port


class _TimeoutTransport(xmlrpc.client.Transport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = CALL_TIMEOUT
        return conn


def _proxy(c: dict, ip: str, rpc_port: int):
    auth = f"{quote(c.get('user', ''), safe='')}:{quote(c.get('password', ''), safe='')}@" if c.get("user") else ""
    return xmlrpc.client.ServerProxy(f"http://{auth}{ip}:{rpc_port}", transport=_TimeoutTransport(), allow_none=True)


def _local_ip(ccu_ip: str) -> str:
    """Eigene Adresse im Netz der CCU (die CCU ruft uns unter dieser Adresse zurueck)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ccu_ip, 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _known_interfaces() -> set[str]:
    import shelly
    out = {d.get("interface") for d in shelly.load_devices() if d.get("kind") == "homematic"}
    out |= {s.get("interface") for s in load_sensors() if s.get("source") not in ("zigbee", "camera")}
    return {i for i in out if i}


def _push_port(c: dict) -> int:
    try:
        return int(c.get("push_port") or PUSH_PORT_DEFAULT)
    except (TypeError, ValueError):
        return PUSH_PORT_DEFAULT


def _deinit_all(c: dict):
    if not _inited:
        return
    try:
        ip = _split_host(c.get("host", ""))[1]
    except HomematicError:
        _inited.clear()
        return
    for iface, url in list(_inited.items()):
        try:
            _proxy(c, ip, RPC_PORTS[iface]).init(url, "")        # abmelden
        except Exception:                                 # noqa: BLE001
            pass
        _inited.pop(iface, None)
    _push_state.clear()


def _push_cycle():
    global _push_on
    c = load_credentials()
    _push_on = bool(c.get("push")) and bool(c.get("host"))
    if not _push_on:
        _deinit_all(c)
        return
    now = time.time()
    port = _push_port(c)
    try:
        scheme, ip = _split_host(c["host"])
        if scheme != "http":
            raise HomematicError("Push geht nur mit http-Adresse der CCU")
        _ensure_listener(port)
        url = f"http://{c.get('push_host') or _local_ip(ip)}:{port}"
    except (HomematicError, OSError) as e:
        for iface in _known_interfaces() or {"-"}:
            _push_state[iface] = {"ok": False, "error": str(e), "ts": now}
        return
    for iface in _known_interfaces():
        st = _push_state.setdefault(iface, {})
        rp = RPC_PORTS.get(iface)
        if not rp:
            st.update(ok=False, error="Schnittstelle wird für Push nicht unterstützt", ts=now)
            continue
        try:
            proxy = _proxy(c, ip, rp)
            if _inited.get(iface) != url or now - st.get("init_ts", 0) > PUSH_INIT_EVERY_S:
                proxy.init(url, PUSH_ID_PREFIX + iface)
                _inited[iface] = url
                st.update(init_ts=now, alive=now)
            else:
                proxy.ping(PUSH_ID_PREFIX + iface)
            if now - st.get("alive", 0) > PUSH_ALIVE_MAX_S:
                st["init_ts"] = 0                         # beim naechsten Durchlauf neu anmelden
                st.update(ok=False, error="Keine Meldungen von der CCU – Port/Firewall prüfen")
            else:
                st.update(ok=True, error="")
        except Exception as e:                            # noqa: BLE001
            st["init_ts"] = 0
            st.update(ok=False, error=f"CCU-Anmeldung fehlgeschlagen: {e}")
        st["ts"] = now


def _push_loop():
    while not _push_stop.is_set():
        try:
            _push_cycle()
        except Exception as e:                            # noqa: BLE001
            log.warning("Homematic-Push: %s", e)
        _push_kick.wait(PUSH_CYCLE_S)
        _push_kick.clear()


def push_start():
    global _push_thread
    if _push_thread and _push_thread.is_alive():
        return
    _push_thread = threading.Thread(target=_push_loop, daemon=True, name="homematic-push-manager")
    _push_thread.start()


def push_status() -> dict:
    c = load_credentials()
    return {"enabled": bool(c.get("push")), "port": _push_port(c), "active": push_active(), "events": _events_seen,
            "interfaces": {k: {"ok": bool(v.get("ok")), "error": v.get("error", "")} for k, v in _push_state.items()}}


def save_push(enabled: bool, port=None):
    c = load_credentials()
    if not c.get("host"):
        raise HomematicError("Erst den CCU-Zugang einrichten")
    if port not in (None, ""):
        try:
            p = int(port)
        except (TypeError, ValueError):
            raise HomematicError("Port: Zahl erwartet")
        if not 1024 <= p <= 65535:
            raise HomematicError("Port: zwischen 1024 und 65535")
        c["push_port"] = p
    c["push"] = bool(enabled)
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
    try:                                               # Zugangsdaten: nur der Besitzer darf lesen
        os.chmod(CREDENTIALS_PATH, 0o600)
    except OSError:
        pass
    _push_kick.set()


def users_registry():
    """(laden, speichern) der Sensoren fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load_sensors, _save_sensors
