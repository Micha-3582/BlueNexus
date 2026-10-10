"""Demo-Modus, Teil 2: Geraete-, Sensor- und Kamera-Simulation (nur mit BLUENEXUS_DEMO=1, wird von activate() eingehaengt).

Ersetzt die Netzwerkzugriffe auf Shelly/Tasmota/Tuya/Zigbee/Homematic-CCU/Midea/WLED/Kameras durch erfundene, plausible Zustaende.
Schaltbefehle werden nur im Speicher gemerkt (nichts verlaesst das Geraet, nichts wird gespeichert).
"""
from __future__ import annotations

import math
import os
import re
import threading
import time
from datetime import datetime

from demo import ACTIVE

_MEDIA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo_media")
_lock = threading.Lock()
_over: dict = {}          # Geraete-ID -> vom Benutzer gesetzter Schaltzustand
_mid: dict = {}           # Klimaanlagen-ID -> Zustand
_hm_over: dict = {}       # (Adresse, Datenpunkt) -> gesetzter Wert (Homematic)
_wled: dict = {}          # WLED-ID -> {"bri": ...}

_LIGHT = ("licht", "lampe", "beleuchtung", "led", "deko", "lichter")
_OUTDOOR = ("außen", "aussen", "hof", "carport", "garage", "haustür", "tor", "eierhaus", "hühner", "huehner", "poolhaus", "terrasse")
_POWER = [("waschmaschine", 480), ("spül", 1100), ("spuel", 1100), ("trockner", 1900), ("wärmepumpe", 1650), ("waermepumpe", 1650),
          ("infrarot", 1500), ("entfeuchter", 260), ("brenner", 15), ("umw", 45), ("lüfter", 22), ("luefter", 22), ("sandfilter", 380),
          ("gartenpumpe", 650), ("lan", 8), ("modem", 12), ("magnetventil", 4), ("led", 9), ("lampe", 28), ("beleuchtung", 45), ("licht", 32)]


def _h(now=None) -> float:
    now = now or datetime.now()
    return now.hour + now.minute / 60.0


def _default_on(name: str, now=None) -> bool:
    n, h = (name or "").lower(), _h(now)
    if any(k in n for k in _LIGHT):
        if any(k in n for k in _OUTDOOR):
            return h >= 17.5 or h < 6.5
        return 18 <= h < 22.5
    for key, rule in (("brenner", (5 <= h < 8) or (17 <= h < 21)), ("umw", (5 <= h < 9) or (16 <= h < 22)),
                      ("waschmaschine", 9 <= h < 11), ("spül", 20 <= h < 22), ("spuel", 20 <= h < 22),
                      ("trockner", 11 <= h < 13), ("wärmepumpe", 10.5 <= h < 16.5), ("waermepumpe", 10.5 <= h < 16.5),
                      ("infrarot", 11 <= h < 14), ("entfeuchter", 8 <= h < 20), ("sandfilter", 9 <= h < 15)):
        if key in n:
            return rule
    return any(k in n for k in ("lüfter", "luefter", "lan", "modem", "boiler"))


def _watts(name: str, d: dict | None = None) -> float:
    n = (name or "").lower()
    base = next((w for k, w in _POWER if k in n), None)
    if base is None:
        base = float((d or {}).get("power_w") or 40)
    return round(base * (1.0 + 0.03 * math.sin(time.time() / 7.0)), 1)


def _is_on(d: dict) -> bool:
    with _lock:
        if d.get("id") in _over:
            return _over[d["id"]]
    return _default_on(d.get("name", ""))


def _midea_state(d: dict) -> dict:
    cid = d["id"]
    with _lock:
        st = _mid.get(cid)
        if st is None:
            st = {"online": True, "on": 12 <= _h() < 17,
                  "mode": "cool" if datetime.now().month in (5, 6, 7, 8, 9) else "heat", "target_c": 23.0, "indoor_c": 22.5,
                  "outdoor_c": 14.0, "fan": "auto", "swing": "off", "eco": False}
            _mid[cid] = st
        return dict(st)


def _midea_pub(st: dict) -> dict:
    import midea
    return {**st, "power": None, "info": midea.info_text(st)}


def _device_status(d: dict) -> dict:
    if d.get("kind") == "midea":
        return _midea_pub(_midea_state(d))
    on = _is_on(d)
    if d.get("kind") == "wled":
        bri = int(_wled.get(d["id"], {}).get("bri", 70))
        return {"online": True, "on": on, "power": None, "brightness": bri if on else None}
    return {"online": True, "on": on, "power": _watts(d.get("name", ""), d) if on else 0.0}


def _device_set(dev_id: str, on: bool, timer_s=None) -> dict:
    import shelly
    d = shelly._find(dev_id)
    if not d:
        raise shelly.ShellyError("Gerät nicht gefunden")
    if d.get("switchable") is False:
        raise shelly.ShellyError("Dieses Gerät ist nur zur Überwachung eingestellt und nicht schaltbar")
    if d.get("kind") == "midea":
        st = _midea_state(d)
        with _lock:
            _mid[d["id"]] = {**st, "on": bool(on)}
    else:
        with _lock:
            _over[dev_id] = bool(on)
    return _device_status(d)


# ---- Homematic-CCU (JSON-RPC) --------------------------------------------------------------------------------------
def _hm_index() -> dict:
    """(Adresse, Datenpunkt) bzw. Adresse -> (Name, Art, invertiert). Sensoren genau je Datenpunkt, alles andere je Adresse."""
    import homematic
    idx: dict = {}
    try:
        import shelly
        for d in shelly.load_devices():
            if d.get("kind") == "homematic":
                idx.setdefault(str(d.get("address")), (d.get("name", ""), "switch", False))
                idx.setdefault(str(d.get("address")).split(":")[0], (d.get("name", ""), "switch", False))
    except Exception:
        pass
    try:
        for x in homematic.load_sensors():
            idx[(str(x.get("address")), x.get("datapoint"))] = (x.get("name", ""), "sensor", bool(x.get("invert")))
            idx.setdefault(str(x.get("address")).split(":")[0], (x.get("name", ""), "sensor", False))
    except Exception:
        pass
    for loader, kind in ((homematic.load_locks, "lock"), (homematic.load_blinds, "blind"),
                         (homematic.load_setpoints, "setpoint"), (homematic.load_sounds, "sound")):
        try:
            for x in loader():
                idx.setdefault(str(x.get("address")), (x.get("name", ""), kind, False))
                idx.setdefault(str(x.get("address")).split(":")[0], (x.get("name", ""), kind, False))
        except Exception:
            pass
    return idx


def _hm_get(address: str, key: str):
    base = str(address).split(":")[0]
    with _lock:
        if (address, key) in _hm_over:
            return _hm_over[(address, key)]
    idx = _hm_index()
    name, kind, inv = idx.get((str(address), key)) or idx.get(str(address)) or idx.get(base) or ("", "", False)
    n, t, h = name.lower(), time.time(), _h()
    if key == "UNREACH":
        return False
    if key in ("ACTUAL_TEMPERATURE", "TEMPERATURE"):
        if "vorlauf" in n:
            b = 58.0
        elif "rücklauf" in n or "ruecklauf" in n:
            b = 44.0
        elif "boiler" in n:
            b = 55.0
        elif any(k in n for k in ("außen", "aussen", "hof")):
            b = 11.0
        elif "keller" in n:
            b = 17.0
        else:
            b = 21.0
        return round(b + 0.7 * math.sin(t / 900.0), 1)
    if key in ("HUMIDITY", "ACTUAL_HUMIDITY"):
        return round(52 + 5 * math.sin(t / 1300.0), 0)
    if key in ("ILLUMINATION", "BRIGHTNESS", "CURRENT_ILLUMINATION"):
        return round(max(0.0, 180 * math.sin(math.pi * (h - 7) / 11)), 0) if 7 < h < 18 else 0.0
    if key == "POWER":
        return round(_watts(name), 1) if _default_on(name) else 0.0
    if key in ("MOTION", "PRESENCE_DETECTION_STATE"):
        return int(t / 20) % 53 == 0
    if key.startswith("PRESS_"):
        return False
    if key == "LOCK_STATE":
        return 1
    if key == "LEVEL":
        return 0.6 if kind == "blind" else (1.0 if _default_on(name) else 0.0)
    if key in ("SET_POINT_TEMPERATURE", "SET_TEMPERATURE"):
        return 18.0 if "schlafzimmer" in n else 20.5 if "kinder" in n else 21.0
    if key == "STATE":
        if kind in ("switch", ""):
            return _default_on(name)
        return False              # Kontakt/Eingang: Rohwert "zu"/inaktiv (die App wendet "invertiert" danach selbst an: bei invertierten Sensoren ergibt das TRUE = zu)
    return 0


def _hm_call(method: str, params: dict | None = None):
    p = params or {}
    if method == "Interface.getValue":
        return _hm_get(p.get("address", ""), p.get("valueKey", ""))
    if method == "Interface.setValue":
        with _lock:
            _hm_over[(p.get("address", ""), p.get("valueKey", ""))] = p.get("value")
            if p.get("valueKey") == "LOCK_TARGET_LEVEL":
                _hm_over[(p.get("address", ""), "LOCK_STATE")] = 1 if p.get("value") in (0, 0.0) else 2
        return None
    if method == "Interface.putParamset":
        for it in p.get("set", []) or []:
            if it.get("name") in ("STATE", "LEVEL"):
                with _lock:
                    _hm_over[(p.get("address", ""), it["name"])] = it.get("value")
        return None
    return []


# ---- Kameras -------------------------------------------------------------------------------------------------------
def _slug(s: str) -> str:
    s = (s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _image_for(item: dict) -> bytes:
    for key in (_slug(item.get("name", "")), item.get("id", ""), "default"):
        p = os.path.join(_MEDIA, key + ".jpg")
        if key and os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
    raise RuntimeError("Demo-Kamerabild fehlt (app/demo_media)")


def _cam_snapshot(item: dict, max_age=None) -> bytes:
    import camera
    try:
        return _image_for(item)
    except RuntimeError as e:
        raise camera.CameraError(str(e))


class _DemoStream:
    """MJPEG-Iterator (wie camera._Stream): liefert alle 1,5 s das Standbild, endet nach 15 Minuten."""

    def __init__(self, data: bytes):
        self.data, self._done, self._t0 = data, False, time.time()

    def __iter__(self):
        return self

    def __next__(self):
        if self._done or time.time() - self._t0 > 900:
            raise StopIteration
        time.sleep(1.5)
        return (b"--ffmpeg\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(self.data)).encode() + b"\r\n\r\n" + self.data + b"\r\n")

    def close(self, release=True):
        self._done = True


def _cam_stream(item: dict, quality=None):
    import camera
    try:
        return _DemoStream(_image_for(item))
    except RuntimeError as e:
        raise camera.CameraError(str(e))


# ---- Wetter (im Format von Open-Meteo, laeuft durch weather._parse) ---------------------------------------------------
def _weather_forecast(force: bool = False) -> dict:
    import weather
    from datetime import timedelta
    from demo import _day_factor, _season
    now = datetime.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    code_for = lambda f: 0 if f >= 0.95 else 1 if f >= 0.75 else 2 if f >= 0.6 else 3 if f >= 0.4 else 61
    hourly = {k: [] for k in ("time", "temperature_2m", "precipitation_probability", "precipitation", "weather_code", "cloud_cover", "wind_speed_10m")}
    daily = {k: [] for k in ("time", "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                             "precipitation_probability_max", "wind_speed_10m_max", "sunrise", "sunset", "sunshine_duration")}

    def at(t):
        f, s = _day_factor(t.date()), _season(t.date())
        mean = 3 + 16 * (s - 0.3) / 0.7 - (1.5 if f < 0.5 else 0)
        amp = 2.5 + 4 * f
        temp = mean + amp * math.sin(2 * math.pi * (t.hour + t.minute / 60.0 - 9) / 24.0)
        return f, temp

    for d in range(7):
        base = day0 + timedelta(days=d)
        f, s = _day_factor(base.date()), _season(base.date())
        length = 7.5 + 9.0 * s
        rise = 13.0 - length / 2.0
        temps = []
        for h in range(24):
            t = base + timedelta(hours=h)
            _, temp = at(t)
            temps.append(temp)
            rain = f < 0.4
            hourly["time"].append(t.strftime("%Y-%m-%dT%H:00"))
            hourly["temperature_2m"].append(round(temp, 1))
            hourly["precipitation_probability"].append(70 if rain else 10 if f >= 0.75 else 30)
            hourly["precipitation"].append(round(0.4 + 0.3 * math.sin(h), 1) if rain and 8 <= h <= 18 else 0.0)
            hourly["weather_code"].append(code_for(f))
            hourly["cloud_cover"].append(int(100 - f * 90))
            hourly["wind_speed_10m"].append(round(8 + 8 * (1 - f) + 2 * math.sin(h / 3.0), 1))
        daily["time"].append(base.strftime("%Y-%m-%d"))
        daily["weather_code"].append(code_for(f))
        daily["temperature_2m_max"].append(round(max(temps), 1))
        daily["temperature_2m_min"].append(round(min(temps), 1))
        daily["precipitation_sum"].append(5.5 if f < 0.4 else 0.0)
        daily["precipitation_probability_max"].append(70 if f < 0.4 else 10 if f >= 0.75 else 30)
        daily["wind_speed_10m_max"].append(round(18 + 10 * (1 - f), 1))
        daily["sunrise"].append((base + timedelta(hours=rise)).strftime("%Y-%m-%dT%H:%M"))
        daily["sunset"].append((base + timedelta(hours=rise + length)).strftime("%Y-%m-%dT%H:%M"))
        daily["sunshine_duration"].append(round(length * 3600 * f * 0.9))
    f, temp = at(now)
    h = _h(now)
    s = _season(now.date())
    length = 7.5 + 9.0 * s
    rise = 13.0 - length / 2.0
    current = {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": round(temp, 1), "apparent_temperature": round(temp - 1.5, 1),
               "relative_humidity_2m": int(85 - 25 * f), "is_day": int(rise <= h <= rise + length), "precipitation": 0.0,
               "weather_code": code_for(f), "cloud_cover": int(100 - f * 90), "wind_speed_10m": round(8 + 8 * (1 - f), 1), "wind_direction_10m": 250}
    loc = weather.get_location()
    data = weather._parse({"current": current, "hourly": hourly, "daily": daily}, loc.get("name") or "Demo")
    data.update(configured=True, error=None, updated=now.isoformat(timespec="seconds"))
    return data


# ---- Einhaengen ----------------------------------------------------------------------------------------------------
def activate() -> None:
    """Ersetzt die Netzwerk-Zugriffe auf Geraete/Kameras/CCU durch die Simulation (nur wenn BLUENEXUS_DEMO=1)."""
    if not ACTIVE:
        return
    if hasattr(time, "tzset"):                              # Demo laeuft immer in deutscher Zeit (Container steht oft auf UTC: Tagesverlauf, Uhrzeit-Karte)
        os.environ["TZ"] = "Europe/Berlin"
        time.tzset()
    try:                                                    # Historie mitrutschen lassen (siehe demo_roll.py)
        import demo_roll
        demo_roll.roll(os.path.dirname(os.path.abspath(__file__)))
    except Exception:                                       # noqa: BLE001 - die Demo muss auch ohne Verschiebung starten
        import logging
        logging.getLogger("demo_roll").exception("Historie konnte nicht verschoben werden")
    import camera
    import homematic
    import midea
    import shelly
    import wled
    import wol
    import zigbee

    shelly.status = _device_status
    shelly.set_state = _device_set
    try:                                                    # Teilen: erfundene Freigaben/Quelle, Angebot der Quelle ohne Netzwerkzugriff
        import share
        seed_share()
        share.source_items = lambda source_id: [dict(x) for x in DEMO_SOURCE_ITEMS]
    except Exception:                                       # noqa: BLE001 - die Demo muss auch ohne Teilen-Daten starten
        import logging
        logging.getLogger("demo_sim").exception("Teilen-Daten konnten nicht angelegt werden")
    homematic._call = _hm_call
    homematic.push_active = lambda: False

    def _m_params(d, **kw):
        st = _midea_state(d)
        kw = {k: v for k, v in kw.items() if v not in (None, "")}
        if "power" in kw:
            st["on"] = bool(kw.pop("power"))
        for k_in, k_out in (("mode", "mode"), ("target", "target_c"), ("fan", "fan"), ("swing", "swing"), ("eco", "eco")):
            if k_in in kw:
                st[k_out] = kw[k_in]
        with _lock:
            _mid[d["id"]] = st
        return _midea_pub(st)

    def _m_details(d):
        return {"state": _midea_pub(_midea_state(d)), "min": 16.0, "max": 30.0, "step": 0.5,
                "modes": [{"key": k, "label": v} for k, v in midea.MODE_LABELS.items()],
                "fans": [{"key": k, "label": v} for k, v in midea.FAN_LABELS.items()],
                "swings": [{"key": k, "label": v} for k, v in midea.SWING_LABELS.items()],
                "supports_eco": True}

    midea.status = lambda d: _midea_pub(_midea_state(d))
    midea.set_params = _m_params
    midea.set_state = lambda d, on, timer_s=None: _m_params(d, power=bool(on))
    midea.details = _m_details

    def _w_details(d):
        return {"partial": False, "effects": [{"id": i, "name": n} for i, n in enumerate(["Solid", "Blink", "Breathe", "Rainbow", "Fire 2012", "Aurora"])],
                "palettes": [{"id": i, "name": n} for i, n in enumerate(["Default", "Party", "Ocean", "Forest"])],
                "palette": 0, "presets": [{"id": 1, "name": "Gemütlich"}, {"id": 2, "name": "Party"}], "color": "#ffa000", "effect": 0, "preset": None}

    def _w_bri(d, pct):
        _wled[d["id"]] = {**_wled.get(d["id"], {}), "bri": int(pct)}
        with _lock:
            _over[d["id"]] = True
        return int(pct)

    wled.details = _w_details
    wled.set_brightness = _w_bri
    wled.set_color = lambda d, hexcolor: hexcolor
    wled.set_effect = lambda d, effect: int(effect or 0)
    wled.set_palette = lambda d, palette: int(palette or 0)
    wled.set_preset = lambda d, preset: int(preset or 0)
    wled.save_preset = lambda d, name: {"id": 3, "name": str(name)}

    zigbee.read_value = lambda sen: (False if sen.get("binary") else round(21.0 + 0.5 * math.sin(time.time() / 1100.0), 1))
    zigbee.read_setpoint = lambda sp: 21.0
    zigbee.set_setpoint = lambda sp, value: min(float(sp.get("max", 30)), max(float(sp.get("min", 5)), float(value)))

    wol.is_up = lambda ip: True
    import sandbox
    import weather
    _real_weather = weather.forecast

    def _weather_live(force: bool = False) -> dict:
        """Echtes Wetter von Open-Meteo (einzige Ausnahme vom Testmodus, nur dieser Thread); bei Fehler die Simulation."""
        try:
            with sandbox.allow_outbound():
                d = _real_weather(force)
            if d.get("configured") and not d.get("error") and d.get("daily"):
                return d
        except Exception:                                   # noqa: BLE001
            pass
        return _weather_forecast(force)

    weather.forecast = _weather_live

    camera.ffmpeg_path = lambda: "demo"          # Live-Ansicht verfuegbar melden (der Demo-Strom braucht kein ffmpeg)
    camera.snapshot = _cam_snapshot
    camera.stream = _cam_stream
    camera.motion_states = lambda item, force=False: {"md": False, "people": False, "vehicle": False, "dog_cat": False,
                                                       "support": {"md", "people", "vehicle", "dog_cat"}}
    camera.read_motion = lambda sen: False
    camera.device_info = lambda item: {"name": item.get("name", ""), "model": item.get("model", ""), "firmware": "demo"}


# ---- Teilen und Benutzer (nur Anzeige in der Demo-Ansicht) -----------------------------------------------------------------
def _find(items: list, *needles: str):
    """Erster Eintrag, dessen Name einen der Suchtexte enthaelt (ohne Gross-/Kleinschreibung)."""
    for n in needles:
        for it in items:
            if n.lower() in str(it.get("name") or "").lower():
                return it
    return None


def seed_share() -> None:
    """Legt erfundene Freigaben (Personen) und eine erfundene fremde Quelle an, solange es noch keine gibt. Die Schluessel sind Zufallswerte,
    die nirgends gespeichert werden - /share/v1/* liefert in der Demo also nie etwas."""
    import secrets
    import share
    import shelly
    import homematic
    import virtual
    if share._load(share.SHARES_PATH) or share._load(share.SOURCES_PATH):
        return
    devs = [d for d in shelly.load_devices() if d.get("kind") != "remote"]
    sens = [x for x in homematic.load_sensors() if x.get("source") != "remote"]
    virt = list(virtual.load())

    def ref(kind, it):
        return (kind + ":" + it["id"]) if it else None

    def items(*pairs):
        return [{"ref": r, "mode": m} for r, m in pairs if r]

    now = time.time()
    k_licht = _find(devs, "Küchenlicht", "Kuechenlicht", "Flurbeleuchtung")
    k_tuer = _find(devs, "Haustürbeleuchtung", "Haustuerbeleuchtung", "Aussenbeleuchtung")
    k_huhn = _find(devs, "Hühnerstall", "Huehnerstall")
    k_garage = _find(devs, "Garagenlampe", "Gartenpumpe")
    s_fenster = _find(sens, "Küche", "Kueche", "Fenster", "Tür", "Tuer")
    v_knopf = _find(virt, "Haustüröffner", "Haustueroeffner", "Warmwasser")
    shares = [
        {"id": "s-demo0001", "name": "Mama", "icon": "👩", "token_hash": secrets.token_hex(32), "created": now - 21 * 86400, "last_seen": now - 3600 * 5,
         "items": items((ref("device", k_licht), "control"), (ref("device", k_tuer), "control"), (ref("sensor", s_fenster), "view"))},
        {"id": "s-demo0002", "name": "Nachbar Tom", "icon": "🧑‍🔧", "token_hash": secrets.token_hex(32), "created": now - 9 * 86400, "last_seen": now - 86400 * 2,
         "items": items((ref("device", k_huhn), "control"), (ref("device", k_garage), "view"))},
        {"id": "s-demo0003", "name": "Ferienwohnung", "icon": "🏖️", "token_hash": secrets.token_hex(32), "created": now - 3 * 86400, "last_seen": 0,
         "items": items((ref("virtual", v_knopf), "control"), (ref("device", k_licht), "view"))},
    ]
    share._save(share.SHARES_PATH, shares)
    share._save(share.SOURCES_PATH, [{"id": "q-demo0001", "name": "Haus von Oma", "url": "https://oma.beispiel.de", "token": "bnx_demo_" + secrets.token_hex(12)}])


DEMO_SOURCE_ITEMS = [
    {"ref": "device:oma-heizung", "type": "device", "name": "Heizungspumpe", "icon": "♨️", "kind": "shelly", "control": True, "already": False},
    {"ref": "device:oma-licht", "type": "device", "name": "Flurlicht", "icon": "💡", "kind": "shelly", "control": True, "already": False},
    {"ref": "device:oma-klima", "type": "device", "name": "Klimaanlage Wohnzimmer", "icon": "❄️", "kind": "midea", "control": True, "already": False},
    {"ref": "sensor:oma-fenster", "type": "sensor", "name": "Fenster Küche", "icon": "🪟", "kind": "contact", "control": False, "already": False},
    {"ref": "sensor:oma-temp", "type": "sensor", "name": "Temperatur Wohnzimmer", "icon": "🌡️", "kind": "temperature", "control": False, "already": True},
]


def fake_users() -> list:
    """Erfundene Konten fuer 'Konto & Benutzer' in der Demo-Ansicht (die echten Konten der Instanz bleiben unsichtbar)."""
    import auth
    now = time.time()
    adm = dict(auth.PRESETS["admin"])
    rows = [
        ("mara", adm, now - 90 * 86400, now - 3600 * 2, None, True),
        ("jonas", adm, now - 60 * 86400, now - 86400, None, False),
        ("paul", auth.PRESETS["smarthome"], now - 40 * 86400, now - 86400 * 3, None, False),
        ("oma", auth.PRESETS["user"], now - 20 * 86400, now - 86400 * 9, "2027-03-31", False),
        ("demo", auth.PRESETS["demo"], now - 5 * 86400, now - 600, None, False),
    ]
    return [{"username": n, "permissions": dict(p), "created": c, "last_login": l, "expires": e, "owner": o} for n, p, c, l, e, o in rows]
