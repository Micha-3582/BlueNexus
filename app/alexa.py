"""
Alexa-Anbindung per Hue-Emulation (lokal, ohne Cloud, ohne Amazon-Entwicklerkonto).

Die App gibt sich im Heimnetz als Philips-Hue-Bridge (v1-Schnittstelle) aus. Echo-Geraete finden sie ueber SSDP (UDP 1900) und sprechen
dann HTTP auf Port 80. Jedes freigegebene Geraet erscheint in der Alexa-App als Lampe oder als Steckdose (je Geraet waehlbar) und laesst
sich per Sprache ein-/ausschalten ("Alexa, schalte den Warmwasser-Timer ein"). Die Freigabe macht ein Administrator; Geraete mit PIN
(und Tuerschloesser) sind ausgeschlossen, damit Sprache die PIN nie umgehen kann.

Dieses Modul kennt keine Geraetetypen der App: Zustand lesen und Schalten liefert der Aufrufer (webapp.py) als Funktionen.
Eigenes Register: alexa.json (Freigaben + Alexa-Namen). Alles hier ist reine Netzwerk-/Registerlogik und testbar (Ports einstellbar).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import socket
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("alexa")

_DIR = os.path.dirname(os.path.abspath(__file__))
ALEXA_PATH = os.path.join(_DIR, "alexa.json")
KINDS = ("shelly", "virtual")                 # shelly = alle Hardware-Geraete der App (Shelly, Tasmota, Tuya, Homematic, Zigbee), virtual = eigene Schalter/Knoepfe
TYPES = ("light", "plug")
SSDP_ADDR, SSDP_PORT = "239.255.255.250", 1900
MAX_DEVICES = 40
_lock = threading.RLock()


class AlexaError(ValueError):
    pass


# ---------------------------------------------------------------- Register
def _store():
    import store
    return store


def load() -> list[dict]:
    with _lock:
        d = _store()._load_json_recovering(ALEXA_PATH, lambda: [])
        return [x for x in d if isinstance(x, dict) and x.get("hid") and x.get("kind") in KINDS and x.get("ref")] if isinstance(d, list) else []


def _save(items: list[dict]):
    with _lock:
        _store()._dump_json(ALEXA_PATH, items, indent=2)


def _clean_name(name) -> str:
    n = " ".join(str(name or "").split())
    if not 1 <= len(n) <= 32:
        raise AlexaError("Name für Alexa: 1 bis 32 Zeichen")
    return n


def add(kind: str, ref: str, name: str, typ: str = "light") -> dict:
    kind, ref = str(kind), str(ref)
    if kind not in KINDS or not ref:
        raise AlexaError("Unbekanntes Gerät")
    if typ not in TYPES:
        raise AlexaError("Art: Lampe oder Steckdose")
    name = _clean_name(name)
    with _lock:
        items = load()
        if len(items) >= MAX_DEVICES:
            raise AlexaError(f"Höchstens {MAX_DEVICES} Geräte für Alexa")
        if any(x["kind"] == kind and x["ref"] == ref for x in items):
            raise AlexaError("Dieses Gerät ist schon für Alexa freigegeben")
        if any(x["name"].lower() == name.lower() for x in items):
            raise AlexaError("Dieser Name ist für Alexa schon vergeben")
        hid = max([int(x["hid"]) for x in items] + [0]) + 1
        item = {"hid": hid, "kind": kind, "ref": ref, "name": name, "type": typ}
        items.append(item)
        _save(items)
        return item


def update(hid, name=None, typ=None) -> bool:
    with _lock:
        items = load()
        for x in items:
            if str(x["hid"]) == str(hid):
                if name is not None:
                    n = _clean_name(name)
                    if any(y is not x and y["name"].lower() == n.lower() for y in items):
                        raise AlexaError("Dieser Name ist für Alexa schon vergeben")
                    x["name"] = n
                if typ is not None:
                    if typ not in TYPES:
                        raise AlexaError("Art: Lampe oder Steckdose")
                    x["type"] = typ
                _save(items)
                return True
    return False


def reorder(hids) -> None:
    """Neue Reihenfolge der freigegebenen Geraete (nur die Anzeige; Kennungen und Alexa-Zuordnung aendern sich nicht)."""
    with _lock:
        items = load()
        by = {str(x["hid"]): x for x in items}
        ids = [str(i) for i in hids if str(i) in by]
        slots = sorted(n for n, x in enumerate(items) if str(x["hid"]) in set(ids))
        for slot, i in zip(slots, ids):
            items[slot] = by[i]
        _save(items)


def remove(hid) -> bool:
    with _lock:
        items = load()
        keep = [x for x in items if str(x["hid"]) != str(hid)]
        if len(keep) == len(items):
            return False
        _save(keep)
        return True


def remove_ref(kind: str, ref: str) -> bool:
    """Geraet in der App geloescht -> Freigabe entfernen."""
    with _lock:
        items = load()
        keep = [x for x in items if not (x["kind"] == kind and x["ref"] == str(ref))]
        if len(keep) == len(items):
            return False
        _save(keep)
        return True


# ---------------------------------------------------------------- Hue-Nachbildung
def _serial() -> str:
    return f"{uuid.getnode() & 0xFFFFFFFFFFFF:012x}"


def _bridge_id(serial: str) -> str:
    return (serial[:6] + "FFFE" + serial[6:]).upper()


def new_serial() -> str:
    """Zufaellige, dauerhaft zu speichernde Bridge-Kennung (12 Hex-Zeichen, Philips-Praefix). Jede App-Instanz braucht ihre eigene, sonst
    haelt Alexa zwei Bridges fuer dieselbe."""
    return "001788" + uuid.uuid4().hex[:6]


def light_json(dev: dict, on, reachable: bool = True, serial: str | None = None) -> dict:
    """Ein Geraet im Hue-Format (Lampe: dimmbar, Steckdose: 'On/off plug-in unit' wie die Hue Smart Plug)."""
    hid = int(dev["hid"])
    serial = serial or _serial()
    # Jedes Geraet braucht einen EIGENEN vorderen Teil der Kennung (wie bei echten Hue-Lampen und bei Home Assistant) - Alexa haelt Geraete mit gleichem Anfang
    # sonst fuer dasselbe und nimmt nur das erste. Aus Bridge-Kennung, Nummer und Art abgeleitet: stabil, aber neue Kennung bei anderer Art (dann legt Alexa neu an).
    h = hashlib.md5(f"{serial}-{hid}-{dev.get('type', 'light')}".encode()).hexdigest()
    uid = "00:17:88:01:" + ":".join(h[k:k + 2] for k in range(0, 8, 2)) + "-0b"
    state = {"on": bool(on), "alert": "none", "mode": "homeautomation", "reachable": bool(reachable)}
    if dev.get("type") == "plug":                   # wie Tasmota/Espalexa-Steckdosen: Alexa erkennt "Dimmable plug-in unit"/"Plug 01" bei der lokalen Suche als Steckdose
        st2 = {**state, "bri": 254}
        return {"state": st2, "type": "Dimmable plug-in unit", "name": dev["name"], "modelid": "Plug 01", "manufacturername": "OpenSource",
                "productname": "E1", "uniqueid": uid, "swversion": "2.0"}
    # Lampe: schlank wie bei Tasmota/Espalexa (nur Zustand, Typ, Name, Modell, Hersteller, Kennung) - ein mit allen Feldern einer echten Hue-Lampe
    # nachgebautes JSON hat Alexa bei der lokalen Suche nicht uebernommen
    return {"state": {**state, "bri": 254}, "type": "Dimmable light", "name": dev["name"], "modelid": "LWB010", "manufacturername": "Philips",
            "productname": "E1", "uniqueid": uid, "swversion": "2.0"}


def username_for(serial: str) -> str:
    """Benutzername, den die Bridge bei der Anmeldung vergibt: 40 Zeichen wie bei einer echten Hue-Bridge, aus der Kennung abgeleitet (stabil)."""
    return hashlib.sha1(("hue-user-" + serial).encode()).hexdigest()


def description_xml(ip: str, port: int, serial: str | None = None) -> str:
    serial = serial or _serial()
    return f"""<?xml version="1.0" encoding="UTF-8" ?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<specVersion><major>1</major><minor>0</minor></specVersion>
<URLBase>http://{ip}:{port}/</URLBase>
<device>
<deviceType>urn:schemas-upnp-org:device:Basic:1</deviceType>
<friendlyName>Philips hue ({ip})</friendlyName>
<manufacturer>Royal Philips Electronics</manufacturer>
<manufacturerURL>http://www.philips.com</manufacturerURL>
<modelDescription>Philips hue Personal Wireless Lighting</modelDescription>
<modelName>Philips hue bridge 2012</modelName>
<modelNumber>929000226503</modelNumber>
<modelURL>http://www.meethue.com</modelURL>
<serialNumber>{serial}</serialNumber>
<UDN>uuid:2f402f80-da50-11e1-9b23-{serial}</UDN>
<presentationURL>index.html</presentationURL>
</device>
</root>
"""


def config_json(ip: str, full: bool = True, serial: str | None = None) -> dict:
    serial = serial or _serial()
    base = {"name": "Philips hue", "datastoreversion": "71", "swversion": "01041302", "apiversion": "1.17.0", "mac": ":".join(serial[i:i + 2] for i in range(0, 12, 2)),
            "bridgeid": _bridge_id(serial), "factorynew": False, "replacesbridgeid": None, "modelid": "BSB002", "starterkitid": ""}
    if full:
        base.update({"ipaddress": ip, "netmask": "255.255.255.0", "gateway": ip, "dhcp": True, "portalservices": False, "linkbutton": True,
                     "whitelist": {username_for(serial): {"name": "alexa", "create date": "2020-01-01T00:00:00", "last use date": "2020-01-01T00:00:00"}}})
    return base


class Bridge:
    """Hue-Bridge-Nachbildung: HTTP (Port 80) + SSDP. get_states(devs) -> {hid: (on, erreichbar)}; set_state(dev, on) -> bool."""

    def __init__(self, get_states, set_state, http_port: int = 80, ssdp_port: int = SSDP_PORT, multicast: bool = True, bind_ip: str = "", serial: str = ""):
        self.get_states, self.set_state = get_states, set_state
        self.http_port, self.ssdp_port, self.multicast = http_port, ssdp_port, multicast
        self.bind_ip = bind_ip                          # eigene Adresse dieser Bridge (leer = alle). Zwei Apps auf einem Server: je eine eigene IP, beide auf Port 80
        self.serial = serial or _serial()               # Kennung dieser Bridge (je App-Instanz eigene)
        self.public_port: int | None = None            # Port, den Echo-Geraete ansprechen (80). None = derselbe wie http_port. Laeuft ein Webserver (Apache/nginx) davor: public 80, http_port intern
        self.error = ""
        self.running = False
        self.seen = 0                                   # Anfragen von Echo-Geraeten (HTTP)
        self.last_seen = 0.0
        self.last_ssdp = 0.0
        self.last_cmd = ""
        self.events: list[dict] = []                    # letzte Anfragen (Fehlersuche): SSDP-Suchen und HTTP-Aufrufe von Echo-Geraeten
        self.ssdp_note = ""                             # Zustand des Suchkanals (UDP 1900)
        self.foreign = 0                                # fremde SSDP-Suchen im Netz (zeigen, dass der Suchkanal Anfragen empfaengt)
        self._httpd = None
        self._sock = None
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def note(self, kind: str, peer: str, text: str):
        self.events.append({"ts": time.time(), "kind": kind, "peer": peer, "text": text[:160]})
        del self.events[:-40]

    # ---- Start/Stopp
    def start(self):
        if self.running:
            return
        self.error = ""
        self._stop.clear()
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _local_ip(self) -> str:
                host = (self.headers.get("Host") or "").split(":")[0]          # hinter einem Webserver (ProxyPreserveHost On) steht hier die Adresse, die Echo benutzt hat
                parts = host.split(".")
                if len(parts) == 4 and all(x.isdigit() and 0 <= int(x) <= 255 for x in parts):
                    return host
                return bridge.bind_ip or self.connection.getsockname()[0]

            def _send(self, code, body, ctype="application/json"):
                if not self.path.startswith("/favicon"):
                    ms = int((time.time() - getattr(self, "_t0", time.time())) * 1000)
                    bridge.note("HTTP", self.client_address[0], f"{self.command} {self.path.split('?')[0]} → {code} ({ms} ms)")
                data = (body if isinstance(body, str) else json.dumps(body)).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")                  # wie die kleinen Hue-/Tasmota-Bridges: pro Anfrage eine Verbindung
                self.close_connection = True
                self.end_headers()
                self.wfile.write(data)

            def _body(self) -> dict:
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(n) if n else b""
                    d = json.loads(raw.decode("utf-8")) if raw else {}
                    return d if isinstance(d, dict) else {}
                except (ValueError, OSError):
                    return {}

            def _devs(self):
                return {str(d["hid"]): d for d in load()}

            def _lights(self, devs: dict) -> dict:
                try:
                    states = bridge.get_states(list(devs.values())) or {}
                except Exception as e:                  # noqa: BLE001
                    log.warning("Alexa: Zustände nicht lesbar: %s", e)
                    states = {}
                out = {}
                for h, d in devs.items():
                    on, ok = states.get(d["hid"], (False, False))
                    out[h] = light_json(d, bool(on), True, bridge.serial)       # immer "erreichbar": Alexa uebergeht sonst Geraete, die beim Suchen gerade offline sind; ein echter Fehler zeigt sich beim Schalten
                return out

            def _route(self, method: str):
                self._t0 = time.time()
                bridge.seen += 1
                bridge.last_seen = time.time()
                path = self.path.split("?")[0].rstrip("/") or "/"
                parts = [p for p in path.split("/") if p]
                if path in ("/description.xml", "/index.html"):
                    return self._send(200, description_xml(self._local_ip(), bridge.public_port or bridge.http_port, bridge.serial), "text/xml")
                if not parts or parts[0] != "api":
                    return self._send(404, {"error": "nicht gefunden"})
                if len(parts) == 1:                        # POST /api -> "Link"-Anmeldung (immer erlaubt)
                    if method == "POST":
                        ok = {"username": username_for(bridge.serial)}
                        if self._body().get("generateclientkey"):                # neuere Alexa-/Hue-Clients verlangen bei der Anmeldung einen Clientkey
                            ok["clientkey"] = uuid.uuid4().hex.upper()
                        return self._send(200, [{"success": ok}])
                    return self._send(200, config_json(self._local_ip(), False, bridge.serial))
                if parts[1] == "config" and len(parts) == 2:
                    return self._send(200, config_json(self._local_ip(), False, bridge.serial))
                rest = parts[2:]                           # parts[1] = Benutzername (beliebig)
                devs = self._devs()
                if not rest:
                    lights = self._lights(devs)
                    return self._send(200, {"lights": lights, "groups": {}, "config": config_json(self._local_ip(), True, bridge.serial), "schedules": {}, "scenes": {}, "rules": {}, "sensors": {}, "resourcelinks": {}})
                if rest[0] == "lights":
                    if len(rest) == 1:
                        return self._send(200, self._lights(devs) if method == "GET" else [])
                    d = devs.get(rest[1])
                    if rest[1] == "new":
                        return self._send(200, {})
                    if d is None:
                        return self._send(200, [{"error": {"type": 3, "address": "/lights/" + rest[1], "description": "resource not available"}}])
                    if len(rest) == 2:
                        return self._send(200, self._lights({rest[1]: d})[rest[1]])
                    if len(rest) == 3 and rest[2] == "state" and method == "PUT":
                        body = self._body()
                        on = body.get("on") if "on" in body else ((float(body.get("bri", 0)) > 0) if "bri" in body else None)
                        out = []
                        if on is not None:
                            ok = False
                            try:
                                ok = bool(bridge.set_state(d, bool(on)))
                            except Exception as e:      # noqa: BLE001
                                log.warning("Alexa: Schalten von %s fehlgeschlagen: %s", d.get("name"), e)
                            bridge.last_cmd = f"{time.strftime('%H:%M:%S')} {d['name']} → {'ein' if on else 'aus'}" + ("" if ok else " (fehlgeschlagen)")
                            out.append({"success": {f"/lights/{rest[1]}/state/on": bool(on)}} if ok else {"error": {"type": 901, "address": f"/lights/{rest[1]}/state", "description": "internal error"}})
                        if "bri" in body and on is not None and ok:
                            out.append({"success": {f"/lights/{rest[1]}/state/bri": body["bri"]}})
                        return self._send(200, out)
                    return self._send(200, [])
                if rest[0] in ("groups", "scenes", "schedules", "rules", "sensors", "resourcelinks", "capabilities"):
                    return self._send(200, {} if method == "GET" else [])
                if rest[0] == "config":
                    return self._send(200, config_json(self._local_ip(), True, bridge.serial))
                return self._send(200, [])

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PUT(self):
                self._route("PUT")

            def do_DELETE(self):
                self._route("DELETE")

        try:
            ThreadingHTTPServer.allow_reuse_address = True
            ThreadingHTTPServer.daemon_threads = True
            self._httpd = ThreadingHTTPServer((self.bind_ip or "0.0.0.0", self.http_port), Handler)
        except OSError as e:
            self.error = (f"{(self.bind_ip + ':') if self.bind_ip else 'Port '}{self.http_port} ist nicht frei ({e.strerror or e}) – dort läuft schon ein anderer Dienst "
                          "(z. B. Apache oder nginx). Echo-Geräte brauchen Port 80: den anderen Dienst beenden und die App neu starten.")
            log.warning("Alexa: %s", self.error)
            self._httpd = None
            return
        t = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="alexa-http")
        t.start()
        self._threads = [t]
        try:
            self._ssdp_start()
        except OSError as e:
            self.error = f"SSDP (UDP {self.ssdp_port}) nicht möglich: {e.strerror or e} – Alexa findet die Geräte so nicht automatisch."
            log.warning("Alexa: %s", self.error)
        self.running = True

    def stop(self):
        self._stop.set()
        self.running = False
        try:
            if self._httpd:
                self._httpd.shutdown()
                self._httpd.server_close()
        except Exception:                               # noqa: BLE001
            pass
        self._httpd = None
        try:
            if self._sock:
                self._sock.close()
        except OSError:
            pass
        self._sock = None
        self._threads = []

    # ---- SSDP
    def _ssdp_start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.bind(("", self.ssdp_port))
        if self.multicast:
            try:
                s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, struct.pack("4s4s", socket.inet_aton(SSDP_ADDR), socket.inet_aton("0.0.0.0")))
            except OSError as e:
                s.close()
                raise OSError(f"Multicast-Gruppe nicht beitretbar: {e}")
        s.settimeout(1.0)
        self.ssdp_note = "Suchkanal (UDP %d) offen%s" % (self.ssdp_port, ", Multicast-Gruppe beigetreten" if self.multicast else "")
        self._sock = s
        t = threading.Thread(target=self._ssdp_loop, args=(s,), daemon=True, name="alexa-ssdp")
        t.start()
        self._threads.append(t)

    def _ssdp_loop(self, s):
        while not self._stop.is_set():
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                text = data.decode("utf-8", "ignore")
                if not text.upper().startswith("M-SEARCH"):
                    continue
                st = ""
                for line in text.split("\r\n"):
                    if line.upper().startswith("ST:"):
                        st = line.split(":", 1)[1].strip()
                low = st.lower()
                answered = low in ("ssdp:all", "upnp:rootdevice", "urn:schemas-upnp-org:device:basic:1") or "basic:1" in low
                if not answered:
                    self.foreign += 1                   # Suchen anderer Geraete (DIAL, FRITZ!Box ...) - nur zaehlen, damit die Liste uebersichtlich bleibt
                    continue
                self.note("SSDP", addr[0], f"Suche nach {st or '?'} – beantwortet")
                self.last_ssdp = time.time()
                for reply_st in ({st} if low != "ssdp:all" else {"upnp:rootdevice", "urn:schemas-upnp-org:device:basic:1"}):
                    s.sendto(self._ssdp_reply(addr[0], reply_st).encode("utf-8"), addr)
            except Exception as e:                      # noqa: BLE001
                log.debug("SSDP: %s", e)

    def _ssdp_reply(self, peer_ip: str, st: str) -> str:
        serial = self.serial
        ip = self.bind_ip
        if not ip:
            try:
                u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                u.connect((peer_ip, 1))
                ip = u.getsockname()[0]
                u.close()
            except OSError:
                ip = "127.0.0.1"
        return ("HTTP/1.1 200 OK\r\nEXT:\r\nCACHE-CONTROL: max-age=100\r\n"
                f"LOCATION: http://{ip}:{self.public_port or self.http_port}/description.xml\r\n"
                "SERVER: Linux/3.14.0 UPnP/1.0 IpBridge/1.24.0\r\n"
                f"hue-bridgeid: {_bridge_id(serial)}\r\n"
                f"ST: {st}\r\nUSN: uuid:2f402f80-da50-11e1-9b23-{serial}::{st}\r\n\r\n")

    def status(self) -> dict:
        return {"running": self.running, "error": self.error, "bind_ip": self.bind_ip, "bridge_id": _bridge_id(self.serial), "port": self.http_port, "public_port": self.public_port or self.http_port, "seen": self.seen,
                "last_seen": self.last_seen or None, "last_ssdp": self.last_ssdp or None, "last_cmd": self.last_cmd,
                "ssdp_note": self.ssdp_note, "foreign": self.foreign, "events": list(reversed(self.events[-25:]))}
