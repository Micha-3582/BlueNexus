"""
ESPHome-Geraete (Hardware-Taster und aehnliches) - LOKAL ueber die Weboberflaeche des Geraets (`web_server`, Port 80). Keine Zusatzpakete, nur `requests`.

Ein Eintrag im Geraeteregister (shelly.py, kind "esphome") = ein Eingang (`binary_sensor`) eines ESPHome-Geraets, z. B. ein Taster.
Die Weboberflaeche des Geraets liefert unter `GET /events` einen dauerhaften Strom (Server-Sent-Events): beim Verbinden den Zustand aller Eintraege
(`event: state`), danach jede Aenderung sofort, alle 30 Sekunden ein `event: ping`. Pro Geraet (IP-Adresse) haelt BlueNexus eine solche Verbindung
(Hintergrund-Thread, mit Wiederverbindung und wachsender Wartezeit). Springt ein Eingang von AUS auf AN, gilt das als Tastendruck: Er ist ein IMPULS, den die Regelschleife genau einmal sieht (`status()["on"]`,
danach `consume()`, wie bei den eigenen Knoepfen in virtual.py) - so loest jeder Druck genau einen Ablauf aus, auch bei schnell aufeinanderfolgenden
Druecken. Die Regelschleife wird sofort geweckt. Fuer die Anzeige (Liste, Dashboard) gilt ein Druck DISPLAY_S Sekunden als "gedrueckt" (`status()["shown"]`).

Ein Druck, der zwischen zwei Verbindungen passiert (Geraet war offline), geht verloren: beim Verbinden gilt der Anfangszustand nie als Druck.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import requests

import idsafe

log = logging.getLogger("esphome")

DISPLAY_S = 3.0                  # so lange zeigt die Oberflaeche "gedrueckt" (die Regeln sehen den Druck als Impuls, unabhaengig davon)
PROBE_CONNECT_S = 8.0            # ein ESP8266 an schwachem WLAN nimmt Verbindungen manchmal erst nach einigen Sekunden an
PROBE_QUIET_S = 1.5              # beim Suchen: so lange auf weitere Eintraege warten, nachdem nichts mehr kommt
PROBE_MAX_S = 6.0
STREAM_READ_S = 25.0             # das Geraet pingt alle 10 s; 25 s Stille = Verbindung tot (ein ESP8266 mit WLAN-Aussetzer schliesst sie oft nicht sauber; bis dahin gehen Druecke verloren)
BACKOFF_START_S = 1.0            # nach einem Abbruch schnell neu verbinden: bis dahin gehen Druecke verloren
BACKOFF_MAX_S = 30.0
SYNC_EVERY_S = 5.0
MAX_QUEUE = 5                    # so viele Druecke warten hoechstens darauf, von den Regeln gesehen zu werden (Schutz vor einem prellenden Taster)
DOMAINS = ("binary_sensor",)     # erste Stufe: Eingaenge/Taster


class EsphomeError(Exception):
    pass


def _url(ip: str, path: str) -> str:
    return f"http://{ip}{path}"


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
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
        # "id:" und "retry:" sowie Kommentare sind hier nicht noetig


def entity_id(title: str, entity: str) -> str:
    """Kennung im Geraeteregister: esphome-<geraetename>-<eintrag>, z. B. esphome-taster-taster."""
    name = entity.split("/", 1)[-1]
    return "esphome-" + idsafe.safe_id(title.lower().replace(" ", "_")) + "-" + idsafe.safe_id(name.lower().replace(" ", "_"))


def probe(ip: str) -> dict:
    """Liest den Anfangszustand eines ESPHome-Geraets: {"title", "entities": [{entity, name, domain, value}]}. Wirft EsphomeError."""
    title, ents = None, {}
    start = time.time()
    try:
        with requests.get(_url(ip, "/events"), stream=True, timeout=(PROBE_CONNECT_S, PROBE_QUIET_S)) as r:
            r.raise_for_status()
            try:
                for event, data in _parse_sse(r.iter_lines(chunk_size=1, decode_unicode=True)):
                    try:
                        j = json.loads(data)
                    except ValueError:
                        continue
                    if event == "ping" and isinstance(j, dict) and j.get("title") is not None:
                        title = str(j["title"])
                    elif event == "state" and isinstance(j, dict) and j.get("id") and (j.get("domain") or str(j["id"]).split("/", 1)[0]) in DOMAINS:
                        ents[str(j["id"])] = {"entity": str(j["id"]), "name": str(j.get("name") or str(j["id"]).split("/", 1)[-1]),
                                              "domain": str(j.get("domain") or str(j["id"]).split("/", 1)[0]), "value": bool(j.get("value"))}
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


def _set_online(ip: str, online: bool) -> None:
    with _lock:
        h = _hosts.get(ip)
        if h is not None:
            h["online"] = online
        if online:                                                          # frische Verbindung: Anfangszustand zaehlt nie als Druck
            for k, st in _state.items():
                if k[0] == ip:
                    st["value"] = None


def _on_state(ip: str, j: dict) -> None:
    ent = str(j.get("id") or "")
    if not ent or (j.get("domain") or ent.split("/", 1)[0]) not in DOMAINS:        # Aenderungsmeldungen tragen kein "domain", nur "id", "value", "state" - die Art steht im Praefix der Kennung
        return
    val = bool(j.get("value"))
    pressed = False
    with _lock:
        st = _state.setdefault((ip, ent), {"value": None, "pressed_at": 0.0, "seq": 0, "consumed": 0, "saw_on": False, "mask": False, "pass_on": False})
        if val and st["value"] is False and ent in _wanted.get(ip, ()):
            st["pressed_at"] = time.time()
            if st["seq"] - st["consumed"] < MAX_QUEUE:
                st["seq"] += 1
            pressed = True
        st["value"] = val
    if pressed:
        _notify()


def _watch(ip: str, stop: threading.Event) -> None:
    backoff = BACKOFF_START_S
    while not stop.is_set() and not _stop_all.is_set():
        try:
            with requests.get(_url(ip, "/events"), stream=True, timeout=(PROBE_CONNECT_S, STREAM_READ_S)) as r:
                r.raise_for_status()
                _set_online(ip, True)
                backoff = BACKOFF_START_S
                for event, data in _parse_sse(r.iter_lines(chunk_size=1, decode_unicode=True)):
                    if stop.is_set() or _stop_all.is_set():
                        break
                    if event == "state":
                        try:
                            j = json.loads(data)
                        except ValueError:
                            continue
                        if isinstance(j, dict):
                            _on_state(ip, j)
        except (requests.RequestException, OSError, ValueError) as e:
            log.debug("ESPHome %s: Verbindung beendet (%s: %s)", ip, e.__class__.__name__, e)
        _set_online(ip, False)
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


def release(ip: str) -> None:
    with _lock:
        h = _hosts.pop(ip, None)
        for k in [k for k in _state if k[0] == ip]:
            _state.pop(k, None)
        _wanted.pop(ip, None)
    if h:
        h["stop"].set()


def sync(devices: list[dict]) -> None:
    """Verbindungen an das Geraeteregister angleichen: neue Adressen verbinden, nicht mehr benoetigte trennen."""
    want = {str(d.get("ip")) for d in devices if d.get("kind") == "esphome" and d.get("ip")}
    with _lock:
        _wanted.clear()
        for d in devices:
            if d.get("kind") == "esphome" and d.get("ip") and d.get("entity"):
                _wanted.setdefault(str(d["ip"]), set()).add(str(d["entity"]))
    for ip in want:
        ensure(ip)
    with _lock:
        gone = [ip for ip in _hosts if ip not in want]
    for ip in gone:
        release(ip)


def start(wake_cb, load_devices, enabled_cb=None) -> None:
    """Hintergrund: haelt die Verbindungen zu allen ESPHome-Geraeten des Registers. wake_cb(): Regelschleife wecken."""
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
                    sync(load_devices())
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


def status(d: dict) -> dict:
    """{'online', 'on', 'power', 'shown'}. 'on' = ein Druck wartet darauf, von den Regeln gesehen zu werden (Impuls; Geraet offline: None);
    'shown' = der letzte Druck liegt hoechstens DISPLAY_S Sekunden zurueck (nur fuer die Anzeige)."""
    ip, ent = str(d.get("ip") or ""), str(d.get("entity") or "")
    with _lock:
        _wanted.setdefault(ip, set()).add(ent)             # auch ohne vorherigen Abgleich (z. B. gerade angelegt) zaehlt dieser Eingang
    ensure(ip)
    with _lock:
        h = _hosts.get(ip)
        online = bool(h and h["online"])
        st = _state.get((ip, ent)) or {}
        pa, pending = st.get("pressed_at", 0.0), st.get("seq", 0) > st.get("consumed", 0) and not st.get("mask")
    if not online:
        return {"online": False, "on": None, "power": None, "shown": False}
    return {"online": True, "on": pending, "power": None, "shown": (time.time() - pa) < DISPLAY_S}
