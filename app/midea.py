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
import logging
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


async def _authenticate_both_endians(cls, dev) -> bool:
    """Ersatz fuer Discover._authenticate_device: die Bibliothek bricht beim ersten Cloud-Fehler ab. Die Cloud antwortet auf die
    falsche Byte-Reihenfolge der Geraete-ID aber mit 9999 - deshalb beide Varianten probieren und erst dann aufgeben."""
    from msmart.cloud import CloudError
    from msmart.lan import AuthenticationError, Security
    cloud = await cls._get_cloud()                                      # Anmeldefehler gehen unveraendert nach oben
    last = None
    for endian in ("little", "big"):
        udpid = Security.udpid(dev.id.to_bytes(6, endian)).hex()
        try:
            token, key = await cloud.get_token(udpid)
        except CloudError as e:
            last = e
            continue
        try:
            await dev.authenticate(token, key)
            return True
        except AuthenticationError:                                     # andere Variante probieren
            continue
    if last:
        raise CloudError(f"Failed to get token from cloud. {last}")
    return False


async def _discover(region: str, account, password, target) -> list[dict]:
    AC, Discover, DeviceType = _lib()
    Discover._authenticate_device = classmethod(_authenticate_both_endians)
    kw = {"timeout": DISCOVER_TIMEOUT_S, "region": region, "auto_connect": True}
    if account and password:
        kw.update(account=account, password=password)
    if target:
        kw["target"] = target
    try:
        devs = await Discover.discover(**kw)
    except Exception as e:
        if "cloud" not in str(e).lower():
            raise
        # NetHome-Plus-Konto abgelehnt (z. B. "9999 system error") -> gleiche Abfrage ueber die SmartHome-Cloud (anderes Konto/Server)
        import msmart.discover as _md
        from msmart.cloud import SmartHomeCloud, CloudError
        orig = _md.NetHomePlusCloud
        _md.NetHomePlusCloud = SmartHomeCloud
        try:
            devs = await Discover.discover(**kw)
        except Exception as e2:
            raise CloudError(f"{e} / SmartHome-Cloud: {e2}") from e2
        finally:
            _md.NetHomePlusCloud = orig
    out = []
    for dev in devs:
        if getattr(dev, "type", None) != DeviceType.AIR_CONDITIONER:
            continue
        out.append({"id": f"midea-{dev.id}", "device_id": int(dev.id), "ip": dev.ip, "port": int(dev.port), "raw_name": dev.name, "sn": dev.sn,
                    "version": dev.version, "token": dev.token, "key": dev.key, "online": bool(dev.online), "supported": bool(dev.supported)})
    return out


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
    """Klimaanlagen im Heimnetz suchen (oder eine bestimmte IP). Rueckgabe ohne Token/Schluessel: [{id, ip, name, version, online, known}]."""
    global _scan_ts
    region = (region or DEFAULT_REGION).upper()
    if region not in REGIONS:
        raise MideaError("Region: " + ", ".join(REGIONS))
    account = (account or "").strip() or None
    local_err = None
    try:
        found = _run(_discover(region, account, password or None, _check_target(target)), DISCOVER_TIMEOUT_S + 40)
    except MideaError as e:
        found, local_err = [], e
    if account and password and (local_err or not found):
        # lokal kein Schluessel (Midea gibt ihn nicht mehr heraus) oder nichts gefunden -> Anlagen des Kontos ueber die Cloud
        try:
            found = _cloud_list(account, password)
        except MideaError as e2:
            raise MideaError(f"{local_err} / Cloud-Zugriff: {e2}" if local_err else str(e2))
    elif local_err:
        raise local_err
    _scan.clear()
    _scan.update({f["id"]: f for f in found})
    _scan_ts = time.time()
    return [{"id": f["id"], "ip": f["ip"] or "Cloud", "name": default_name(f), "model": "Midea Klimaanlage" + (" (über die Cloud)" if f.get("cloud") else ""), "version": f["version"], "online": f["online"],
             "supported": f["supported"], "known": f["id"] in set(known_ids), "room": ""} for f in found]


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
            raise MideaError(f"{default_name(f)}: Token/Schlüssel konnten nicht geholt werden (Region prüfen oder eigenes NetHome-Plus-Konto angeben)")
        out.append({"id": f["id"], "kind": "midea", "ip": f["ip"], "port": f["port"], "device_id": f["device_id"], "raw_name": f["raw_name"], "sn": f["sn"],
                    "version": f["version"], "token": f["token"], "key": f["key"], "mac": None, "gen": 0, "channel": 0, "model": "Midea Klimaanlage",
                    "name": default_name(f), "room": "", "icon": "❄️"})
    return out


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
    return mb


def _cloud_explain(e: Exception) -> str:
    name, msg = e.__class__.__name__, str(e)
    low = (name + " " + msg).lower()
    if "authentication" in low or "login" in low or "password" in low:
        return f"Anmeldung bei der Midea-Cloud fehlgeschlagen ({msg or name}) – E-Mail/Passwort prüfen"
    if "timeout" in low or "timed out" in low or "connection" in low:
        return "Die Midea-Cloud antwortet nicht (Internet/Zeitüberschreitung)"
    return f"{name}: {msg}" if msg else name


LOGIN_BACKOFF_S = 300.0                                     # nach fehlgeschlagener Anmeldung so lange nicht erneut anmelden (zu viele Anmeldungen sperren das Konto)
_login_fail: dict[str, tuple] = {}                          # Konto -> (Zeit, Meldung)


def _cloud_conn(account: str, password: str, manual: bool = False):
    mb = _mb()
    with _clock:
        c = _clouds.get(account)
        if c is None:
            hit = _login_fail.get(account)
            if hit and not manual and time.time() - hit[0] < LOGIN_BACKOFF_S:
                raise MideaError(f"{hit[1]} (nächster Versuch in {int(LOGIN_BACKOFF_S - (time.time() - hit[0]))} s – nicht gleichzeitig mit der Handy-App oder einem zweiten Server dasselbe Konto benutzen)")
            try:
                c = mb.connect_to_cloud(account=account, password=password)
            except Exception as e:                           # noqa: BLE001
                _login_fail[account] = (time.time(), _cloud_explain(e))
                raise
            _login_fail.pop(account, None)
            c.max_retries = 2
            _clouds[account] = c
        return c


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


def _cloud_read(d: dict) -> dict:
    with _cloud_guard(d):
        try:
            cloud, dev = _cloud_dev(d)
            dev.refresh(cloud)
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
