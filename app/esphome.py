"""
ESPHome-Geraete (Hardware-Taster und aehnliches) - LOKAL ueber die Weboberflaeche des Geraets (`web_server`, Port 80). Keine Zusatzpakete, nur `requests`.

Ein Eintrag im Geraeteregister (shelly.py, kind "esphome") = ein Eingang (`binary_sensor`) eines ESPHome-Geraets, z. B. ein Taster.
Messwerte (`sensor`: Temperatur, Luftfeuchte, Leistung ...) stehen als Sensoren (homematic.py, source "esphome") im Sensorregister; ihren Wert liefert
read_value() aus demselben Strom.
Die Weboberflaeche des Geraets liefert unter `GET /events` einen dauerhaften Strom (Server-Sent-Events): beim Verbinden den Zustand aller Eintraege
(`event: state`), danach jede Aenderung sofort, alle 30 Sekunden ein `event: ping`. Pro Geraet (IP-Adresse) haelt BlueNexus eine solche Verbindung
(Hintergrund-Thread, mit Wiederverbindung und wachsender Wartezeit). Springt ein Eingang von AUS auf AN, gilt das als Tastendruck: Er ist ein IMPULS, den die Regelschleife genau einmal sieht (`status()["on"]`,
danach `consume()`, wie bei den eigenen Knoepfen in virtual.py) - so loest jeder Druck genau einen Ablauf aus, auch bei schnell aufeinanderfolgenden
Druecken. Die Regelschleife wird sofort geweckt. Fuer die Anzeige (Liste, Dashboard) gilt ein Druck DISPLAY_S Sekunden als "gedrueckt" (`status()["shown"]`).

Ein Druck, der zwischen zwei Verbindungen passiert (Geraet war offline), geht verloren: beim Verbinden gilt der Anfangszustand nie als Druck.

Neu geflasht (1.30.2): Aendert eine neue Firmware den Namen eines Eintrags (z. B. "Taster" -> "Taster01 Taster"), meldet das Geraet den alten nicht mehr,
und der angelegte Eintrag bliebe stumm. BlueNexus merkt, was das Geraet seit dem Verbinden gemeldet hat (`missing()`), zeigt "Eingang fehlt am Geraet"
und ordnet den Eintrag einem eindeutig passenden neuen zu (`match_stale()`, `heal()`), ohne die Kennung zu aendern (Regeln, Verlauf, Freigaben bleiben).
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time

import requests

import idsafe

log = logging.getLogger("esphome")

DISPLAY_S = 3.0                  # so lange zeigt die Oberflaeche "gedrueckt" (die Regeln sehen den Druck als Impuls, unabhaengig davon)
PROBE_CONNECT_S = 8.0            # ein ESP8266 an schwachem WLAN nimmt Verbindungen manchmal erst nach einigen Sekunden an
PROBE_TRIES = 3                  # der Stick der Klimaanlage nimmt nur jede zweite/dritte Verbindung an: beim Suchen bis zu so viele Versuche
PROBE_QUIET_S = 3.0              # beim Suchen: so lange auf weitere Eintraege warten, nachdem nichts mehr kommt (der Stick schickt sie langsam)
PROBE_MAX_S = 14.0
STREAM_READ_S = 25.0             # das Geraet pingt alle 10 s; 25 s Stille = Verbindung tot (ein ESP8266 mit WLAN-Aussetzer schliesst sie oft nicht sauber; bis dahin gehen Druecke verloren)
BACKOFF_START_S = 1.0            # nach einem Abbruch schnell neu verbinden: bis dahin gehen Druecke verloren
BACKOFF_MAX_S = 30.0
SYNC_EVERY_S = 5.0
MISSING_GRACE_S = 10.0           # so lange nach dem Verbinden darf ein Eintrag noch fehlen (Anfangszustand kommt bei einem ESP8266 langsam)
SLOW_PRESS_S = 1.0               # dauert es von Druck bis fertiger Regelrunde laenger, steht das im Protokoll (sonst nur im Debug-Protokoll)
MAX_QUEUE = 5                    # so viele Druecke warten hoechstens darauf, von den Regeln gesehen zu werden (Schutz vor einem prellenden Taster)
DOMAINS = ("binary_sensor", "sensor", "climate", "switch")        # Eingaenge/Taster (Aktoren), Messwerte (Sensoren) und Klimaanlagen (Aktor, Art "esphome_ac")
VALUE_GRACE_S = 120.0            # ein Messwert gilt auch nach einem kurzen Verbindungsabbruch noch so lange (der ESP8266 verliert die Verbindung gelegentlich)


class EsphomeError(Exception):
    pass


def _url(ip: str, path: str) -> str:
    return f"http://{ip}{path}"


def split_id(ent) -> tuple:
    """(Art, Name) aus der Kennung, die das Geraet meldet. Aeltere ESPHome-Staende: "binary_sensor/Taster"; neuere: "binary_sensor-taster" (Bindestrich, Objektname)."""
    e = str(ent or "")
    if "/" in e:
        a, b = e.split("/", 1)
        return a, b
    if "-" in e:
        a, b = e.split("-", 1)
        return a, b
    return e, e


def _lines(r):
    """Zeilen eines Stroms als Text. Manche Geraete schicken die Einheit als Einzelbyte (° als 0xB0, kein gueltiges UTF-8): dann gilt Windows-1252."""
    for raw in r.iter_lines(chunk_size=1):
        if isinstance(raw, bytes):
            try:
                yield raw.decode("utf-8")
            except UnicodeDecodeError:
                yield raw.decode("cp1252", "replace")
        else:
            yield raw


# ---------------------------------------------------------------- Suchen
def _parse_sse(lines):
    """Erzeugt (event, daten-text) aus den Zeilen eines SSE-Stroms."""
    event, data = "message", []
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data:
                yield event, "\n".join(data)
                event, data = "message", []
            # eine Leerzeile ohne Daten (neuere ESPHome-Staende setzen sie zwischen "event:" und "data:") behaelt den Ereignisnamen
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        # "id:" und "retry:" sowie Kommentare sind hier nicht noetig


def _num(v):
    """Zahl oder None (ESPHome meldet einen fehlenden Messwert als null oder "NaN")."""
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


# ESPHome-Einheit -> (Art, Einheit in BlueNexus, Umrechnung) fuer die Sensorarten, die BlueNexus kennt (homematic.SENSOR_KINDS). Alles andere wird (noch) nicht angeboten.
def sensor_kind(uom: str, name: str):
    u, n = (uom or "").strip().replace("�", "°"), (name or "").lower()          # manche Geraete schicken das Gradzeichen schon als Ersatzzeichen
    if u in ("°C", "ºC", "C"):
        return "temperature", "°C", None
    if u in ("°F", "ºF", "F"):
        return "temperature", "°C", "f2c"
    if u == "%" and ("humid" in n or "feucht" in n):                 # "%" allein kann auch Akku oder Bodenfeuchte sein: nur mit passendem Namen
        return "humidity", "%", None
    if u == "W":
        return "power", "W", None
    if u == "kW":
        return "power", "W", "k"
    if u in ("hPa", "mbar"):
        return "pressure", "hPa", None
    if u == "kPa":
        return "pressure", "hPa", "x10"
    if u == "Pa":
        return "pressure", "hPa", "x0.01"
    if u in ("lx", "lux"):
        return "brightness", "lx", None
    if u == "V":
        return "voltage", "V", None
    if u in ("dBm", "dB"):
        return "signal", "dBm", None
    return None


_CONV = {"f2c": lambda v: (v - 32.0) / 1.8, "k": lambda v: v * 1000.0, "x10": lambda v: v * 10.0, "x0.01": lambda v: v * 0.01}


def sensor_id(title: str, entity: str) -> str:
    """Kennung im Sensorregister: espS-<geraetename>-<eintrag>."""
    return "espS-" + entity_id(title, entity)[len("esphome-"):]


def entity_id(title: str, entity: str) -> str:
    """Kennung im Geraeteregister: esphome-<geraetename>-<eintrag>, z. B. esphome-taster-taster."""
    name = split_id(entity)[1]
    return "esphome-" + idsafe.safe_id(title.lower().replace(" ", "_")) + "-" + idsafe.safe_id(name.lower().replace(" ", "_"))


def probe(ip: str) -> dict:
    """Liest den Anfangszustand eines ESPHome-Geraets: {"title", "entities": [{entity, name, domain, value}]}. Wirft EsphomeError.
    Ein ueberlastetes Geraet (ESP8266) nimmt nicht jede Verbindung an: bis zu PROBE_TRIES Versuche."""
    err = None
    for attempt in range(PROBE_TRIES):
        try:
            return _probe_once(ip)
        except EsphomeError as e:
            err = e
            time.sleep(0.5)
    raise err


def _probe_once(ip: str) -> dict:
    title, ents = None, {}
    start = time.time()
    try:
        with requests.get(_url(ip, "/events"), stream=True, timeout=(PROBE_CONNECT_S, PROBE_QUIET_S)) as r:
            r.raise_for_status()
            try:
                for event, data in _parse_sse(_lines(r)):
                    try:
                        j = json.loads(data)
                    except ValueError:
                        continue
                    if event == "ping" and isinstance(j, dict) and j.get("title") is not None:
                        title = str(j["title"])
                    elif event == "state" and isinstance(j, dict) and j.get("id") and (j.get("domain") or split_id(j["id"])[0]) in DOMAINS:
                        dom = str(j.get("domain") or split_id(j["id"])[0])
                        ents[str(j["id"])] = {"entity": str(j["id"]), "name": str(j.get("name") or split_id(j["id"])[1]), "domain": dom,
                                              "value": bool(j.get("value")) if dom == "binary_sensor" else _num(j.get("value")), "uom": str(j.get("uom") or "")}
                    if time.time() - start > PROBE_MAX_S:
                        break
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError, requests.exceptions.ChunkedEncodingError):
                pass                                                    # Stille = alle Anfangswerte sind da
    except requests.RequestException:
        raise EsphomeError("Unter dieser Adresse antwortet kein ESPHome-Gerät mit Weboberfläche (web_server)")
    if title is None and not ents:
        raise EsphomeError("Unter dieser Adresse antwortet kein ESPHome-Gerät mit Weboberfläche (web_server)")
    return {"title": title or "esphome", "entities": sorted(ents.values(), key=lambda e: e["name"].lower())}


# ---------------------------------------------------------------- Zustand und Verbindungen
_lock = threading.RLock()
_hosts: dict[str, dict] = {}                         # ip -> {"online", "stop" (Event), "thread"}
_state: dict[tuple, dict] = {}                       # (ip, entity) -> {"value": bool|None, "pressed_at": float, "seq": Zaehler der Druecke, "consumed": von den Regeln gesehen}
_wanted: dict[str, set] = {}                         # ip -> Eingaenge, die im Geraeteregister stehen (nur deren Druecke zaehlen und wecken die Regeln)
_seen: dict[str, dict] = {}                          # ip -> {Eintrag: Anzeigename}: alles, was das Geraet seit dem Verbinden gemeldet hat
_conn_at: dict[str, float] = {}                      # ip -> Zeit der letzten erfolgreichen Verbindung
_values: dict[tuple, tuple] = {}                     # (ip, entity) -> (Zeit, Messwert|None) der angelegten Sensoren
_climate: dict[tuple, tuple] = {}                    # (ip, entity) -> (Zeit, zuletzt gemeldete Felder der Klimaanlage)
_switch: dict[tuple, tuple] = {}                     # (ip, entity) -> (Zeit, an?) der Schalter/Relais (Aktor, Art "esphome_sw")
_sens_all: dict[tuple, float] = {}                   # (ip, entity) -> letzter Messwert, auch von nicht angelegten Sensoren (z. B. Aussentemperatur der Klimaanlage)
_pre: dict[tuple, dict] = {}                         # (ip, entity) -> Vorwahl bei ausgeschalteter Anlage {mode,target,fan,swing,eco} (BlueNexus-Begriffe); geht erst beim Einschalten an die Anlage
_last_mode: dict[tuple, str] = {}                    # (ip, entity) -> zuletzt benutzter Modus ausser OFF (fuer "einschalten" ohne Modus)
_listeners: list = []
_stop_all = threading.Event()
_sup: threading.Thread | None = None


def add_listener(fn) -> None:
    """fn() wird bei jedem Tastendruck aufgerufen (weckt die Regelschleife)."""
    with _lock:
        if fn not in _listeners:
            _listeners.append(fn)


def _notify() -> None:
    for fn in list(_listeners):
        try:
            fn()
        except Exception:                                                   # noqa: BLE001
            log.warning("ESPHome-Listener fehlgeschlagen", exc_info=True)


_link: dict[str, dict] = {}                          # ip -> Messung der Verbindung seit dem Start: {since, drops, down_s, longest_s, down_at, last_drop, last_reason}
_last_err: dict[str, str] = {}                       # ip -> Grund des letzten Abbruchs (Fehlerart)


def _note_link(ip: str, was_online: bool, online: bool) -> None:
    """Fuehrt Buch ueber die Verbindung zu einem Geraet (Abbrueche, Ausfallzeit); der Aufrufer haelt _lock."""
    now = time.time()
    m = _link.setdefault(ip, {"since": now, "drops": 0, "down_s": 0.0, "longest_s": 0.0, "down_at": None, "last_drop": None, "last_reason": "", "restarts": 0, "uptime": None, "last_restart": None})
    if was_online and not online:
        m["drops"] += 1
        m["down_at"] = now
        m["last_drop"] = now
        m["last_reason"] = _last_err.get(ip, "")
        log.info("ESPHome %s: Verbindung abgebrochen (%s), bisher %d Abbrüche", ip, m["last_reason"] or "ohne Fehler", m["drops"])
    elif online and m["down_at"]:
        d = now - m["down_at"]
        m["down_s"] += d
        m["longest_s"] = max(m["longest_s"], d)
        m["down_at"] = None
        log.info("ESPHome %s: wieder verbunden nach %.1f s", ip, d)


def _note_uptime(ip: str, up) -> None:
    """Betriebszeit aus den Ping-Meldungen des Geraets: faellt sie zurueck, hat sich der Chip neu gestartet (Absturz, Stromausfall, Update)."""
    try:
        up = float(up)
    except (TypeError, ValueError):
        return
    with _lock:
        m = _link.setdefault(ip, {"since": time.time(), "drops": 0, "down_s": 0.0, "longest_s": 0.0, "down_at": None, "last_drop": None, "last_reason": "",
                                  "restarts": 0, "uptime": None, "last_restart": None})
        prev = m.get("uptime")
        m["uptime"] = up
        if prev is not None and up + 5 < prev:
            m["restarts"] += 1
            m["last_restart"] = time.time()
            log.info("ESPHome %s: Gerät hat neu gestartet (Betriebszeit %.0f s statt zuletzt %.0f s), bisher %d Neustarts", ip, up, prev, m["restarts"])


def link_stats(ip: str) -> dict | None:
    """Messung der Verbindung seit dem Start von BlueNexus: Abbrueche, gesamte Ausfallzeit, laengster Ausfall, letzter Abbruch (None, wenn noch nichts gemessen)."""
    with _lock:
        m = _link.get(ip)
        if not m:
            return None
        now = time.time()
        cur = (now - m["down_at"]) if m["down_at"] else 0.0
        return {"drops": m["drops"], "down_s": round(m["down_s"] + cur, 1), "longest_s": round(max(m["longest_s"], cur), 1), "since_s": int(now - m["since"]),
                "last_drop_ago_s": None if m["last_drop"] is None else int(now - m["last_drop"]), "last_reason": m["last_reason"], "down_now": bool(m["down_at"]),
                "restarts": m.get("restarts", 0), "last_restart_ago_s": None if not m.get("last_restart") else int(now - m["last_restart"]),
                "uptime_s": None if m.get("uptime") is None else int(m["uptime"])}


def _set_online(ip: str, online: bool, stop=None) -> None:
    with _lock:
        h = _hosts.get(ip)
        if stop is not None and (h is None or h["stop"] is not stop):       # eine abgeloeste (neu gestartete) Verbindung darf den Zustand der neuen nicht stoeren
            return
        if h is not None:
            _note_link(ip, bool(h["online"]), online)
            h["online"] = online
        if online:                                                          # frische Verbindung: Anfangszustand zaehlt nie als Druck
            for k, st in _state.items():
                if k[0] == ip:
                    st["value"] = None
            _seen[ip] = {}                                                  # was das Geraet jetzt meldet, wird neu gesammelt (nach einem Neuflashen ggf. andere Namen)
            _conn_at[ip] = time.time()


def _on_state(ip: str, j: dict) -> None:
    ent = str(j.get("id") or "")
    dom = str(j.get("domain") or split_id(ent)[0])                 # Aenderungsmeldungen tragen kein "domain", nur "id", "value", "state" - die Art steht im Praefix der Kennung
    if not ent or dom not in DOMAINS:
        return
    with _lock:
        seen = _seen.setdefault(ip, {})
        seen[ent] = str(j.get("name") or seen.get(ent) or split_id(ent)[1])      # Aenderungsmeldungen tragen keinen Namen: der aus dem Anfangszustand bleibt
    if dom == "climate":                                               # Klimaanlage: Felder zusammenfuehren (Aenderungsmeldungen koennen nur einen Teil enthalten)
        with _lock:
            old = _climate.get((ip, ent), (0.0, {}))[1]
            new = {**old, **{k: v for k, v in j.items() if k not in ("id", "domain", "name", "icon", "entity_category")}}
            _climate[(ip, ent)] = (time.time(), new)
            m = str(new.get("mode") or "").upper()
            if m and m != "OFF":
                _last_mode[(ip, ent)] = m
                _pre.pop((ip, ent), None)                                  # Anlage laeuft (auch per Fernbedienung eingeschaltet): die Vorwahl ist erledigt
        _notify()
        return
    if dom == "switch":                                                # Schalter/Relais: Zustand merken (kommt beim Verbinden und bei jeder Aenderung, auch am Geraet selbst)
        with _lock:
            _switch[(ip, ent)] = (time.time(), bool(j.get("value")))
        _notify()
        return
    if dom == "sensor":                                                # Messwert: nur merken, wenn ein Sensor ihn braucht
        with _lock:
            _sens_all[(ip, ent)] = _num(j.get("value"))
        with _lock:
            if ent in _wanted.get(ip, ()):
                _values[(ip, ent)] = (time.time(), _num(j.get("value")))
        return
    val = bool(j.get("value"))
    pressed = False
    with _lock:
        st = _state.setdefault((ip, ent), {"value": None, "pressed_at": 0.0, "seq": 0, "consumed": 0, "saw_on": False, "mask": False, "pass_on": False, "stamps": [], "round_mono": 0.0})
        if val and st["value"] is False and ent in _wanted.get(ip, ()):
            st["pressed_at"] = time.time()
            if st["seq"] - st["consumed"] < MAX_QUEUE:
                st["seq"] += 1
                st["stamps"].append(time.monotonic())                      # fuer die Zeitmessung Druck -> Regelrunde
            pressed = True
        st["value"] = val
    if pressed:
        _notify()


def simulate_press(d: dict) -> bool:
    """Loest einen Tastendruck in BlueNexus aus, als haette jemand den Taster am Geraet gedrueckt (Test-Knopf in der Aktorenliste): Regeln, die auf
    den Taster reagieren, laufen los. Am Geraet selbst wird nichts gesendet. False, wenn das Geraet gerade nicht verbunden ist."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)
    ensure(ip)
    with _lock:
        h = _hosts.get(ip)
        if not (h and h["online"]):
            return False
        st = _state.setdefault((ip, ent), {"value": None, "pressed_at": 0.0, "seq": 0, "consumed": 0, "saw_on": False, "mask": False, "pass_on": False, "stamps": [], "round_mono": 0.0})
        st["pressed_at"] = time.time()
        if st["seq"] - st["consumed"] < MAX_QUEUE:
            st["seq"] += 1
            st["stamps"].append(time.monotonic())
    _notify()
    return True


def _watch(ip: str, stop: threading.Event) -> None:
    backoff = BACKOFF_START_S
    while not stop.is_set() and not _stop_all.is_set():
        try:
            with requests.get(_url(ip, "/events"), stream=True, timeout=(PROBE_CONNECT_S, STREAM_READ_S)) as r:
                r.raise_for_status()
                _set_online(ip, True, stop)
                backoff = BACKOFF_START_S
                for event, data in _parse_sse(_lines(r)):
                    if stop.is_set() or _stop_all.is_set():
                        break
                    if event == "ping":                                    # enthaelt (je nach Stand) die Betriebszeit des Geraets
                        try:
                            pj = json.loads(data)
                        except ValueError:
                            pj = None
                        if isinstance(pj, dict) and "uptime" in pj:
                            _note_uptime(ip, pj["uptime"])
                        continue
                    if event == "state":
                        try:
                            j = json.loads(data)
                        except ValueError:
                            continue
                        if isinstance(j, dict):
                            _on_state(ip, j)
        except (requests.RequestException, OSError, ValueError) as e:
            log.debug("ESPHome %s: Verbindung beendet (%s: %s)", ip, e.__class__.__name__, e)
            _last_err[ip] = {"ReadTimeout": "Stille (25 s ohne Meldung)", "ConnectTimeout": "keine Antwort beim Verbinden", "ConnectionError": "Verbindung getrennt oder abgelehnt",
                             "ChunkedEncodingError": "Verbindung getrennt"}.get(e.__class__.__name__, e.__class__.__name__)
        else:
            _last_err[ip] = "vom Gerät beendet"
        _set_online(ip, False, stop)
        stop.wait(backoff)
        backoff = min(BACKOFF_MAX_S, backoff * 2)


def ensure(ip: str) -> None:
    """Sorgt dafuer, dass fuer diese Adresse eine Verbindung gehalten wird."""
    with _lock:
        h = _hosts.get(ip)
        if h and h["thread"].is_alive():
            return
        stop = threading.Event()
        t = threading.Thread(target=_watch, args=(ip, stop), name="esphome-" + ip, daemon=True)
        _hosts[ip] = {"online": False, "stop": stop, "thread": t}
        t.start()


def _restart(ip: str) -> None:
    """Verbindung neu aufbauen: der Anfangszustand aller Eintraege kommt nur beim Verbinden - ein Eintrag, der nach dem Verbinden angelegt wurde, braucht ihn."""
    with _lock:
        h = _hosts.pop(ip, None)
    if h:
        h["stop"].set()
    ensure(ip)


def _want(ip: str, ent: str) -> None:
    with _lock:
        known = _wanted.setdefault(ip, set())
        new = ent not in known
        known.add(ent)
        live = ip in _hosts
    if new and live:
        _restart(ip)


def release(ip: str) -> None:
    with _lock:
        h = _hosts.pop(ip, None)
        for k in [k for k in _state if k[0] == ip]:
            _state.pop(k, None)
        _wanted.pop(ip, None)
        _seen.pop(ip, None)
        _conn_at.pop(ip, None)
        for k in [k for k in _values if k[0] == ip]:
            _values.pop(k, None)
        for dct in (_climate, _switch, _sens_all, _last_mode, _pre):
            for k in [k for k in dct if k[0] == ip]:
                dct.pop(k, None)
    if h:
        h["stop"].set()


def sync(devices: list[dict]) -> None:
    """Verbindungen an das Geraeteregister angleichen: neue Adressen verbinden, nicht mehr benoetigte trennen."""
    want, restart = set(), []
    with _lock:
        old = {ip: set(v) for ip, v in _wanted.items()}
        _wanted.clear()
        for d in devices:
            if d.get("kind") in ("esphome", "esphome_ac", "esphome_sw") and d.get("ip") and d.get("entity"):               # Taster, Klimaanlagen und Schalter (Geraeteregister)
                ip, ent = str(d["ip"]), str(d["entity"])
            elif d.get("source") == "esphome" and d.get("ip") and d.get("datapoint"):        # Messwert (Sensorregister)
                ip, ent = str(d["ip"]), str(d["datapoint"])
            else:
                continue
            want.add(ip)
            _wanted.setdefault(ip, set()).add(ent)
        restart = [ip for ip, ents in _wanted.items() if ip in _hosts and ents - old.get(ip, set())]
    for ip in restart:
        _restart(ip)
    for ip in want:
        ensure(ip)
    with _lock:
        gone = [ip for ip in _hosts if ip not in want]
    for ip in gone:
        release(ip)


def entries() -> list[dict]:
    """Alle Eintraege, die ein ESPHome-Geraet brauchen: Taster (Geraeteregister) und Messwerte (Sensorregister)."""
    import homematic
    import shelly
    return shelly.load_devices() + [s for s in homematic.load_sensors() if s.get("source") == "esphome"]


def resync() -> None:
    sync(entries())


def start(wake_cb, enabled_cb=None, load_entries=None) -> None:
    """Hintergrund: haelt die Verbindungen zu allen ESPHome-Geraeten der Register. wake_cb(): Regelschleife wecken."""
    global _sup
    add_listener(wake_cb)
    if _sup and _sup.is_alive():
        return
    _stop_all.clear()
    enabled = enabled_cb or (lambda: True)

    def loop():
        while not _stop_all.is_set():
            try:
                if enabled():
                    sync((load_entries or entries)())
                    heal()
                else:
                    sync([])
            except Exception:                                               # noqa: BLE001
                log.warning("ESPHome-Abgleich fehlgeschlagen", exc_info=True)
            _stop_all.wait(SYNC_EVERY_S)
    _sup = threading.Thread(target=loop, name="esphome-sync", daemon=True)
    _sup.start()


def stop() -> None:
    _stop_all.set()
    with _lock:
        for h in _hosts.values():
            h["stop"].set()
        _hosts.clear()


def missing(ip: str, ent: str) -> bool:
    """Das Geraet ist verbunden, hat seinen Anfangszustand laengst geschickt, aber diesen Eintrag nicht gemeldet (z. B. nach einem Firmware-Wechsel umbenannt)."""
    with _lock:
        h = _hosts.get(ip)
        if not (h and h["online"]):
            return False
        if time.time() - _conn_at.get(ip, 0.0) < MISSING_GRACE_S:
            return False
        return ent not in _seen.get(ip, {})


def _norm(s) -> str:
    return "".join(ch for ch in str(s or "").casefold() if ch.isalnum())


def match_stale(stale: list, cands: list, fallback: bool = False) -> list:
    """Ordnet Eintraege, die das Geraet nicht mehr meldet (stale: [{id, entity, name}]), neuen Eintraegen des Geraets (cands: [{entity, name}]) zu.
    Nur eindeutige Paare: gleicher Name (nach Grossschreibung/Sonderzeichen) = starker Treffer, ein Name steckt im anderen (mind. 4 Zeichen,
    z. B. "Taster" -> "Taster01 Taster") = schwacher Treffer; gibt es mehrere Kandidaten, wird nichts zugeordnet. fallback=True: bleibt am Ende genau ein
    Eintrag und genau ein Kandidat uebrig, gehoeren sie zusammen (nur, wenn der Nutzer den Kandidaten gerade selbst hinzufuegt)."""
    def keys(x):
        return {k for k in (_norm(split_id(x.get("entity"))[1]), _norm(x.get("name"))) if k}

    def likes(a, b):
        ka, kb = keys(a), keys(b)
        if ka & kb:
            return 2
        for x in ka:
            for y in kb:
                if len(x) >= 4 and len(y) >= 4 and (x in y or y in x):
                    return 1
        return 0
    pairs, used_s, used_c = [], set(), set()
    for score in (2, 1):
        for i, s in enumerate(stale):
            if i in used_s:
                continue
            ms = [j for j, c in enumerate(cands) if j not in used_c and likes(s, c) == score]
            if len(ms) != 1:
                continue
            j = ms[0]
            if len([k for k, s2 in enumerate(stale) if k not in used_s and likes(s2, cands[j]) >= score]) != 1:
                continue
            pairs.append((s, cands[j])); used_s.add(i); used_c.add(j)
    rest_s = [s for i, s in enumerate(stale) if i not in used_s]
    rest_c = [c for j, c in enumerate(cands) if j not in used_c]
    if fallback and len(rest_s) == 1 and len(rest_c) == 1:
        pairs.append((rest_s[0], rest_c[0]))
    return pairs


def heal() -> int:
    """Hintergrund (alle paar Sekunden): Eintraege, die ein verbundenes Geraet nicht mehr meldet, werden einem eindeutig passenden neuen Eintrag desselben
    Geraets zugeordnet (starker/schwacher Namens-Treffer, nie geraten). Gibt die Zahl der neu zugeordneten Eintraege zurueck."""
    import shelly
    with _lock:
        now = time.time()
        todo = {}
        for ip, h in _hosts.items():
            if not h["online"] or now - _conn_at.get(ip, now) < MISSING_GRACE_S:
                continue
            seen = _seen.get(ip, {})
            if any(e not in seen for e in _wanted.get(ip, ())):
                todo[ip] = dict(seen)
    n = 0
    for ip, seen in todo.items():
        ents = [{"entity": e, "name": nm, "domain": split_id(e)[0]} for e, nm in seen.items()]
        n += len(shelly.esphome_relink(ip, ents))
    if n:
        resync()
    return n


def _log_timing(k: tuple, st: dict, done: int) -> None:
    """Eine Regelrunde hat `done` Druecke abgearbeitet: Zeit von Druck bis Rundenbeginn und bis Rundenende ins Protokoll (nur lange Zeiten als Info)."""
    now = time.monotonic()
    for _ in range(done):
        if not st["stamps"]:
            return
        t0 = st["stamps"].pop(0)
        total = now - t0
        began = (st["round_mono"] - t0) if st["round_mono"] >= t0 else 0.0
        (log.info if total >= SLOW_PRESS_S else log.debug)("ESPHome %s %s: Druck bis Regelrunde %.2f s, bis Runde fertig %.2f s", k[0], k[1], began, total)


def read_value(sen: dict):
    """Aktueller Wert eines Messwert-Sensors (Zahl in der Einheit des Sensors) oder None (Geraet nicht erreichbar / noch kein Wert)."""
    ip, ent = str(sen.get("ip") or ""), str(sen.get("datapoint") or "")
    _want(ip, ent)
    ensure(ip)
    with _lock:
        h = _hosts.get(ip)
        online = bool(h and h["online"])
        ts, v = _values.get((ip, ent), (0.0, None))
    if v is None or not (online or time.time() - ts < VALUE_GRACE_S):
        return None
    conv = _CONV.get(sen.get("conv") or "")
    return conv(v) if conv else v


def seqs() -> dict:
    """Beginn einer Regelrunde: Zaehlerstand aller Taster merken; am Ende der Runde consume() damit aufrufen (ein Druck waehrend der Runde bleibt fuer die
    naechste erhalten). Hat die vorige Runde den Taster schon als "an" gesehen und wartet schon der naechste Druck, zeigt DIESE Runde einmal "aus" (Luecke):
    Regeln erkennen einen neuen Druck nur am Wechsel von aus nach an - ohne Luecke gingen schnell aufeinanderfolgende Druecke verloren."""
    with _lock:
        snap = {}
        for k, st in _state.items():
            pending = st["seq"] > st["consumed"]
            st["mask"] = pending and st["saw_on"]
            st["pass_on"] = pending and not st["mask"]
            if pending:
                st["round_mono"] = time.monotonic()
            snap[k] = st["consumed"] if (st["mask"] or not pending) else st["consumed"] + 1          # pro Runde genau ein Druck: jeder Druck ein eigener Ablauf
        return snap


def consume(snapshot: dict) -> None:
    """Die Regelschleife hat die Druecke bis zu diesem Stand gesehen - Impuls beenden. Wartet noch ein Druck, werden die Regeln gleich noch einmal geweckt."""
    again = False
    with _lock:
        for k, n in snapshot.items():
            st = _state.get(k)
            if st is None:
                continue
            if n > st["consumed"]:
                _log_timing(k, st, n - st["consumed"])
                st["consumed"] = n
            st["saw_on"], st["mask"], st["pass_on"] = st["pass_on"], False, False
            if st["seq"] > st["consumed"]:
                again = True
    if again:
        _notify()


def clear() -> None:
    """Alle wartenden Druecke verwerfen (Regeln sind aus: ein alter Druck darf spaeter nichts ausloesen)."""
    with _lock:
        for st in _state.values():
            st["consumed"], st["saw_on"], st["mask"], st["pass_on"] = st["seq"], False, False, False
            st["stamps"].clear()


def status(d: dict) -> dict:
    """{'online', 'on', 'power', 'shown'} (+ 'missing' = True, wenn das Geraet diesen Eingang nicht meldet). 'on' = ein Druck wartet darauf, von den Regeln gesehen zu werden (Impuls; Geraet offline: None);
    'shown' = der letzte Druck liegt hoechstens DISPLAY_S Sekunden zurueck (nur fuer die Anzeige)."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)                                          # auch ohne vorherigen Abgleich (z. B. gerade angelegt) zaehlt dieser Eingang
    ensure(ip)
    with _lock:
        h = _hosts.get(ip)
        online = bool(h and h["online"])
        st = _state.get((ip, ent)) or {}
        pa, pending = st.get("pressed_at", 0.0), st.get("seq", 0) > st.get("consumed", 0) and not st.get("mask")
    link = link_stats(ip)
    if not online:
        return {"online": False, "on": None, "power": None, "shown": False, "link": link}
    out = {"online": True, "on": pending, "power": None, "shown": (time.time() - pa) < DISPLAY_S, "link": link}
    if missing(ip, ent):
        out["missing"] = True                               # das Geraet meldet diesen Eingang nicht mehr (neue Firmware?) - der Eintrag bliebe sonst stumm
    return out


# ---------------------------------------------------------------- Klimaanlage (Aktor, Art "esphome_ac"): ESPHome-Entitaet "climate"
# Begriffe wie bei der Midea-Anbindung (midea.py), damit Kachel, Regeln, Automatik und Klimafenster ohne Umbau funktionieren.
CLIMATE_MODES = {"HEAT_COOL": "auto", "COOL": "cool", "HEAT": "heat", "FAN_ONLY": "fan_only", "DRY": "dry"}
CLIMATE_FANS = {"AUTO": "auto", "LOW": "low", "MEDIUM": "medium", "HIGH": "high"}
CLIMATE_CUSTOM_FANS = {"silent": "silent", "turbo": "max"}
CLIMATE_SWINGS = {"OFF": "off", "BOTH": "both", "VERTICAL": "vertical", "HORIZONTAL": "horizontal"}
SET_WAIT_S = 4.0                                     # so lange auf die Rueckmeldung des Geraets nach einem Befehl warten
CLIMATE_TRIES = 3                                    # der Stick schliesst bei Last manchmal ohne Antwort: bis zu so viele Versuche
CLIMATE_CHECK_S = 2.5                                # nach einem Abbruch so lange auf die Meldung warten, ob der Befehl doch angekommen ist
CLIMATE_RETRY_S = 1.0


def _rev(table: dict, key):
    return next((k for k, v in table.items() if v == key), None)


def _climate_fields(ip: str, ent: str):
    with _lock:
        h = _hosts.get(ip)
        online = bool(h and h["online"])
        ts, c = _climate.get((ip, ent), (0.0, {}))
    return online, ts, dict(c)


def climate_status(d: dict) -> dict:
    """Zustand der Klimaanlage im Format der Midea-Anbindung: online, on, mode, target_c, indoor_c, outdoor_c, fan, swing, info."""
    import midea
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)
    ensure(ip)
    online, ts, c = _climate_fields(ip, ent)
    if online and missing(ip, ent):                         # das Geraet meldet diese Klima-Entitaet nicht mehr (neue Firmware?): BlueNexus ordnet sie selbst neu zu, bis dahin nicht anzeigen
        return {"online": True, "on": None, "power": None, "missing": True, "info": "Klima fehlt am Gerät – neu suchen oder löschen"}
    if not c or not (online or time.time() - ts < VALUE_GRACE_S):
        return {"online": False, "on": None, "power": None}
    mode = str(c.get("mode") or "OFF").upper()
    on = mode != "OFF"
    with _lock:
        shown = mode if on else _last_mode.get((ip, ent), "COOL")
        out = next((v for (i, e), v in _sens_all.items() if i == ip and "outdoor" in e.lower() and v is not None), None)
    fan = CLIMATE_CUSTOM_FANS.get(str(c.get("custom_fan_mode") or "").lower()) or CLIMATE_FANS.get(str(c.get("fan_mode") or "").upper())
    snap = {"online": True, "on": on, "mode": CLIMATE_MODES.get(shown, "auto"), "target_c": _num(c.get("target_temperature")), "indoor_c": _num(c.get("current_temperature")),
            "outdoor_c": out, "fan": fan, "swing": CLIMATE_SWINGS.get(str(c.get("swing_mode") or "").upper(), "off"), "eco": str(c.get("preset") or "").upper() == "ECO"}
    with _lock:
        pre = dict(_pre.get((ip, ent)) or {}) if not on else {}
    for k_pre, k_snap in (("mode", "mode"), ("target", "target_c"), ("fan", "fan"), ("swing", "swing"), ("eco", "eco")):       # bei ausgeschalteter Anlage zeigt BlueNexus, was beim Einschalten gelten wird
        if k_pre in pre:
            snap[k_snap] = pre[k_pre]
    return {**snap, "power": None, "info": midea.info_text(snap)}


def climate_details(d: dict) -> dict:
    """Auswahl fuer das Klimafenster (Modi, Luefter, Schwenken, Temperaturbereich) aus dem, was das Geraet selbst meldet."""
    import midea
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    st = climate_status(d)
    if not st.get("online"):
        raise EsphomeError("Die Klimaanlage antwortet nicht (WLAN/Strom prüfen)")
    online, ts, c = _climate_fields(ip, ent)
    lab = lambda table, labels, keys: [{"key": table[k], "label": labels.get(table[k], table[k])} for k in keys if k in table]
    fans = lab(CLIMATE_FANS, midea.FAN_LABELS, [str(x).upper() for x in c.get("fan_modes") or []])
    # Die Sonderstufen "silent"/"turbo" meldet die ESPHome-Midea-Komponente immer, auch wenn die Anlage sie nicht kann -> nicht anbieten
    # (gesetzt werden koennen sie weiter, z. B. aus einer alten Regel; Anzeige bleibt dann "Flüster"/"maximal").
    return {"state": st, "min": _num(c.get("min_temp")) or 16.0, "max": _num(c.get("max_temp")) or 30.0, "step": _num(c.get("step")) or 0.5,
            "modes": lab(CLIMATE_MODES, midea.MODE_LABELS, [str(x).upper() for x in c.get("modes") or []]), "fans": fans,
            "swings": lab(CLIMATE_SWINGS, midea.SWING_LABELS, [str(x).upper() for x in c.get("swing_modes") or []]),
            "supports_eco": "ECO" in [str(x).upper() for x in c.get("presets") or []]}


def _climate_query(c: dict, given: dict) -> dict:
    """Parameter fuer POST /climate/<name>/set aus BlueNexus-Werten ({mode, target, fan, swing, eco}); wirft EsphomeError bei ungueltigen Werten."""
    q = {}
    if given.get("mode") is not None:
        m = _rev(CLIMATE_MODES, given["mode"])
        if m is None:
            raise EsphomeError(f"Unbekannter Modus: {given['mode']}")
        q["mode"] = m
    if given.get("target") is not None:
        lo, hi = _num(c.get("min_temp")) or 16.0, _num(c.get("max_temp")) or 30.0
        t = _num(given["target"])
        if t is None or not lo <= t <= hi:
            raise EsphomeError(f"Solltemperatur zwischen {lo:g} und {hi:g} °C wählen")
        q["target_temperature"] = f"{t:g}"
    if given.get("fan") is not None:
        f = _rev(CLIMATE_FANS, given["fan"])
        cf = _rev(CLIMATE_CUSTOM_FANS, given["fan"])
        if f:
            q["fan_mode"] = f
        elif cf:
            q["custom_fan_mode"] = next((x for x in c.get("custom_fan_modes") or [] if str(x).lower() == cf), cf)          # Schreibweise des Geraets (Silent/Turbo oder silent/turbo)
        else:
            raise EsphomeError(f"Unbekannte Lüfterstufe: {given['fan']}")
    if given.get("swing") is not None:
        sw = _rev(CLIMATE_SWINGS, given["swing"])
        if not sw:
            raise EsphomeError(f"Unbekannte Schwenkart: {given['swing']}")
        q["swing_mode"] = sw
    if given.get("eco") is not None:
        q["preset"] = "ECO" if given["eco"] else "NONE"
    return q


def climate_set(d: dict, power=None, mode=None, target=None, fan=None, swing=None, eco=None) -> dict:
    """Setzt nur die genannten Werte (Ein/Aus, Modus, Solltemperatur, Luefter, Schwenken, Eco) per POST /climate/<name>/set. Rueckgabe: neuer Zustand."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)
    ensure(ip)
    online, ts, c = _climate_fields(ip, ent)
    if not online or not c:
        raise EsphomeError("Die Klimaanlage antwortet nicht (WLAN/Strom prüfen)")
    if missing(ip, ent):
        raise EsphomeError("Das Gerät meldet diese Klimaanlage nicht mehr (neue Firmware?) – bitte „Taster, Klima & Schalter suchen“ noch einmal ausführen.")
    given = {k: v for k, v in (("mode", mode), ("target", target), ("fan", fan), ("swing", swing), ("eco", eco)) if v is not None}
    cur_off = str(c.get("mode") or "OFF").upper() == "OFF"
    q = _climate_query(c, given)                                    # prueft die Werte (wirft EsphomeError)
    if power is False:
        with _lock:
            _pre.pop((ip, ent), None)
        q = {"mode": "OFF"}
    elif cur_off and power is not True:
        # Bei ESPHome ist der Modus zugleich der Ein/Aus-Schalter: einen Modus waehlen heisst einschalten. Ist die Anlage aus, wird nur vorgemerkt
        # und erst beim Einschalten gemeinsam gesendet (wie bei den Midea-Anlagen, dort bleibt die Anlage beim Einstellen aus).
        if not given:
            raise EsphomeError("Nichts zu setzen")
        with _lock:
            _pre.setdefault((ip, ent), {}).update(given)
        log.info("ESPHome-Klima %s: Vorwahl %s gemerkt (Anlage ist aus)", ip, given)
        return climate_status(d)
    elif cur_off:                                                   # einschalten: Vorwahl und neue Angaben zusammen senden
        with _lock:
            pre = _pre.pop((ip, ent), {})
        q = _climate_query(c, {**pre, **given})
        if "mode" not in q:
            with _lock:
                q["mode"] = _last_mode.get((ip, ent)) or "HEAT_COOL"
    else:
        with _lock:
            _pre.pop((ip, ent), None)
        if not q and power is True:
            return climate_status(d)                                # laeuft schon
    if not q:
        raise EsphomeError("Nichts zu setzen")
    obj = split_id(ent)[1]
    want = {"mode": q.get("mode"), "target_temperature": q.get("target_temperature"), "fan_mode": q.get("fan_mode"), "swing_mode": q.get("swing_mode"), "preset": q.get("preset")}
    want = {k: v for k, v in want.items() if v is not None}

    def applied() -> bool:
        _o, ts2, c2 = _climate_fields(ip, ent)
        return ts2 > t0 and all(str(c2.get(k) or "").upper() == v.upper() or (_num(c2.get(k)) is not None and _num(c2.get(k)) == _num(v)) for k, v in want.items())

    def wait_applied(sek: float) -> bool:
        end = time.time() + sek
        while time.time() < end:
            if want and applied():
                return True
            time.sleep(0.15)
        return want != {} and applied()
    t0, err, ok = time.time(), None, False
    for attempt in range(1, CLIMATE_TRIES + 1):
        try:
            r = requests.post(_url(ip, "/climate/" + requests.utils.quote(obj, safe="") + "/set"), params=q, timeout=(PROBE_CONNECT_S, 8.0),
                              headers={"Connection": "close", "Accept-Encoding": "identity"})
            r.raise_for_status()
            ok = True
            break
        except requests.RequestException as e:                      # der Stick schliesst bei Last manchmal ohne Antwort - der Befehl kann trotzdem angekommen sein: Zustand pruefen
            err = e
            log.info("ESPHome-Klima %s: Versuch %d/%d ohne Antwort (%s)", ip, attempt, CLIMATE_TRIES, e.__class__.__name__)
            if wait_applied(CLIMATE_CHECK_S):
                ok = True
                break
            time.sleep(CLIMATE_RETRY_S)
    if not ok:
        log.warning("ESPHome-Klima %s: Befehl %s fehlgeschlagen: %s", ip, q, err)
        raise EsphomeError("Die Klimaanlage hat den Befehl nicht angenommen oder ist nicht erreichbar.")
    log.info("ESPHome-Klima %s: Befehl %s gesendet", ip, q)
    wait_applied(SET_WAIT_S)                                        # die neue Meldung des Geraets abwarten, damit die Anzeige gleich stimmt
    return climate_status(d)


# ---------------------------------------------------------------- Schalter / Relais (Aktor, Art "esphome_sw"): ESPHome-Entitaet "switch"
SWITCH_TRIES = 3
SWITCH_WAIT_S = 3.0                                  # so lange auf die Rueckmeldung des Geraets nach einem Befehl warten


def _switch_fields(ip: str, ent: str):
    with _lock:
        h = _hosts.get(ip)
        online = bool(h and h["online"])
        ts, on = _switch.get((ip, ent), (0.0, None))
    return online, ts, on


def switch_status(d: dict) -> dict:
    """Zustand eines Schalters/Relais: {'online', 'on', 'power'}. Der Zustand kommt aus der gehaltenen Verbindung; nach einem kurzen Abbruch gilt der letzte noch VALUE_GRACE_S."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)
    ensure(ip)
    online, ts, on = _switch_fields(ip, ent)
    link = link_stats(ip)
    if online and missing(ip, ent):
        return {"online": True, "on": None, "power": None, "missing": True, "link": link}
    if on is None or not (online or time.time() - ts < VALUE_GRACE_S):
        return {"online": False, "on": None, "power": None, "link": link}
    return {"online": True, "on": bool(on), "power": None, "link": link}


def switch_set(d: dict, on: bool) -> dict:
    """Schaltet das Relais per POST /switch/<name>/turn_on bzw. turn_off und wartet kurz auf die Rueckmeldung des Geraets. Rueckgabe: neuer Zustand."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    _want(ip, ent)
    ensure(ip)
    online, ts, cur = _switch_fields(ip, ent)
    if not online:
        raise EsphomeError("Das Gerät antwortet nicht (WLAN/Strom prüfen)")
    if missing(ip, ent):
        raise EsphomeError("Das Gerät meldet diesen Schalter nicht mehr (neue Firmware?) – bitte „Taster, Klima & Schalter suchen“ noch einmal ausführen.")
    obj = split_id(ent)[1]
    path = "/switch/" + requests.utils.quote(obj, safe="") + ("/turn_on" if on else "/turn_off")

    def applied() -> bool:
        return _switch_fields(ip, ent)[2] is bool(on)
    t0, err, ok = time.time(), None, False
    for attempt in range(1, SWITCH_TRIES + 1):
        try:
            r = requests.post(_url(ip, path), timeout=(PROBE_CONNECT_S, 8.0), headers={"Connection": "close", "Accept-Encoding": "identity"})
            r.raise_for_status()
            ok = True
            break
        except requests.RequestException as e:                      # das Geraet schliesst bei Last manchmal ohne Antwort - der Befehl kann trotzdem angekommen sein
            err = e
            log.info("ESPHome-Schalter %s: Versuch %d/%d ohne Antwort (%s)", ip, attempt, SWITCH_TRIES, e.__class__.__name__)
            end = time.time() + 1.5
            while time.time() < end and not applied():
                time.sleep(0.15)
            if applied():
                ok = True
                break
            time.sleep(0.5)
    if not ok:
        log.warning("ESPHome-Schalter %s: Befehl %s fehlgeschlagen: %s", ip, path, err)
        raise EsphomeError("Das Gerät hat den Befehl nicht angenommen oder ist nicht erreichbar.")
    end = time.time() + SWITCH_WAIT_S
    while time.time() < end and not applied():
        time.sleep(0.1)
    if not applied():                                               # keine Meldung abgewartet: den Befehl als neuen Zustand merken (die Verbindung korrigiert ihn, falls das Geraet anders entscheidet)
        with _lock:
            _switch[(ip, ent)] = (time.time(), bool(on))
    _notify()
    log.info("ESPHome-Schalter %s: %s -> %s", ip, ent, "an" if on else "aus")
    return switch_status(d)
