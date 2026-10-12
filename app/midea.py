"""
Midea-Klimaanlagen (NetHome Plus, auch Comfee, Inventor, Pioneer u. a.) - lokal im Heimnetz ueber die Bibliothek `msmart-ng`
(`pip install msmart-ng`; Python 3.9 reicht).

- Suche per UDP-Rundruf im Heimnetz. Moderne Geraete (Protokoll V3) brauchen einmalig Token und Schluessel, die die Bibliothek ueber
  die NetHome-Plus-Cloud holt (mit dem eingebauten Standardzugang der Bibliothek je Region DE/US/KR; wahlweise mit dem eigenen
  NetHome-Plus-Konto - das wird NICHT gespeichert). Danach laeuft alles lokal, ohne Cloud.
- Jede Klimaanlage ist ein Geraet der normalen Geraeteliste (kind "midea"): Ein/Aus, Rechte, PIN, Alexa, Dashboard und Regeln funktionieren
  wie bei den anderen. Dazu kommen Modus, Solltemperatur, Luefter und Schwenken (Panel in der Geraeteliste, Schritt "Klimaanlage" in Regeln).
- Die Bibliothek ist asynchron: eine eigene Ereignisschleife in einem Hintergrund-Thread bedient alle Aufrufe. Die Geraete merken sich ihre
  angemeldete Verbindung; Zustaende werden kurz zwischengespeichert (Klimaanlagen-Funkmodule vertragen kein haeufiges Abfragen).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import threading
import time

log = logging.getLogger("midea")

STATUS_TTL_S = 20.0               # gelesener Zustand gilt so lange
CLOUD_STATUS_TTL_S = 45.0         # ueber die Cloud seltener fragen
FAIL_TTL_S = 30.0                 # nach einem Fehler so lange nicht erneut versuchen (haelt die Geraeteliste schnell)
STATUS_TIMEOUT_S = 12.0
SET_TIMEOUT_S = 25.0
DISCOVER_TIMEOUT_S = 6.0
REGIONS = ("DE", "US", "KR")
DEFAULT_REGION = "DE"

MODE_LABELS = {"auto": "Automatik", "cool": "Kühlen", "dry": "Entfeuchten", "heat": "Heizen", "fan_only": "Lüften", "smart_dry": "Intelligent entfeuchten"}
FAN_LABELS = {"auto": "Automatik", "silent": "Flüster", "low": "niedrig", "medium": "mittel", "high": "hoch", "max": "maximal"}
SWING_LABELS = {"off": "aus", "vertical": "vertikal", "horizontal": "horizontal", "both": "beides"}


class MideaError(Exception):
    pass


# ---------------------------------------------------------------- Bibliothek + Ereignisschleife
def _lib():
    """(AirConditioner, Discover, DeviceType) der Bibliothek - mit verstaendlicher Meldung, falls sie fehlt."""
    try:
        from msmart.const import DeviceType
        from msmart.device import AirConditioner
        from msmart.discover import Discover
    except ImportError:
        raise MideaError("Die Bibliothek „msmart-ng“ ist auf dem Server nicht installiert (Server: venv/bin/pip install -r app/requirements.txt, dann die App neu starten)")
    return AirConditioner, Discover, DeviceType


def available() -> bool:
    try:
        _lib()
        return True
    except MideaError:
        return False


_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="midea-loop", daemon=True).start()
            _loop = loop
        return _loop


def _run(coro, timeout: float):
    """Coroutine in der Hintergrund-Schleife ausfuehren und warten."""
    fut = asyncio.run_coroutine_threadsafe(coro, _get_loop())
    try:
        return fut.result(timeout)
    except (TimeoutError, concurrent.futures.TimeoutError):          # Python < 3.11: zwei verschiedene Klassen
        fut.cancel()
        raise MideaError("Zeitüberschreitung – die Klimaanlage antwortet nicht (WLAN/IP prüfen)")
    except MideaError:
        raise
    except Exception as e:                                  # noqa: BLE001 - Bibliotheksfehler in klare Meldungen uebersetzen
        raise MideaError(_explain(e))


def _explain(e: Exception) -> str:
    name, msg = e.__class__.__name__, str(e)
    if "Authentication" in name or "authent" in msg.lower():
        return "Anmeldung an der Klimaanlage fehlgeschlagen (Token/Schlüssel ungültig – Klimaanlage neu suchen und anlegen)"
    if "Cloud" in name:
        return f"Midea-Cloud: {msg or name} (Region prüfen oder eigenes NetHome-Plus-Konto angeben)"
    return f"{name}: {msg}" if msg else name


# ---------------------------------------------------------------- Zustand + Verbindungen
_devs: dict[str, object] = {}                              # Geraete-ID -> angemeldetes AirConditioner-Objekt (nur in der Schleife benutzen)
_dlocks: dict[str, asyncio.Lock] = {}                       # je Geraet nur ein Aufruf gleichzeitig
_cache: dict[str, tuple] = {}                              # Geraete-ID -> (Zeit, Zustand | MideaError)
_slocks: dict[str, threading.Lock] = {}


def _mode_key(v) -> str:
    return str(getattr(v, "name", v) or "").lower()


def snapshot(dev) -> dict:
    """Zustand eines AirConditioner-Objekts als einfaches Dict."""
    fan = dev.fan_speed
    return {"online": bool(dev.online), "on": dev.power_state, "mode": _mode_key(dev.operational_mode), "target_c": dev.target_temperature,
            "indoor_c": dev.indoor_temperature, "outdoor_c": dev.outdoor_temperature,
            "fan": _mode_key(fan) if hasattr(fan, "name") else (int(fan) if fan is not None else None),
            "swing": _mode_key(dev.swing_mode), "eco": getattr(dev, "eco", None)}


def info_text(s: dict) -> str:
    """Kurztext fuer die Geraeteliste: Modus, Soll, innen, aussen."""
    n = lambda v: f"{v:g}".replace(".", ",")            # deutsches Komma
    parts = []
    if s.get("on") and s.get("mode"):
        parts.append(MODE_LABELS.get(s["mode"], s["mode"]))
    if s.get("target_c") is not None:
        parts.append(f"Soll {n(s['target_c'])} °C")
    if s.get("indoor_c") is not None:
        parts.append(f"innen {n(s['indoor_c'])} °C")
    if s.get("outdoor_c") is not None:
        parts.append(f"außen {n(s['outdoor_c'])} °C")
    return " · ".join(parts)


async def _get_dev(entry: dict):
    """Angemeldetes Geraeteobjekt (neu aufgebaut, wenn noetig)."""
    AC, _, _ = _lib()
    cid = entry["id"]
    dev = _devs.get(cid)
    key = (entry.get("ip"), entry.get("token"), entry.get("key"))
    if dev is not None and getattr(dev, "_vl_key", None) == key:
        return dev
    dev = AC(ip=entry["ip"], port=int(entry.get("port") or 6444), device_id=int(entry["device_id"]), sn=entry.get("sn"), name=entry.get("raw_name"),
             version=entry.get("version"))
    if (entry.get("version") or 0) >= 3:
        await dev.authenticate(entry["token"], entry["key"])
    await dev.get_capabilities()
    dev._vl_key = key
    _devs[cid] = dev
    return dev


def _lock_for(cid: str) -> asyncio.Lock:
    return _dlocks.setdefault(cid, asyncio.Lock())


async def _read(entry: dict) -> dict:
    async with _lock_for(entry["id"]):
        try:
            dev = await _get_dev(entry)
            await dev.refresh()
            return snapshot(dev)
        except Exception:
            _devs.pop(entry["id"], None)                    # naechstes Mal neu anmelden
            raise


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': None, 'info': Text, mode/target_c/indoor_c/outdoor_c/fan/swing ...}"""
    cid = d["id"]
    with _slocks.setdefault(cid, threading.Lock()):
        hit = _cache.get(cid)
        ttl = CLOUD_STATUS_TTL_S if d.get("cloud") else STATUS_TTL_S
        if hit and time.time() - hit[0] < (FAIL_TTL_S if isinstance(hit[1], MideaError) else ttl):
            if isinstance(hit[1], MideaError):
                return {"online": False, "on": None, "power": None, "error": str(hit[1])}
            return _public_status(hit[1])
        try:
            snap = _cloud_read(d) if d.get("cloud") else _run(_read(d), STATUS_TIMEOUT_S)
        except MideaError as e:
            _cache[cid] = (time.time(), e)
            return {"online": False, "on": None, "power": None, "error": str(e)}
        if not snap.get("online"):
            err = MideaError("Die Klimaanlage antwortet nicht (WLAN/Strom prüfen)")
            _cache[cid] = (time.time(), err)
            return {"online": False, "on": None, "power": None, "error": str(err)}
        _cache[cid] = (time.time(), snap)
        return _public_status(snap)


def _public_status(snap: dict) -> dict:
    return {**snap, "power": None, "info": info_text(snap)}


def invalidate(cid: str):
    _cache.pop(cid, None)


def _resolve(AC, enum_name: str, key):
    """'cool' -> AirConditioner.OperationalMode.COOL (Gross-/Kleinschreibung egal)."""
    enum = getattr(AC, enum_name)
    try:
        return enum[str(key).strip().upper()]
    except KeyError:
        raise MideaError(f"Unbekannter Wert „{key}“")


async def _apply(entry: dict, power=None, mode=None, target=None, fan=None, swing=None, eco=None) -> dict:
    AC, _, _ = _lib()
    async with _lock_for(entry["id"]):
        try:
            dev = await _get_dev(entry)
            await dev.refresh()                             # aktuellen Zustand holen - apply() schickt immer den ganzen Zustand
            if not dev.online:
                raise MideaError("Die Klimaanlage antwortet nicht (WLAN/Strom prüfen)")
            if power is not None:
                dev.power_state = bool(power)
            if mode:
                dev.operational_mode = _resolve(AC, "OperationalMode", mode)
            if target is not None:
                t = float(target)
                if not dev.min_target_temperature <= t <= dev.max_target_temperature:
                    raise MideaError(f"Solltemperatur zwischen {dev.min_target_temperature} und {dev.max_target_temperature} °C")
                dev.target_temperature = round(t * 2) / 2
            if fan:
                dev.fan_speed = _resolve(AC, "FanSpeed", fan)
            if swing:
                dev.swing_mode = _resolve(AC, "SwingMode", swing)
            if eco is not None and getattr(dev, "supports_eco", False):
                dev.eco = bool(eco)
            await dev.apply()
            return snapshot(dev)
        except Exception:
            _devs.pop(entry["id"], None)
            raise


def set_params(d: dict, **kw) -> dict:
    """Modus/Solltemperatur/Luefter/Schwenken/Ein-Aus setzen (nur die genannten). Rueckgabe: neuer Zustand."""
    kw = {k: v for k, v in kw.items() if v not in (None, "")}
    if not kw:
        raise MideaError("Nichts zu setzen")
    try:
        snap = _cloud_apply(d, **kw) if d.get("cloud") else _run(_apply(d, **kw), SET_TIMEOUT_S)
    finally:
        invalidate(d["id"])
    _cache[d["id"]] = (time.time(), snap)
    return _public_status(snap)


def set_state(d: dict, on: bool, timer_s: int | None = None) -> dict:
    """Ein-/Ausschalten (ein Rueckschalt-Timer wird nicht unterstuetzt und ignoriert)."""
    return set_params(d, power=bool(on))


async def _details(entry: dict) -> dict:
    AC, _, _ = _lib()
    async with _lock_for(entry["id"]):
        try:
            dev = await _get_dev(entry)
            await dev.refresh()
            snap = snapshot(dev)
            modes = [m for m in (dev.supported_operation_modes or []) ] or list(AC.OperationalMode)
            fans = [f for f in (dev.supported_fan_speeds or [])] or list(AC.FanSpeed)
            swings = [s for s in (dev.supported_swing_modes or [])] or list(AC.SwingMode)
            return {"state": snap, "min": dev.min_target_temperature, "max": dev.max_target_temperature, "step": 0.5,
                    "modes": [{"key": _mode_key(m), "label": MODE_LABELS.get(_mode_key(m), _mode_key(m))} for m in modes if _mode_key(m) in MODE_LABELS],
                    "fans": [{"key": _mode_key(f), "label": FAN_LABELS.get(_mode_key(f), _mode_key(f))} for f in fans if _mode_key(f) in FAN_LABELS],
                    "swings": [{"key": _mode_key(s), "label": SWING_LABELS.get(_mode_key(s), _mode_key(s))} for s in swings if _mode_key(s) in SWING_LABELS],
                    "supports_eco": bool(getattr(dev, "supports_eco", False))}
        except Exception:
            _devs.pop(entry["id"], None)
            raise


def details(d: dict) -> dict:
    snap = _cloud_details(d) if d.get("cloud") else _run(_details(d), SET_TIMEOUT_S)
    return {**snap, "state": _public_status(snap["state"])}


# ---------------------------------------------------------------- Suche
_scan: dict[str, dict] = {}                               # Geraete-ID -> Eintrag samt Token/Schluessel (nur auf dem Server, nie zum Browser)
_scan_ts = 0.0


def _check_target(target: str | None) -> str | None:
    if not target:
        return None
    import ipaddress
    try:
        a = ipaddress.ip_address(target.strip())
    except ValueError:
        raise MideaError("Ungültige IP-Adresse")
    if a.version != 4 or not (a.is_private and not a.is_loopback):
        raise MideaError("Nur IP-Adressen aus dem lokalen Netz erlaubt")
    return str(a)


def discover(region: str = DEFAULT_REGION, account: str | None = None, password: str | None = None, target: str | None = None, known_ids=()) -> list[dict]:
    """Klimaanlagen im Heimnetz suchen (oder eine bestimmte IP), ohne Cloud. Mit MSmartHome-Konto werden die Schluessel einmalig geholt (Konto wird nicht gespeichert)."""
    global _scan_ts
    region = (region or DEFAULT_REGION).upper()
    if region not in REGIONS:
        raise MideaError("Region: " + ", ".join(REGIONS))
    account = (account or "").strip() or None
    hit = _login_fail.get(account) if account else None
    if hit and "7610" in hit[1] and time.time() - hit[0] < hit[2]:
        # gesperrtes Konto: die Suche wuerde sich bis zu dreimal anmelden (NetHome, SmartHome, Cloud-Liste) und die Sperre jedes Mal verlaengern
        left = int(hit[2] - (time.time() - hit[0]))
        raise MideaError(f"{hit[1]} – Suche mit Konto erst in {left // 60 + 1} Min wieder möglich (jeder Versuch verlängert die Sperre bei Midea)")
    async def scan():
        lan = await _lan_scan(_check_target(target))
        keys = {}
        need = [i for i, d in lan.items() if (d.version or 0) >= 3 and f"midea-{i}" not in set(known_ids)]   # schon angelegte: Schluessel ueber 🔑
        if account and password and need:
            keys = await _local_keys(region, account, password, need, lan)
        return lan, keys
    lan, keys = _run(scan(), DISCOVER_TIMEOUT_S + 90)
    found = []
    for did, d in lan.items():
        k = keys.get(did, {})
        found.append({"id": f"midea-{did}", "device_id": did, "ip": d.ip, "port": int(d.port), "raw_name": d.name, "sn": d.sn, "version": d.version,
                      "token": k.get("token"), "key": k.get("key"), "online": True, "supported": True})
    _scan.clear()
    _scan.update({f["id"]: f for f in found})
    _scan_ts = time.time()
    return [{"id": f["id"], "ip": f["ip"] or "Cloud", "name": default_name(f), "model": "Midea Klimaanlage", "version": f["version"], "online": f["online"],
             "supported": f["supported"], "known": f["id"] in set(known_ids), "room": "",
             "nokey": (f.get("version") or 0) >= 3 and not (f.get("token") and f.get("key"))} for f in found]


def default_name(f: dict) -> str:
    if f.get("cloud") and f.get("raw_name"):
        return str(f["raw_name"])
    raw = str(f.get("raw_name") or "")
    tail = raw.split("_")[-1] if "_" in raw else str(f.get("device_id", ""))[-4:]
    return f"Klimaanlage {tail}".strip()


def build_entries(ids: list[str]) -> list[dict]:
    """Geraete-Eintraege (mit Token/Schluessel) aus dem letzten Suchergebnis."""
    out = []
    for i in ids:
        f = _scan.get(i)
        if not f:
            raise MideaError("Klimaanlage nicht gefunden – bitte noch einmal suchen")
        if f.get("cloud"):
            out.append({"id": f["id"], "kind": "midea", "cloud": True, "cloud_account": f["cloud_account"], "cloud_password": f["cloud_password"], "ip": "", "port": 0,
                        "device_id": f["device_id"], "raw_name": f["raw_name"], "sn": f.get("sn"), "version": 0, "mac": None, "gen": 0, "channel": 0,
                        "model": "Midea Klimaanlage", "name": default_name(f), "room": "", "icon": "❄️"})
            continue
        if (f.get("version") or 0) >= 3 and not (f.get("token") and f.get("key")):
            raise MideaError(f"{default_name(f)}: kein Schlüssel – bei der Suche E-Mail/Passwort des MSmartHome-Kontos angeben, in dem die Anlage eingetragen ist")
        out.append({"id": f["id"], "kind": "midea", "ip": f["ip"], "port": f["port"], "device_id": f["device_id"], "raw_name": f["raw_name"], "sn": f["sn"],
                    "version": f["version"], "token": f["token"], "key": f["key"], "mac": None, "gen": 0, "channel": 0, "model": "Midea Klimaanlage",
                    "name": default_name(f), "room": "", "icon": "❄️"})
    return out


# ---------------------------------------------------------------- Cloud -> lokal umstellen
async def _smarthome_token(cloud, udpid: str, appliance_id: int):
    """getToken der SmartHome-Cloud mit Geraete-ID (applianceCodes) - ohne sie antwortet Midea mit 3004 "value is illegal".
    Eigene Umsetzung, damit es mit jeder msmart-ng-Version geht (erst ab 2026.9 eingebaut)."""
    import msmart.cloud as mcloud
    body = cloud._build_request_body({"udpid": udpid, "applianceCodes": str(appliance_id)})
    resp = await cloud._api_request("/v1/iot/secure/getToken", body)
    for t in (resp or {}).get("tokenlist", []):
        if t.get("udpId") == udpid:
            return t["token"], t["key"]
    raise mcloud.CloudError(f"Kein Schlüssel für {udpid}")


async def _lan_scan(target: str | None = None) -> dict:
    """Klimaanlagen im Heimnetz finden - ohne Cloud. {device_id: Geraet der Bibliothek}"""
    _, Discover, DeviceType = _lib()
    orig = Discover.__dict__.get("_authenticate_device")
    Discover._authenticate_device = classmethod(lambda cls, dev: asyncio.sleep(0, False))      # nur finden
    try:
        kw = {"timeout": int(DISCOVER_TIMEOUT_S), "auto_connect": False}
        if target:
            kw["target"] = target
        devs = await Discover.discover(**kw)
    finally:
        if orig is not None:
            Discover._authenticate_device = orig
    return {int(d.id): d for d in devs if getattr(d, "type", None) == DeviceType.AIR_CONDITIONER}


async def _local_keys(region: str, account: str, password: str, device_ids: list, lan: dict | None = None) -> dict:
    """Mit EINER Anmeldung beim MSmartHome-Konto Token/Schluessel holen und lokal pruefen.
    Rueckgabe {device_id: {ip, port, version, sn, raw_name, token, key}} - nur Anlagen, die lokal wirklich antworten."""
    AC, _, _ = _lib()
    import msmart.cloud as mcloud
    from msmart.lan import Security
    if lan is None:
        lan = await _lan_scan()
    wanted = set(int(i) for i in device_ids)
    lan = {i: d for i, d in lan.items() if i in wanted}
    if not lan:
        raise MideaError("Keine der Klimaanlagen antwortet im Heimnetz (WLAN der Anlage? gleiches Netz wie der Server?)")
    # Schluessel gibt es nur noch ueber die SmartHome-Cloud (App "MSmartHome"); NetHome Plus antwortet mit 9999.
    # Feste Kennung: msmart wuerfelt sonst bei jedem Start eine neue, und Midea laesst nur wenige "angemeldete Geraete" je Konto zu (65027).
    mcloud.BaseCloud.DEVICE_ID = _own_device_id()
    cloud = mcloud.SmartHomeCloud(region, account=account, password=password)
    try:
        await cloud.login()
    except Exception as e:                                   # noqa: BLE001
        msg = _cloud_explain(e)
        if "65027" in msg:
            msg = ("MSmartHome: zu viele angemeldete Geräte für dieses Konto (65027) – in der MSmartHome-App unter "
                   "Profil → Angemeldete Geräte verwalten einen Eintrag abmelden und noch einmal versuchen")
        _login_fail[account] = (time.time(), msg, _login_wait(msg))
        _save_login_fail()
        raise MideaError(msg)
    if _login_fail.pop(account, None):
        _save_login_fail()
    out = {}
    for did, d in lan.items():
        for endian in ("little", "big"):
            try:
                token, key = await _smarthome_token(cloud, Security.udpid(did.to_bytes(6, endian)).hex(), did)
                dev = AC(ip=d.ip, port=int(d.port), device_id=did)
                await dev.authenticate(token, key)
                await dev.refresh()
            except Exception as e:                           # noqa: BLE001 - andere Byte-Reihenfolge versuchen
                log.info("Midea lokal %s (%s): %s", did, endian, e)
                if "3201" in str(e):                         # Anlage steckt nicht in diesem MSmartHome-Konto
                    break
                continue
            out[did] = {"ip": d.ip, "port": int(d.port), "version": d.version, "sn": d.sn, "raw_name": d.name, "token": token, "key": key}
            break
    return out


def local_keys(region: str, account: str, password: str, device_ids: list) -> dict:
    return _run(_local_keys((region or DEFAULT_REGION).upper(), account, password, [int(i) for i in device_ids]), DISCOVER_TIMEOUT_S + 90)


# ---------------------------------------------------------------- Cloud-Weg (ohne lokalen Schluessel)
# Midea gibt den lokalen Schluessel teils nicht mehr heraus (Cloud-Antwort 9999). Dann steuert die App die Anlage ueber die NetHome-Plus-Cloud:
# Bibliothek `midea-beautiful-air`, Konto (E-Mail/Passwort) bleibt auf dem Server. Langsamer als lokal und braucht Internet.
CLOUD_FANS = {"silent": 20, "low": 40, "medium": 60, "high": 80, "max": 100, "auto": 102}
CLOUD_MODES = {"auto": 1, "cool": 2, "dry": 3, "heat": 4, "fan_only": 5}
CLOUD_MIN_C, CLOUD_MAX_C = 16.0, 31.0
_clouds: dict[str, object] = {}                             # Konto -> angemeldete MideaCloud
_cdevs: dict[str, object] = {}                              # Geraete-ID -> LanDevice (nur Cloud)
_clock = threading.Lock()
_cdlocks: dict[str, threading.Lock] = {}


def _mb():
    try:
        import midea_beautiful as mb
    except ImportError:
        raise MideaError("Die Bibliothek „midea-beautiful-air“ ist auf dem Server nicht installiert (Server: venv/bin/pip install -r app/requirements.txt, dann die App neu starten)")
    _install_login_gate(mb)
    return mb


def _cloud_explain(e: Exception) -> str:
    name, msg = e.__class__.__name__, str(e)
    low = (name + " " + msg).lower()
    if "7610" in low or "too many failed login" in low:
        return "Midea hat das Konto wegen zu vieler Anmeldungen vorübergehend gesperrt (7610) – BlueNexus wartet jetzt 30 Min, bitte nichts tun"
    if "authentication" in low or "login" in low or "password" in low:
        return f"Anmeldung bei der Midea-Cloud fehlgeschlagen ({msg or name}) – E-Mail/Passwort prüfen"
    if "timeout" in low or "timed out" in low or "connection" in low:
        return "Die Midea-Cloud antwortet nicht (Internet/Zeitüberschreitung)"
    return f"{name}: {msg}" if msg else name


LOGIN_BACKOFF_S = 300.0                                     # nach fehlgeschlagener Anmeldung so lange nicht erneut anmelden (zu viele Anmeldungen sperren das Konto)
LOGIN_BACKOFF_AUTH_S = 3600.0                               # bei "Passwort falsch" deutlich laenger: staendiges Wiederholen kann das Konto sperren
LOGIN_BACKOFF_LOCK_S = 1800.0                               # Midea meldet "zu viele Anmeldungen" (7610): lange Ruhe, sonst verlaengert jeder Versuch die Sperre
LOGIN_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midea_login.json")


def _load_login_fail() -> dict:
    """Fehlgeschlagene Anmeldungen ueberleben einen Neustart der App (sonst meldet sich jeder Neustart sofort wieder an und haemmert auf das Konto)."""
    try:
        with open(LOGIN_STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {k: (float(v[0]), str(v[1]), float(v[2])) for k, v in d.items() if isinstance(v, list) and len(v) == 3}
    except (OSError, ValueError, TypeError, IndexError):
        return {}


def _save_login_fail():
    try:
        with open(LOGIN_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({k: list(v) for k, v in _login_fail.items()}, f)
    except OSError:
        pass


_login_fail: dict[str, tuple] = _load_login_fail()          # Konto -> (Zeit, Meldung, Wartezeit in s)
_login_last: dict[str, float] = {}                          # Konto -> Zeit des letzten Anmeldeversuchs
_login_tl = threading.local()                               # .manual = True, solange eine von Hand ausgeloeste Anmeldung laeuft


def _login_wait(msg: str) -> float:
    low = msg.lower()
    if "7610" in low or "too many" in low or "retry later" in low:
        return LOGIN_BACKOFF_LOCK_S
    if "authentication" in low or "password" in low:
        return LOGIN_BACKOFF_AUTH_S
    return LOGIN_BACKOFF_S


DEVICE_ID_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midea_device_id.txt")
_SHARED_DEVICE_ID = "c1acad8939ac0d7d"                       # fest in midea-beautiful eingebaut - teilen sich alle Nutzer der Bibliothek weltweit


def _own_device_id() -> str:
    """Eigene, dauerhafte Geraete-Kennung dieser Anlage (wie jede echte App-Installation). Mit der eingebauten Kennung meldet sich jede
    Installation als dasselbe Handy an - Midea sperrt dann Anmeldungen (7610), obwohl die Handy-App mit demselben Konto sofort reinkommt."""
    try:
        with open(DEVICE_ID_PATH, encoding="utf-8") as f:
            v = f.read().strip().lower()
        if len(v) == 16 and all(c in "0123456789abcdef" for c in v):
            return v
    except OSError:
        pass
    v = os.urandom(8).hex()
    try:
        with open(DEVICE_ID_PATH, "w", encoding="utf-8") as f:
            f.write(v)
    except OSError:
        pass
    return v


def _install_login_gate(mb):
    """Jede Anmeldung bei der Midea-Cloud laeuft durch diese Schranke - auch die, die die Bibliothek selbst ausloest.
    midea-beautiful meldet sich bei Fehlern wie 3004 ("value is illegal") oder 3106 (Sitzung ungueltig) mitten in einer Abfrage
    stillschweigend neu an. Bei drei Klimaanlagen und Abfragen alle 45 s waren das so viele Anmeldungen, dass Midea das Konto
    sperrte (7610 "Too many failed login attempts", vorher auch als "Passwort falsch (3101)")."""
    import midea_beautiful.cloud as mcloud
    from midea_beautiful.cloud import MideaCloud
    if getattr(MideaCloud, "_bnx_gated", False):
        return
    mcloud.CLOUD_API_DEVICE_ID = _own_device_id()            # Voreinstellung fuer jede neue MideaCloud (connect_to_cloud, Suche)
    for name in ("_login_proxied", "_login_non_proxied"):
        orig = getattr(MideaCloud, name)

        def gated(self, _orig=orig):
            acc = self._account
            manual = getattr(_login_tl, "manual", False)
            now = time.time()
            if not manual:
                # automatisch nie: jede Anmeldung, die Midea ablehnt, verlaengert die Sperre (7610). Nur von Hand (☁ Zugang, ⇄ Lokal).
                raise MideaError("Midea-Cloud: Sitzung abgelaufen – automatische Anmeldung ist abgeschaltet (sonst sperrt Midea das Konto). "
                                 "Abhilfe: Klimaanlage → „⇄ Lokal“ (einmalig, danach ohne Cloud) oder ☁ Zugang")
            _login_last[acc] = now
            log.info("Midea-Cloud: Anmeldung für %s (%s)", acc, "von Hand" if manual else "automatisch")
            try:
                r = _orig(self)
            except Exception as e:                           # noqa: BLE001
                msg = _cloud_explain(e)
                _login_fail[acc] = (time.time(), msg, _login_wait(msg))
                _save_login_fail()
                raise
            if _login_fail.pop(acc, None):
                _save_login_fail()
            return r
        setattr(MideaCloud, name, gated)
    MideaCloud._bnx_gated = True

# Die Midea-Cloud begrenzt, wie oft und von wie vielen Orten man sich anmelden darf. Jeder Neustart der App (Update!) meldete sich bisher neu an -
# nach ein paar Neustarts am Tag lehnt die Cloud die Anmeldung ab ("Passwort falsch (3101)"). Darum wird die laufende Sitzung auf der Platte gemerkt
# und nach einem Neustart weiterverwendet; nur wenn sie abgelaufen ist, meldet die Bibliothek sich selbst neu an.
SESSION_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "midea_session.json")
_SESSION_ATTRS = ("_session", "_login_id", "_country_code", "_id_adapt", "_mas_url", "_sse_url", "_api_url", "_uid", "_header_access_token", "_pushtoken", "_device_id")
_session_saved: dict[str, str] = {}                         # Konto -> zuletzt gespeicherter Stand (nur Aenderungen schreiben)


def _fp(account: str, password: str) -> str:
    return hashlib.sha256((account + "\0" + password).encode("utf-8")).hexdigest()


def _sessions_load() -> dict:
    try:
        with open(SESSION_STATE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _sessions_write(d: dict):
    try:
        with open(SESSION_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
        try:
            os.chmod(SESSION_STATE_PATH, 0o600)
        except OSError:
            pass
    except OSError:
        pass


def _session_save(account: str, password: str, cloud) -> None:
    """Sitzung merken (nur wenn sich etwas geaendert hat)."""
    try:
        state = {a: getattr(cloud, a) for a in _SESSION_ATTRS if hasattr(cloud, a)}
        if not state.get("_session"):
            return
        blob = json.dumps(state, sort_keys=True, default=str)
        if _session_saved.get(account) == blob:
            return
        d = _sessions_load()
        d[account] = {"fp": _fp(account, password), "ts": time.time(), "state": state}
        _sessions_write(d)
        _session_saved[account] = blob
    except Exception:                                        # noqa: BLE001 - das Merken ist nur eine Erleichterung
        pass


def _session_forget(account: str) -> None:
    _session_saved.pop(account, None)
    d = _sessions_load()
    if d.pop(account, None) is not None:
        _sessions_write(d)


def _session_restore(mb, account: str, password: str):
    """Eine gemerkte Sitzung wiederherstellen (ohne Anmeldung). None, wenn es keine gibt oder sie nicht passt."""
    try:
        ent = _sessions_load().get(account)
        if not ent or ent.get("fp") != _fp(account, password) or not ent.get("state", {}).get("_session"):
            return None
        from midea_beautiful.cloud import MideaCloud
        from midea_beautiful.midea import DEFAULT_APP_ID, DEFAULT_APPKEY, DEFAULT_HMACKEY, DEFAULT_IOTKEY, DEFAULT_PROXIED, DEFAULT_SIGNKEY
        st = ent["state"]
        if st.get("_device_id") and st.get("_device_id") != _own_device_id():
            return None                                       # Sitzung mit der alten, geteilten Kennung -> einmal neu anmelden
        c = MideaCloud(appkey=DEFAULT_APPKEY, account=account, password=password, appid=DEFAULT_APP_ID, hmac_key=DEFAULT_HMACKEY, iot_key=DEFAULT_IOTKEY,
                       api_url=st.get("_api_url") or None, proxied=DEFAULT_PROXIED, sign_key=DEFAULT_SIGNKEY, pushtoken=st.get("_pushtoken"), device_id=st.get("_device_id"))
        for a in _SESSION_ATTRS:
            if a in st and a not in ("_api_url",):
                setattr(c, a, st[a])
        if st.get("_api_url"):
            c._api_url = st["_api_url"]
        sess = c._session
        if c._proxied:
            c._security.set_access_token(str(sess.get("accessToken")), str(sess.get("randomData")))
        else:
            c._security.access_token = str(sess.get("accessToken"))
        _session_saved[account] = json.dumps({a: getattr(c, a) for a in _SESSION_ATTRS if hasattr(c, a)}, sort_keys=True, default=str)
        return c
    except Exception as e:                                   # noqa: BLE001 - dann einfach normal anmelden
        log.info("Gemerkte Midea-Sitzung nicht nutzbar (%s) – normale Anmeldung", e)
        _session_forget(account)
        return None


def _cloud_conn(account: str, password: str, manual: bool = False):
    mb = _mb()
    with _clock:
        c = _clouds.get(account)
        if c is None:
            hit = _login_fail.get(account)
            if hit and not manual and time.time() - hit[0] < hit[2]:
                left = int(hit[2] - (time.time() - hit[0]))
                raise MideaError(f"{hit[1]} (nächster Versuch in {left // 60 + 1} Min – zum sofortigen Versuch: Klimaanlage → ☁ Zugang; "
                                 f"bei falschem Passwort: Klimaanlage ✎ → „Zugang erneuern“)")
            c = None if manual else _session_restore(mb, account, password)          # nach einem Neustart die gemerkte Sitzung weiterverwenden
            if c is not None:
                c.max_retries = 2
                _clouds[account] = c
                return c
            _login_tl.manual = manual                        # die Schranke (_install_login_gate) merkt Fehlversuche und Wartezeiten
            try:
                c = mb.connect_to_cloud(account=account, password=password)
            finally:
                _login_tl.manual = False
            c.max_retries = 2
            _clouds[account] = c
            _session_save(account, password, c)
        return c


def cloud_forget(accounts, dev_ids=()):
    """Gemerkte Anmeldungen/Verbindungen verwerfen (nach neuen Zugangsdaten)."""
    with _clock:
        for a in accounts:
            _clouds.pop(a, None)
            _session_forget(a)
            if _login_fail.pop(a, None):
                _save_login_fail()
        for i in dev_ids:
            _cdevs.pop(i, None)
            _cache.pop(i, None)


def _cloud_list(account: str, password: str) -> list[dict]:
    """Klimaanlagen des NetHome-Plus-Kontos (ohne Netzwerksuche)."""
    try:
        c = _cloud_conn(account, password, manual=True)            # von Hand ausgeloest: immer versuchen
        items = c.list_appliances(force=True)
    except MideaError:
        raise
    except Exception as e:                                   # noqa: BLE001
        with _clock:
            _clouds.pop(account, None)
        raise MideaError(_cloud_explain(e))
    out = []
    for x in items:
        t = str(x.get("type") or "").lower()
        if t not in ("0xac", "ac", "172", "-84"):
            continue
        out.append({"id": f"midea-{x['id']}", "device_id": int(x["id"]), "ip": "", "port": 0, "raw_name": x.get("name"), "sn": x.get("sn"), "version": 0,
                    "token": None, "key": None, "online": True, "supported": True, "cloud": True, "cloud_account": account, "cloud_password": password})
    if not out:
        raise MideaError("Im NetHome-Plus-Konto ist keine Klimaanlage eingetragen")
    return out


def _cloud_dev(d: dict):
    mb = _mb()
    cloud = _cloud_conn(d["cloud_account"], d["cloud_password"])
    dev = _cdevs.get(d["id"])
    if dev is None:
        dev = mb.appliance_state(cloud=cloud, use_cloud=True, appliance_id=str(d["device_id"]), appliance_type="0xAC", retries=2, timeout=8)
        _cdevs[d["id"]] = dev
    return cloud, dev


def _cloud_sync_extras(dev):
    """Die Bibliothek uebernimmt Eco/Trocknen nicht aus der Antwort, schickt sie aber bei jedem Setzen mit - sonst waere Eco danach aus."""
    try:
        from midea_beautiful.command import AirConditionerResponse
        r = AirConditionerResponse(dev.state.latest_data)
        dev.state.eco_mode = r.eco
        dev.state.dryer = r.dryer
    except Exception:                                        # noqa: BLE001
        pass


def _cloud_snapshot(dev) -> dict:
    st = dev.state
    inv_mode = {v: k for k, v in CLOUD_MODES.items()}
    inv_fan = {v: k for k, v in CLOUD_FANS.items()}
    v, h = bool(st.vertical_swing), bool(st.horizontal_swing)
    return {"online": bool(dev.online), "on": bool(st.running), "mode": inv_mode.get(int(st.mode), str(st.mode)), "target_c": float(st.target_temperature),
            "indoor_c": st._indoor_temperature, "outdoor_c": st._outdoor_temperature,
            "fan": inv_fan.get(int(st.fan_speed), int(st.fan_speed)), "swing": "both" if v and h else "vertical" if v else "horizontal" if h else "off",
            "eco": bool(st.eco_mode)}


def _cloud_guard(d: dict):
    return _cdlocks.setdefault(d["id"], threading.Lock())


def _cloud_drop(d: dict, e: Exception | None = None):
    """Nach einem Fehler: Verbindung nur bei Anmelde-/Sitzungsproblemen verwerfen (die Bibliothek meldet sich bei abgelaufener Sitzung selbst neu an)."""
    low = (str(e) + e.__class__.__name__).lower() if e else "login"
    if "login" in low or "session" in low or "authentication" in low:
        with _clock:
            _clouds.pop(d.get("cloud_account"), None)
            _session_forget(d.get("cloud_account"))                  # sonst wuerde dieselbe unbrauchbare Sitzung wiederhergestellt


def _cloud_read(d: dict) -> dict:
    with _cloud_guard(d):
        try:
            cloud, dev = _cloud_dev(d)
            dev.refresh(cloud)
            _session_save(d["cloud_account"], d["cloud_password"], cloud)       # hat die Bibliothek sich zwischendurch neu angemeldet, den neuen Stand merken
            _cloud_sync_extras(dev)
            return _cloud_snapshot(dev)
        except MideaError:
            raise
        except Exception as e:                               # noqa: BLE001
            _cloud_drop(d, e)
            raise MideaError(_cloud_explain(e))


def _cloud_apply(d: dict, power=None, mode=None, target=None, fan=None, swing=None, eco=None) -> dict:
    with _cloud_guard(d):
        try:
            cloud, dev = _cloud_dev(d)
            dev.refresh(cloud)                              # apply schickt den ganzen Zustand -> erst aktuellen Stand holen
            if not dev.online:
                raise MideaError("Die Klimaanlage antwortet nicht (WLAN/Strom prüfen)")
            _cloud_sync_extras(dev)
            st = dev.state
            if power is not None:
                st.running = bool(power)
            if mode:
                if str(mode).lower() not in CLOUD_MODES:
                    raise MideaError(f"Unbekannter Wert „{mode}“")
                st.mode = CLOUD_MODES[str(mode).lower()]
            if target is not None:
                t = float(target)
                if not CLOUD_MIN_C <= t <= CLOUD_MAX_C:
                    raise MideaError(f"Solltemperatur zwischen {CLOUD_MIN_C:g} und {CLOUD_MAX_C:g} °C")
                st.target_temperature = round(t * 2) / 2
            if fan:
                if str(fan).lower() not in CLOUD_FANS:
                    raise MideaError(f"Unbekannter Wert „{fan}“")
                st.fan_speed = CLOUD_FANS[str(fan).lower()]
            if swing:
                sw = str(swing).lower()
                if sw not in ("off", "vertical", "horizontal", "both"):
                    raise MideaError(f"Unbekannter Wert „{swing}“")
                st.vertical_swing, st.horizontal_swing = sw in ("vertical", "both"), sw in ("horizontal", "both")
            if eco is not None:
                st.eco_mode = bool(eco)
            dev.apply(cloud)                                # holt danach selbst den neuen Zustand
            return _cloud_snapshot(dev)
        except MideaError:
            raise
        except Exception as e:                               # noqa: BLE001
            _cloud_drop(d, e)
            raise MideaError(_cloud_explain(e))


def _cloud_details(d: dict) -> dict:
    snap = _cloud_read(d)
    return {"state": snap, "min": CLOUD_MIN_C, "max": CLOUD_MAX_C, "step": 0.5,
            "modes": [{"key": k, "label": MODE_LABELS[k]} for k in CLOUD_MODES],
            "fans": [{"key": k, "label": FAN_LABELS[k]} for k in CLOUD_FANS],
            "swings": [{"key": k, "label": SWING_LABELS[k]} for k in ("off", "vertical", "horizontal", "both")],
            "supports_eco": True}
