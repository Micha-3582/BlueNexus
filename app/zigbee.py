"""
Zigbee ueber ein Phoscon-/deCONZ-Gateway (ConBee, RaspBee) - LOKAL ueber die REST-API (`http://<gateway>/api/<schluessel>/...`).
Keine Zusatzpakete (nur `requests`), keine Cloud.

Schluessel holen: In Phoscon unter Einstellungen -> Gateway -> Erweitert "App autorisieren" druecken, dann in der App "Mit Gateway verbinden"
(`POST /api` mit `devicetype`, das Gateway antwortet mit dem Schluessel). Alternativ einen vorhandenen Schluessel eintragen.

Lichter/Steckdosen (`/lights`, schreibbar `state.on`) sind Schalt-Geraete wie die der anderen Systeme (kind "zigbee", id "zb-<uniqueid>"; die
Leistung kommt vom ZHAPower-Sensor derselben Steckdose). Sensoren (`/sensors`: Tuer/Fenster, Bewegung, Temperatur, Luftfeuchte, Helligkeit, Leistung)
und Thermostate (ZHAThermostat, Solltemperatur `config.heatsetpoint`) landen in denselben Registern wie die von Homematic (mit `source: "zigbee"`),
damit Dashboard, Regeln und Abläufe sie gleich behandeln. Werte werden 1 s zwischengespeichert (eine Abfrage fuer alles).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import threading
import time

import requests

import homematic

log = logging.getLogger("zigbee")

CREDENTIALS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zigbee.json")
CALL_TIMEOUT = 5.0
VALUE_TTL_S = 1.0
SCAN_TTL_S = 900.0
DEFAULT_SP_RANGE = (5.0, 30.0)
DOWN_BACKOFF_S = 15.0                    # ausgefallenes Gateway so lange nicht erneut abfragen (ausser bei Suche/Einrichten)

_http = requests.Session()
_lock = threading.Lock()
_cache: dict = {"ts": 0.0, "lights": {}, "sensors": {}, "groups": {}}
_gcache: dict = {}                        # Gruppen (Raeume) je Gateway - aendern sich selten
_down: dict = {}                         # Gateway-Kennung -> (Pause bis, Fehlertext)
_fail: dict = {}                         # Gateway-Kennung -> (Name, Fehlertext) beim letzten Abruf
_scan: dict[str, dict] = {}
_scan_ts = 0.0


class ZigbeeError(Exception):
    pass


# ---------------------------------------------------------------- Zugangsdaten (ein oder mehrere Gateways)
def load_gateways() -> list[dict]:
    """[{id, name, host, key}] - das alte Format (ein Gateway: {host, key}) wird als "gw1" gelesen und beim naechsten Speichern umgestellt."""
    try:
        with open(CREDENTIALS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if isinstance(data, dict) and isinstance(data.get("gateways"), list):
        return [g for g in data["gateways"] if isinstance(g, dict) and g.get("host") and g.get("id")]
    if isinstance(data, dict) and data.get("host"):
        return [{"id": "gw1", "name": "Gateway 1", "host": data["host"], "key": data.get("key", "")}]
    return []


def _save_gateways(gws: list[dict]):
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        json.dump({"gateways": gws}, f, indent=2)
    try:                                               # Zugangsdaten: nur der Besitzer darf lesen
        os.chmod(CREDENTIALS_PATH, 0o600)
    except OSError:
        pass
    _invalidate()


def gateway(gw_id: str | None) -> dict | None:
    """Gateway zur Kennung; ohne Kennung (Geraete aus der Zeit mit nur einem Gateway) das erste."""
    gws = load_gateways()
    if not gw_id:                                     # Geraete aus der Zeit mit nur einem Gateway: immer "gw1" (unabhaengig von der Reihenfolge in der Liste)
        return next((g for g in gws if g["id"] == "gw1"), gws[0] if gws else None)
    return next((g for g in gws if g["id"] == gw_id), None)


def load_credentials() -> dict:
    """Das erste Gateway (Kompatibilitaet)."""
    return gateway(None) or {}


def _split_host(host: str) -> tuple[str, int]:
    """(ip, port) aus '192.168.2.66' bzw. 'http://192.168.2.66:8080'. Nur private IPv4 (kein Web-Proxy-Missbrauch)."""
    raw = (host or "").strip().rstrip("/")
    for s in ("https://", "http://"):
        if raw.lower().startswith(s):
            raw = raw[len(s):]
            break
    port = 80
    if ":" in raw:
        raw, p = raw.rsplit(":", 1)
        try:
            port = int(p)
        except ValueError:
            raise ZigbeeError("Ungültiger Port")
        if not 1 <= port <= 65535:
            raise ZigbeeError("Ungültiger Port")
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        raise ZigbeeError("Ungültige Adresse – bitte die IP des Gateways eintragen, z. B. 192.168.2.66")
    if addr.version != 4 or not (addr.is_private and not addr.is_loopback):
        raise ZigbeeError("Nur IP-Adressen aus dem lokalen Netz erlaubt")
    return str(addr), port


def credentials_public() -> dict:
    gws = load_gateways()
    first = gws[0] if gws else {}
    return {"configured": any(g.get("host") and g.get("key") for g in gws), "host": first.get("host", ""), "key_set": bool(first.get("key")),
            "gateways": [{"id": g["id"], "name": g.get("name", ""), "host": g["host"], "key_set": bool(g.get("key"))} for g in gws]}


def save_gateway(host: str, key: str = "", name: str = "", gw_id: str = "") -> dict:
    """Gateway anlegen oder aendern (gleiche Kennung bzw. gleiche Adresse = aendern). Ein neuer Schluessel ersetzt den alten;
    aendert sich die Adresse ohne neuen Schluessel, wird der alte verworfen (er gehoert zum alten Geraet)."""
    ip, port = _split_host(host)
    h = ip if port == 80 else f"{ip}:{port}"
    gws = load_gateways()
    g = next((x for x in gws if x["id"] == gw_id), None) if gw_id else None
    if g is None:
        g = next((x for x in gws if x["host"] == h), None)
    if g is None:
        n, ids = 1, {x["id"] for x in gws}
        while f"gw{n}" in ids:
            n += 1
        g = {"id": f"gw{n}", "name": "", "host": h, "key": ""}
        gws.append(g)
    elif g["host"] != h and not (key or "").strip():
        g["key"] = ""
    g["host"] = h
    if (key or "").strip():
        g["key"] = key.strip()
    nm = (name or "").strip()[:40]
    if nm:
        g["name"] = nm
    elif not g.get("name"):
        g["name"] = "Gateway " + g["id"][2:]
    _save_gateways(gws)
    return dict(g)


def save_credentials(host: str, key: str = ""):
    """Kompatibilitaet: ein Gateway speichern (das mit gleicher Adresse, sonst das erste, sonst neu)."""
    ip, port = _split_host(host)
    same = next((x for x in load_gateways() if x["host"] == (ip if port == 80 else f"{ip}:{port}")), None)
    save_gateway(host, key, gw_id=(same or gateway(None) or {}).get("id", ""))


def rename_gateway(gw_id: str, name: str) -> bool:
    nm = (name or "").strip()[:40]
    gws = load_gateways()
    g = next((x for x in gws if x["id"] == gw_id), None)
    if not g or not nm:
        return False
    g["name"] = nm
    _save_gateways(gws)
    return True


def reorder_gateways(ids: list[str]) -> None:
    """Neue Reihenfolge der Gateways (nur die Anzeige; Geraete bleiben ihrem Gateway zugeordnet)."""
    gws = load_gateways()
    by = {g["id"]: g for g in gws}
    ids = [i for i in ids if i in by]
    slots = sorted(n for n, g in enumerate(gws) if g["id"] in set(ids))
    for slot, i in zip(slots, ids):
        gws[slot] = by[i]
    _save_gateways(gws)


def remove_gateway(gw_id: str) -> bool:
    gws = load_gateways()
    rest = [g for g in gws if g["id"] != gw_id]
    if len(rest) == len(gws):
        return False
    _save_gateways(rest)
    return True


def _gw_of(d: dict) -> str:
    g = gateway(d.get("gw"))
    return g["id"] if g else (d.get("gw") or "")


def in_use(gw_id: str) -> int:
    """Wie viele angelegte Geraete/Sensoren/Thermostate haengen an diesem Gateway (Eintraege ohne Kennung gehoeren zum ersten)."""
    import shelly
    first = gateway(None)
    first_id = first["id"] if first else ""
    n = sum(1 for d in shelly.load_devices() if d.get("kind") == "zigbee" and (d.get("gw") or first_id) == gw_id)
    for s in list(homematic.load_sensors()) + list(homematic.load_setpoints()):
        if s.get("source") == "zigbee" and (s.get("gw") or first_id) == gw_id:
            n += 1
    return n


def _invalidate():
    with _lock:
        _cache.update(ts=0.0, lights={}, sensors={}, groups={})
        _down.clear()


# ---------------------------------------------------------------- REST
def _url(c: dict, path: str, with_key: bool = True) -> str:
    if not c.get("host"):
        raise ZigbeeError("Zigbee ist noch nicht eingerichtet (Smart Home → Geräte suchen → Zigbee)")
    ip, port = _split_host(c["host"])
    if with_key:
        if not c.get("key"):
            raise ZigbeeError("Kein API-Schlüssel – „Mit Gateway verbinden“ drücken")
        return f"http://{ip}:{port}/api/{c['key']}{path}"
    return f"http://{ip}:{port}/api{path}"


def _request(gw, method: str, path: str, body=None, with_key: bool = True):
    c = gw if isinstance(gw, dict) else (gateway(gw) or {})
    try:
        r = _http.request(method, _url(c, path, with_key), json=body, timeout=CALL_TIMEOUT)
    except requests.RequestException as e:
        raise ZigbeeError(f"Gateway nicht erreichbar: {e}")
    if r.status_code == 403:
        raise ZigbeeError("Zugriff verweigert – API-Schlüssel ungültig oder abgelaufen (neu verbinden)")
    try:
        data = r.json()
    except ValueError:
        raise ZigbeeError(f"Unerwartete Antwort des Gateways (HTTP {r.status_code})")
    if isinstance(data, list):                      # Fehlerliste: [{"error": {"description": ...}}]
        for item in data:
            if isinstance(item, dict) and item.get("error"):
                raise ZigbeeError(str(item["error"].get("description") or item["error"]))
    if r.status_code >= 400:
        raise ZigbeeError(f"Gateway-Fehler (HTTP {r.status_code})")
    return data


def pair(host: str, name: str = "", gw_id: str = "") -> str:
    """Schluessel vom Gateway holen (in Phoscon vorher "App autorisieren"). Speichert Adresse und Schluessel."""
    ip, port = _split_host(host)
    try:
        r = _http.post(f"http://{ip}:{port}/api", json={"devicetype": "bluenexus"}, timeout=CALL_TIMEOUT)
    except requests.RequestException as e:
        raise ZigbeeError(f"Gateway nicht erreichbar: {e}")
    try:
        data = r.json()
    except ValueError:
        raise ZigbeeError("Unerwartete Antwort des Gateways – ist das ein Phoscon/deCONZ-Gateway?")
    first = data[0] if isinstance(data, list) and data else {}
    key = ((first or {}).get("success") or {}).get("username")
    if not key:
        raise ZigbeeError("Das Gateway hat keinen Schlüssel herausgegeben – in Phoscon unter Einstellungen → Gateway → Erweitert "
                          "„App autorisieren“ drücken und dann innerhalb einer Minute hier erneut „Mit Gateway verbinden“")
    save_gateway(host, key, name, gw_id)
    return key


def test_connection(gw_id: str | None = None) -> dict:
    """Verbindung eines Gateways pruefen (ohne Kennung: das erste)."""
    g = gateway(gw_id)
    if not g:
        raise ZigbeeError("Zigbee ist noch nicht eingerichtet (Smart Home → Geräte suchen → Zigbee)")
    cfg = _request(g, "GET", "/config")
    lights, sensors = _request(g, "GET", "/lights"), _request(g, "GET", "/sensors")
    _invalidate()
    n = (len(lights) if isinstance(lights, dict) else 0) + (len(sensors) if isinstance(sensors, dict) else 0)
    return {"name": cfg.get("name", "") if isinstance(cfg, dict) else "", "devices": n, "id": g["id"], "gateway": g.get("name", "")}


def _fetch_one(g: dict, force: bool, with_groups: bool):
    gid, now = g["id"], time.time()
    if not force and _down.get(gid, (0, ""))[0] > now:
        raise ZigbeeError(_down[gid][1])                 # kurz nach einem Fehler nicht bei jeder Abfrage neu warten
    try:
        lights = _request(g, "GET", "/lights")
        sensors = _request(g, "GET", "/sensors")
        groups = _gcache.get(gid, {})
        if with_groups or gid not in _gcache:
            try:
                groups = _request(g, "GET", "/groups")
            except ZigbeeError:
                groups = {}
        for d in (lights, sensors, groups):
            if not isinstance(d, dict):
                raise ZigbeeError("Unerwartete Antwort des Gateways")
    except ZigbeeError as e:
        _down[gid] = (time.time() + DOWN_BACKOFF_S, str(e))
        raise
    _down.pop(gid, None)
    _gcache[gid] = groups
    return lights, sensors, groups


def _fetch(force: bool = False, with_groups: bool = False):
    """(lights, sensors, groups) aller Gateways als {"<gw>|<id>": objekt} (Objekte tragen "_gw" und "_id") - 1 s zwischengespeichert.
    Faellt ein Gateway aus, laufen die anderen weiter (Fehler je Gateway in _fail); nur wenn alle ausfallen, gibt es einen Fehler."""
    now = time.time()
    with _lock:
        if not force and _cache["ts"] and now - _cache["ts"] < VALUE_TTL_S:
            return _cache["lights"], _cache["sensors"], _cache["groups"]
    gws = load_gateways()
    if not gws:
        raise ZigbeeError("Zigbee ist noch nicht eingerichtet (Smart Home → Geräte suchen → Zigbee)")
    results: dict = {}

    def one(g):
        try:
            results[g["id"]] = _fetch_one(g, force, with_groups)
        except ZigbeeError as e:
            results[g["id"]] = e
    if len(gws) == 1:
        one(gws[0])
    else:
        ts = [threading.Thread(target=one, args=(g,), daemon=True) for g in gws]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    merged = ({}, {}, {})
    fail = {}
    for g in gws:
        r = results.get(g["id"])
        if not isinstance(r, tuple):
            msg = str(r) if r else "keine Antwort"
            fail[g["id"]] = (g.get("name", ""), msg if len(gws) == 1 else f"Gateway „{g.get('name') or g['id']}“: {msg}")
            continue
        for src, dst in zip(r, merged):
            for oid, o in src.items():
                if isinstance(o, dict):
                    o = dict(o)
                    o["_gw"], o["_id"] = g["id"], oid
                    dst[f"{g['id']}|{oid}"] = o
    if fail and len(fail) == len(gws):
        with _lock:
            _fail.clear()
            _fail.update(fail)
        raise ZigbeeError(" · ".join(v[1] for v in fail.values()))
    with _lock:
        _fail.clear()
        _fail.update(fail)
        _cache.update(ts=time.time(), lights=merged[0], sensors=merged[1], groups=merged[2])
    return merged


def _missing(d: dict) -> str:
    """Warum ein Geraet nicht gefunden wurde: Gateway ausgefallen oder Geraet wirklich entfernt."""
    f = _fail.get(_gw_of(d))
    return f[1] if f else "Gerät im Gateway nicht mehr vorhanden"


def _by_uid(objs: dict, uid: str):
    for oid, o in objs.items():
        if o.get("uniqueid") == uid:
            return oid, o
    return None, None


def _mac(uid: str) -> str:
    return (uid or "")[:23]


def _room(groups: dict, light: dict) -> str:
    for g in groups.values():
        if g.get("_gw") == light.get("_gw") and str(light.get("_id")) in [str(x) for x in (g.get("lights") or [])] and g.get("name"):
            return g["name"]
    return ""


def _gwname(gw_id: str) -> str:
    """Gateway-Name fuer Trefferlisten - nur wenn es mehrere gibt."""
    gws = load_gateways()
    if len(gws) < 2:
        return ""
    return next((g.get("name") or g["id"] for g in gws if g["id"] == gw_id), "")


# ---------------------------------------------------------------- Lichter / Steckdosen (Schalter)
def device_id(uid: str) -> str:
    return "zb-" + uid.replace(":", "-")


def discover(known_ids: set[str]) -> list[dict]:
    lights, _, groups = _fetch(force=True, with_groups=True)
    out = []
    for lid, l in lights.items():
        st = l.get("state") or {}
        if "on" not in st or not l.get("uniqueid"):
            continue                                  # Rolllaeden & Co. (kein on/off) vorerst nicht
        out.append({"id": device_id(l["uniqueid"]), "uniqueid": l["uniqueid"], "name": l.get("name") or l["uniqueid"],
                    "model": str(l.get("modelid") or l.get("type") or "Zigbee"), "type": l.get("type", ""),
                    "room": _room(groups, l), "dimmable": "bri" in st, "known": device_id(l["uniqueid"]) in known_ids,
                    "gw": l["_gw"], "gwname": _gwname(l["_gw"])})
    out.sort(key=lambda f: (f["room"].lower(), f["name"].lower()))
    with _lock:
        _scan.clear()
        _scan.update({f["id"]: f for f in out})
        global _scan_ts
        _scan_ts = time.time()
    return out


def _icon_for(f: dict) -> str:
    t = (f.get("type") or "").lower()
    return "🔌" if ("plug" in t or "on/off" in t or "outlet" in t) else "💡"


def build_entries(ids: list[str]) -> list[dict]:
    if time.time() - _scan_ts > SCAN_TTL_S or any(i not in _scan for i in ids):
        discover(set())
    out = []
    for i in ids:
        f = _scan.get(i)
        if not f:
            raise ZigbeeError("Gerät nicht gefunden (im Gateway entfernt?)")
        ip = _split_host((gateway(f["gw"]) or {}).get("host", ""))[0]
        out.append({"id": f["id"], "kind": "zigbee", "uniqueid": f["uniqueid"], "gw": f["gw"], "mac": None, "gen": 0, "channel": 0, "model": f["model"],
                    "name": f["name"], "room": f["room"], "ip": ip, "icon": _icon_for(f)})
    return out


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': W|None}"""
    try:
        lights, sensors, _ = _fetch()
        _, l = _by_uid(lights, d["uniqueid"])
        if not l:
            return {"online": False, "on": None, "power": None, "error": _missing(d)}
        st = l.get("state") or {}
        if st.get("reachable") is False:
            return {"online": False, "on": None, "power": None, "error": "Das Gateway meldet das Gerät als nicht erreichbar"}
        power = None
        for s in sensors.values():
            if s.get("type") == "ZHAPower" and _mac(s.get("uniqueid", "")) == _mac(d["uniqueid"]):
                p = (s.get("state") or {}).get("power")
                power = None if p is None else round(float(p), 1)
                break
        return {"online": True, "on": bool(st.get("on")), "power": power}
    except (ZigbeeError, KeyError, TypeError, ValueError) as e:
        return {"online": False, "on": None, "power": None, "error": str(e)}


def set_state(d: dict, on: bool, timer_s: int | None = None):
    """Schaltet ein Licht/eine Steckdose. Einen eingebauten Rueckschalt-Timer gibt es bei Zigbee-Geraeten nicht (timer_s wird ignoriert)."""
    lights, _, _ = _fetch()
    _, l = _by_uid(lights, d["uniqueid"])
    if l is None:
        raise ZigbeeError(_missing(d))
    try:
        _request(l["_gw"], "PUT", f"/lights/{l['_id']}/state", {"on": bool(on)})
    except ZigbeeError as e:
        raise ZigbeeError(f"Schalten fehlgeschlagen: {e}")
    _invalidate()
    return status(d)


# ---------------------------------------------------------------- Sensoren (nur lesen)
# deCONZ-Typ -> (Art, Einheit, binaer?, Datenfeld, Teiler)
SENSOR_TYPES = {
    "ZHAOpenClose": ("contact", "", True, "open", 1),
    "ZHAPresence": ("motion", "", True, "presence", 1),
    "ZHATemperature": ("temperature", "°C", False, "temperature", 100.0),
    "ZHAHumidity": ("humidity", "%", False, "humidity", 100.0),
    "ZHALightLevel": ("brightness", "lux", False, "lux", 1),
    "ZHAPower": ("power", "W", False, "power", 1),
}
KIND_LABEL = {"contact": "Fenster/Tür", "motion": "Bewegung", "temperature": "Temperatur", "humidity": "Luftfeuchte", "brightness": "Helligkeit", "power": "Leistung"}


def sensor_id(uid: str) -> str:
    return "zbS-" + uid.replace(":", "-")


def thermostat_id(uid: str) -> str:
    return "zbT-" + uid.replace(":", "-")


def _sensor_scan_items(known_ids: set[str]) -> list[dict]:
    _, sensors, _ = _fetch(force=True)
    out = []
    for s in sensors.values():
        spec = SENSOR_TYPES.get(s.get("type"))
        if not spec or not s.get("uniqueid"):
            continue
        kind, unit, binary, _, _ = spec
        out.append({"id": sensor_id(s["uniqueid"]), "kind": kind, "address": s["uniqueid"], "interface": "Zigbee", "datapoint": s["type"],
                    "unit": unit, "binary": binary, "model": str(s.get("modelid") or s.get("type")), "room": "",
                    "name": f"{s.get('name') or s['uniqueid']} – {KIND_LABEL[kind]}", "source": "zigbee", "gw": s["_gw"], "gwname": _gwname(s["_gw"]),
                    "known": sensor_id(s["uniqueid"]) in known_ids})
    out.sort(key=lambda f: f["name"].lower())
    return out


_sensor_scan: dict[str, dict] = {}
_sp_scan: dict[str, dict] = {}


def sensors_scan() -> list[dict]:
    items = _sensor_scan_items({s["id"] for s in homematic.load_sensors()})
    with _lock:
        _sensor_scan.clear()
        _sensor_scan.update({f["id"]: f for f in items})
    return items


def add_sensors(ids: list[str]) -> list[dict]:
    if any(i not in _sensor_scan for i in ids):
        sensors_scan()
    items = homematic.load_sensors()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _sensor_scan.get(i)
        if not f:
            raise ZigbeeError("Sensor nicht gefunden (im Gateway entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "kind", "address", "interface", "datapoint", "unit", "binary", "model", "room", "name", "source", "gw") if k in f}
        item["users"] = []                           # neu: zunaechst nur fuer Administratoren sichtbar
        if f["kind"] == "contact":
            item["invert"] = True                      # Standard fuer Fenster/Tueren: TRUE = geschlossen (gruen), FALSE = offen (rot)
        items.append(item)
        added.append(item)
    if added:
        homematic._save_sensors(items)
    return added


def read_value(sen: dict):
    """Rohwert eines Zigbee-Sensors: True/False (binaer), Zahl oder None (nicht lesbar/nicht erreichbar)."""
    try:
        _, sensors, _ = _fetch()
        _, s = _by_uid(sensors, sen["address"])
        spec = SENSOR_TYPES.get(sen.get("datapoint"))
        if not s or not spec or (s.get("config") or {}).get("reachable") is False:
            return None
        v = (s.get("state") or {}).get(spec[3])
        if v is None:
            return None
        return bool(v) if spec[2] else float(v) / spec[4]
    except (ZigbeeError, KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- Thermostate (Solltemperatur)
def setpoints_scan() -> list[dict]:
    _, sensors, groups = _fetch(force=True, with_groups=True)
    known = {s["id"] for s in homematic.load_setpoints()}
    out = []
    for s in sensors.values():
        if s.get("type") != "ZHAThermostat" or not s.get("uniqueid"):
            continue
        out.append({"id": thermostat_id(s["uniqueid"]), "address": s["uniqueid"], "interface": "Zigbee", "datapoint": "heatsetpoint",
                    "min": DEFAULT_SP_RANGE[0], "max": DEFAULT_SP_RANGE[1], "model": str(s.get("modelid") or "Thermostat"), "room": "",
                    "name": s.get("name") or s["uniqueid"], "source": "zigbee", "gw": s["_gw"], "gwname": _gwname(s["_gw"]),
                    "known": thermostat_id(s["uniqueid"]) in known})
    out.sort(key=lambda f: f["name"].lower())
    with _lock:
        _sp_scan.clear()
        _sp_scan.update({f["id"]: f for f in out})
    return out


def add_setpoints(ids: list[str]) -> list[dict]:
    if any(i not in _sp_scan for i in ids):
        setpoints_scan()
    items = homematic.load_setpoints()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _sp_scan.get(i)
        if not f:
            raise ZigbeeError("Thermostat nicht gefunden (im Gateway entfernt?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "address", "interface", "datapoint", "min", "max", "model", "room", "name", "source", "gw") if k in f}
        items.append(item)
        added.append(item)
    if added:
        homematic._save_setpoints(items)
    return added


def read_setpoint(sp: dict):
    """Aktuelle Solltemperatur in °C oder None."""
    try:
        _, sensors, _ = _fetch()
        _, s = _by_uid(sensors, sp["address"])
        v = ((s or {}).get("config") or {}).get("heatsetpoint")
        return None if v is None else round(float(v) / 100.0, 1)
    except (ZigbeeError, TypeError, ValueError):
        return None


def set_setpoint(sp: dict, value: float) -> float:
    """Solltemperatur setzen (auf den Bereich des Geraets begrenzt). Rueckgabe: gesetzter Wert."""
    v = min(float(sp.get("max", DEFAULT_SP_RANGE[1])), max(float(sp.get("min", DEFAULT_SP_RANGE[0])), float(value)))
    _, sensors, _ = _fetch()
    _, sen = _by_uid(sensors, sp["address"])
    if sen is None:
        raise ZigbeeError(_missing(sp).replace("Gerät", "Thermostat"))
    _request(sen["_gw"], "PUT", f"/sensors/{sen['_id']}/config", {"heatsetpoint": int(round(v * 100))})
    _invalidate()
    return v
