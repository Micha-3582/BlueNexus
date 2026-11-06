"""
Bambu-Lab-Drucker (X1C, P1, A1 ...) im lokalen Netz: Druckstatus ueber die MQTT-Schnittstelle des Druckers (Port 8883, TLS, Benutzer "bblp",
Passwort = Zugangscode aus den Druckereinstellungen). Nur lesen - BlueNexus steuert den Drucker nicht.

Ein Eintrag im Geraeteregister (shelly.py, kind "bambu") = ein Drucker: ip, serial (Seriennummer), password (Zugangscode).
"An" bedeutet: der Drucker druckt gerade (auch vorbereiten oder pausiert). "Druck fertig" ist damit die Flanke an -> aus (Regel).
Die Verbindung wird gehalten (ein Thread je Drucker) und liefert laufend Fortschritt, Temperaturen, Restzeit und Fehler.

Der MQTT-Teil ist bewusst klein und ohne Zusatz-Paket: Verbinden, Abonnieren, Nachrichten lesen, Ping, eine Anfrage senden.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import ssl
import threading
import time

log = logging.getLogger("bambu")

PORT = 8883
USE_TLS = True                        # nur der Test schaltet das ab (nachgebauter Drucker ohne Zertifikat)
USER = "bblp"
CONNECT_S = 8.0                       # Zeit zum Verbinden (TCP + TLS)
READ_S = 5.0                          # Lesen blockiert hoechstens so lange, danach wird Ping/Anfrage geprueft
KEEPALIVE_S = 60
PING_S = 25.0
PUSHALL_S = 300.0                     # alle 5 min den vollstaendigen Stand anfordern (Teilmeldungen reichen sonst nicht bei jedem Modell)
BACKOFF_START_S, BACKOFF_MAX_S = 2.0, 30.0
GRACE_S = 120.0                       # nach einem Abbruch gilt der letzte Stand noch so lange (WLAN-Aussetzer des Druckers)
CAMERA_PORT, CAMERA_PATH = 322, "/streaming/live/1"      # Kamera der X1-Modelle: rtsps://bblp:<Zugangscode>@<IP>:322/streaming/live/1
PROBE_S = 10.0                        # Pruefen beim Anlegen: so lange auf die erste Meldung warten
ACTIVE = ("PREPARE", "RUNNING", "PAUSE")
STATE_TEXT = {"IDLE": "bereit", "PREPARE": "bereitet vor", "RUNNING": "druckt", "PAUSE": "pausiert", "FINISH": "fertig", "FAILED": "Fehler"}


class BambuError(Exception):
    pass


# ---------------------------------------------------------------- MQTT (Version 3.1.1, nur was gebraucht wird)
def _varlen(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n % 128, n // 128
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _s(text: str) -> bytes:
    b = text.encode("utf-8")
    return len(b).to_bytes(2, "big") + b


def _packet(first: int, body: bytes) -> bytes:
    return bytes([first]) + _varlen(len(body)) + body


def connect_packet(client_id: str, user: str, password: str) -> bytes:
    return _packet(0x10, _s("MQTT") + bytes([4, 0xC2]) + KEEPALIVE_S.to_bytes(2, "big") + _s(client_id) + _s(user) + _s(password))


def subscribe_packet(topic: str, pid: int = 1) -> bytes:
    return _packet(0x82, pid.to_bytes(2, "big") + _s(topic) + b"\x00")


def publish_packet(topic: str, payload: bytes) -> bytes:
    return _packet(0x30, _s(topic) + payload)


PING = b"\xc0\x00"


def _recv_exact(sock, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Verbindung vom Drucker beendet")
        buf += chunk
    return buf


def read_packet(sock):
    """(Typ, Flags, Inhalt) des naechsten Pakets; wirft socket.timeout, wenn nichts kommt."""
    first = _recv_exact(sock, 1)[0]
    mult, length = 1, 0
    for _ in range(4):
        b = _recv_exact(sock, 1)[0]
        length += (b & 0x7F) * mult
        if not b & 0x80:
            break
        mult *= 128
    return first >> 4, first & 0x0F, (_recv_exact(sock, length) if length else b"")


def parse_publish(flags: int, body: bytes):
    tl = int.from_bytes(body[:2], "big")
    topic = body[2:2 + tl].decode("utf-8", "replace")
    pos = 2 + tl + (2 if (flags >> 1) & 3 else 0)                     # bei QoS > 0 folgt eine Paketnummer
    return topic, body[pos:]


def _open(ip: str, user: str, code: str, serial: str, client_id: str):
    raw = socket.create_connection((ip, PORT), CONNECT_S)
    sock = raw
    if USE_TLS:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE                               # der Drucker hat ein eigenes (selbst signiertes) Zertifikat
        sock = ctx.wrap_socket(raw, server_hostname=ip)
    sock.settimeout(CONNECT_S)
    sock.sendall(connect_packet(client_id, user, code))
    typ, _f, body = read_packet(sock)
    if typ != 2 or len(body) < 2:
        raise BambuError("Unerwartete Antwort des Druckers")
    if body[1] in (4, 5):
        raise BambuError("Der Zugangscode wird vom Drucker nicht akzeptiert")
    if body[1] != 0:
        raise BambuError(f"Der Drucker hat die Verbindung abgelehnt (Code {body[1]})")
    sock.sendall(subscribe_packet(f"device/{serial}/report"))
    return sock


def _request(sock, serial: str) -> None:
    msg = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}).encode()
    sock.sendall(publish_packet(f"device/{serial}/request", msg))


# ---------------------------------------------------------------- Zustand und Verbindungen
_lock = threading.RLock()
_hosts: dict[str, dict] = {}                          # Seriennummer -> {"stop", "thread", "ip", "code", "online"}
_data: dict[str, dict] = {}                           # Seriennummer -> {"print": {...}, "ts": Zeit der letzten Meldung}
_error: dict[str, str] = {}                           # Seriennummer -> letzte Fehlermeldung der Verbindung
_wake = None


def set_wake(fn) -> None:
    """Funktion, die die Regeln sofort anstoesst, wenn sich der Druckzustand aendert (z. B. fertig)."""
    global _wake
    _wake = fn


def _merge(serial: str, js: dict) -> None:
    p = js.get("print") if isinstance(js, dict) else None
    if not isinstance(p, dict):
        return
    changed = False
    with _lock:
        cur = _data.setdefault(serial, {"print": {}, "ts": 0.0})
        old = cur["print"].get("gcode_state")
        cur["print"].update(p)
        cur["ts"] = time.time()
        changed = "gcode_state" in p and p["gcode_state"] != old
    if changed and _wake:
        try:
            _wake()
        except Exception:                                     # noqa: BLE001
            pass


def _watch(serial: str, stop: threading.Event, ip: str, code: str) -> None:
    backoff = BACKOFF_START_S
    cid = "bluenexus-" + os.urandom(3).hex()
    while not stop.is_set():
        sock = None
        try:
            sock = _open(ip, USER, code, serial, cid)
            with _lock:
                h = _hosts.get(serial)
                if h and h["stop"] is stop:
                    h["online"] = True
                _error.pop(serial, None)
            backoff = BACKOFF_START_S
            sock.settimeout(READ_S)
            _request(sock, serial)
            last_ping = last_push = time.time()
            while not stop.is_set():
                try:
                    typ, flags, body = read_packet(sock)
                    if typ == 3:
                        _topic, payload = parse_publish(flags, body)
                        try:
                            _merge(serial, json.loads(payload.decode("utf-8", "replace")))
                        except ValueError:
                            pass
                except socket.timeout:
                    pass
                now = time.time()
                if now - last_ping > PING_S:
                    sock.sendall(PING)
                    last_ping = now
                if now - last_push > PUSHALL_S:
                    _request(sock, serial)
                    last_push = now
        except BambuError as e:
            with _lock:
                _error[serial] = str(e)
        except (OSError, ConnectionError, ssl.SSLError) as e:
            with _lock:
                _error[serial] = "Drucker nicht erreichbar" if isinstance(e, (socket.timeout, ConnectionRefusedError)) else str(e) or e.__class__.__name__
        finally:
            with _lock:
                h = _hosts.get(serial)
                if h and h["stop"] is stop:
                    h["online"] = False
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        if stop.wait(backoff):
            return
        backoff = min(BACKOFF_MAX_S, backoff * 2)


def ensure(d: dict) -> None:
    serial, ip, code = str(d.get("serial") or ""), str(d.get("ip") or ""), str(d.get("password") or "")
    if not (serial and ip and code):
        return
    with _lock:
        h = _hosts.get(serial)
        if h and h["thread"].is_alive() and (h["ip"], h["code"]) == (ip, code):
            return
        old = _hosts.pop(serial, None)
        stop = threading.Event()
        t = threading.Thread(target=_watch, args=(serial, stop, ip, code), name="bambu-" + serial[-4:], daemon=True)
        _hosts[serial] = {"stop": stop, "thread": t, "ip": ip, "code": code, "online": False}
    if old:
        old["stop"].set()
    t.start()


def release(serial: str) -> None:
    with _lock:
        h = _hosts.pop(serial, None)
        _data.pop(serial, None)
        _error.pop(serial, None)
    if h:
        h["stop"].set()


def sync(devices: list) -> None:
    """Verbindungen an das Geraeteregister angleichen: neue Drucker verbinden, entfernte trennen."""
    want = {str(d.get("serial")): d for d in devices if d.get("kind") == "bambu" and d.get("serial")}
    for d in want.values():
        ensure(d)
    with _lock:
        gone = [s for s in _hosts if s not in want]
    for s in gone:
        release(s)


def probe(ip: str, serial: str, code: str) -> dict:
    """Beim Anlegen: verbinden und auf die erste Meldung warten. Gibt {"model", "name", "state"} zurueck; wirft BambuError mit klarer Meldung."""
    serial = serial.strip()
    if not (ip and serial and code):
        raise BambuError("Adresse, Seriennummer und Zugangscode werden gebraucht")
    try:
        sock = _open(ip, USER, code, serial, "bluenexus-probe-" + os.urandom(2).hex())
    except BambuError:
        raise
    except (OSError, ssl.SSLError) as e:
        raise BambuError("Der Drucker antwortet nicht – Adresse prüfen und ob er im Netzwerk ist (" + (str(e) or e.__class__.__name__) + ")")
    got: dict = {}
    try:
        sock.settimeout(READ_S)
        _request(sock, serial)
        end = time.time() + PROBE_S
        while time.time() < end and not got.get("gcode_state"):
            try:
                typ, flags, body = read_packet(sock)
            except socket.timeout:
                continue
            if typ == 3:
                try:
                    p = json.loads(parse_publish(flags, body)[1].decode("utf-8", "replace")).get("print")
                except ValueError:
                    continue
                if isinstance(p, dict):
                    got.update(p)
    except (OSError, ConnectionError, ssl.SSLError):
        pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not got.get("gcode_state"):
        raise BambuError("Der Drucker meldet nichts – stimmt die Seriennummer? (Der Drucker muss dafür im LAN-Modus oder mit eingeschaltetem Zugriff im Heimnetz laufen.)")
    return {"state": got.get("gcode_state"), "name": str(got.get("subtask_name") or ""), "model": str(got.get("hw_ver") or "")}


# ---------------------------------------------------------------- Status fuer BlueNexus
def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x != x else x


def _n(v: float) -> str:
    return f"{v:g}".replace(".", ",")


def info_text(s: dict) -> str:
    st = s.get("state")
    parts = []
    if st:
        parts.append(STATE_TEXT.get(st, str(st).lower()))
    if st in ACTIVE:
        if s.get("progress") is not None:
            parts[0] = f"{parts[0]} {int(round(s['progress']))} %"
        if s.get("remaining_min") is not None:
            m = int(s["remaining_min"])
            parts.append("noch " + (f"{m // 60} h {m % 60} min" if m >= 60 else f"{m} min"))
    if s.get("job"):
        parts.append(s["job"])
    if s.get("nozzle_c") is not None:
        parts.append(f"Düse {_n(round(s['nozzle_c']))} °C")
    if s.get("bed_c") is not None:
        parts.append(f"Bett {_n(round(s['bed_c']))} °C")
    if s.get("error"):
        parts.append("Fehlermeldung am Drucker")
    return " · ".join(parts)


def status(d: dict) -> dict:
    """{'online', 'on' (druckt), 'power', 'state', 'progress', 'remaining_min', 'nozzle_c', 'bed_c', 'chamber_c', 'layer', 'layers', 'job', 'error', 'info'}"""
    ensure(d)
    serial = str(d.get("serial") or "")
    with _lock:
        h = _hosts.get(serial)
        online = bool(h and h["online"])
        cur = _data.get(serial)
        p, ts = (dict(cur["print"]), cur["ts"]) if cur else ({}, 0.0)
        err = _error.get(serial)
    if not p or not (online or time.time() - ts < GRACE_S):
        out = {"online": False, "on": None, "power": None}
        if err:
            out["error_text"] = err
        return out
    state = str(p.get("gcode_state") or "")
    pe = p.get("print_error")
    out = {"online": True, "on": state in ACTIVE, "power": None, "state": state or None,
           "progress": _f(p.get("mc_percent")), "remaining_min": _f(p.get("mc_remaining_time")),
           "nozzle_c": _f(p.get("nozzle_temper")), "bed_c": _f(p.get("bed_temper")), "chamber_c": _f(p.get("chamber_temper")),
           "layer": _f(p.get("layer_num")), "layers": _f(p.get("total_layer_num")),
           "job": str(p.get("subtask_name") or p.get("gcode_file") or "") or None,
           "error": bool(pe) and state in ("FAILED", "PAUSE")}
    out["info"] = info_text(out)
    return out


# ---------------------------------------------------------------- Anlegen (Geraeteregister)
def add_device(ip: str, serial: str, code: str, name: str = "") -> dict:
    """Prueft die Zugangsdaten am Drucker und legt ihn im Geraeteregister an (nicht schaltbar, nur Status). Wirft shelly.ShellyError mit klarer Meldung."""
    import idsafe
    import shelly
    ip = shelly.check_ip(ip)
    serial, code = (serial or "").strip().upper(), (code or "").strip()
    if not (6 <= len(serial) <= 24) or not serial.isalnum():
        raise shelly.ShellyError("Die Seriennummer sieht nicht richtig aus (Buchstaben und Ziffern, steht am Drucker und in den Geräteinfos)")
    try:
        probe(ip, serial, code)
    except BambuError as e:
        raise shelly.ShellyError(str(e))
    dev_id = "bambu-" + idsafe.safe_id(serial.lower())
    items = shelly.load_devices()
    if any(d["id"] == dev_id or (d.get("kind") == "bambu" and d.get("serial") == serial) for d in items):
        raise shelly.ShellyError("Dieser Drucker ist schon angelegt")
    entry = {"id": dev_id, "kind": "bambu", "ip": ip, "serial": serial, "password": code, "user": "", "gen": 0, "channel": 0,
             "model": "Bambu Lab" + (f" · {serial}" if serial else ""), "name": (name or "").strip()[:60] or "Bambu-Lab-Drucker", "icon": "🖨️",
             "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "switchable": False, "users": []}
    items.append(entry)
    shelly._save(items)
    ensure(entry)
    return {k: v for k, v in entry.items() if k not in ("password", "user")}


def add_camera(dev_id: str) -> dict:
    """Legt die Kamera eines X1-Druckers (RTSPS-Strom, Port 322, gleicher Zugangscode) als Kamera an. Wirft shelly.ShellyError mit klarer Meldung."""
    import camera
    import shelly
    d = shelly._find(dev_id)
    if not d or d.get("kind") != "bambu":
        raise shelly.ShellyError("Drucker nicht gefunden")
    if any(c.get("kind") == "rtsp" and c.get("host") == d.get("ip") and int(c.get("port") or 0) == CAMERA_PORT for c in camera.load()):
        raise shelly.ShellyError("Für diesen Drucker gibt es schon eine Kamera (Kameras)")
    try:
        item = camera.add(f"{d.get('name') or 'Drucker'} – Kamera", d["ip"], USER, d.get("password") or "", CAMERA_PORT, 0, False, "rtsp", CAMERA_PATH, "", True)
    except camera.CameraError as e:
        raise shelly.ShellyError(f"{e}. Am Drucker muss die Live-Ansicht im LAN freigegeben sein (Einstellungen → Allgemein → „LAN-Modus Liveview“). "
                                 "Einen RTSP-Strom bieten die Modelle X1C, X1E und H2D; P1 und A1 verwenden ein anderes Verfahren, das BlueNexus noch nicht kann.")
    return item
