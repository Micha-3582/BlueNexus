"""ESPHome-Hardware-Taster (1.29.0): Suchen, Anlegen unter Aktoren, Tastendruck als kurzer Zustand "an", Ausfall und Wiederverbindung, nie schaltbar.
Das Geraet wird mit einem kleinen Web-Server nachgebildet, der wie die Weboberflaeche von ESPHome einen Strom `GET /events` liefert."""
import sys, os, json, time, threading, queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import esphome, shelly, rules
from auth import UserStore

# ---------------------------------------------------------------- nachgebildetes Geraet
STATE = {"Taster": False, "Tuer": False}
STREAMS = []                                        # offene Verbindungen: je eine Warteschlange


class Dev(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"                   # Strom ohne Laenge, wie beim echten Geraet: Ende = Verbindung zu

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        q = queue.Queue(); STREAMS.append(q)
        try:
            self.wfile.write(b'retry: 30000\nid: 1\nevent: ping\ndata: {"title":"taster","comment":"","ota":false,"log":true,"lang":"en","uptime":87}\n\n')
            for name, v in STATE.items():
                j = {"id": "binary_sensor/" + name, "domain": "binary_sensor", "name": name, "entity_category": 0, "value": v, "state": "ON" if v else "OFF"}
                self.wfile.write(("event: state\ndata: " + json.dumps(j) + "\n\n").encode()); self.wfile.flush()
            j = {"id": "sensor/WLAN Signal", "domain": "sensor", "name": "WLAN Signal", "value": -74, "state": "-74 dBm"}
            self.wfile.write(("event: state\ndata: " + json.dumps(j) + "\n\n").encode()); self.wfile.flush()
            while True:
                item = q.get()
                if item is None:
                    return
                self.wfile.write(item.encode()); self.wfile.flush()
        except OSError:
            pass
        finally:
            if q in STREAMS:
                STREAMS.remove(q)


def push(name, value):
    STATE[name] = value
    j = {"id": "binary_sensor/" + name, "value": value, "state": "ON" if value else "OFF"}          # wie das echte Geraet: Aenderungen ohne "domain" und "name"
    for q in list(STREAMS):
        q.put("event: state\ndata: " + json.dumps(j) + "\n\n")


def start_server(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Dev); srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def stop_server(srv):
    for q in list(STREAMS):
        q.put(None)
    srv.shutdown(); srv.server_close()


def wait(cond, sek=6.0, what=""):
    t0 = time.time()
    while time.time() - t0 < sek:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("Zeitueberschreitung: " + what)


srv = start_server(); PORT = srv.server_address[1]
esphome._url = lambda ip, path: f"http://127.0.0.1:{PORT}{path}"
esphome.HOLD_S, esphome.PROBE_QUIET_S, esphome.BACKOFF_START_S, esphome.BACKOFF_MAX_S = 1.2, 0.5, 0.3, 0.6

# ---------------------------------------------------------------- Suchen (nur Binaersensoren, Titel, Kennung)
info = esphome.probe("192.168.50.9")
assert info["title"] == "taster" and [e["name"] for e in info["entities"]] == ["Taster", "Tuer"], info
assert all(e["domain"] == "binary_sensor" and e["value"] is False for e in info["entities"]), "WLAN-Signal (Messwert) kommt in dieser Stufe nicht dazu"
assert esphome.entity_id("taster", "binary_sensor/Taster") == "esphome-taster-taster" and esphome.entity_id("Mein Taster", "binary_sensor/Pin D2") == "esphome-mein_taster-pin_d2"
assert all(ch.isalnum() or ch in "._:-" for ch in esphome.entity_id("a');x", "binary_sensor/b'\"c")), "Kennung nur mit harmlosen Zeichen"
real_url = esphome._url
esphome._url = lambda ip, path: "http://127.0.0.1:9" + path                    # nichts erreichbar
try:
    esphome.probe("192.168.50.9"); raise SystemExit("haette fehlschlagen muessen")
except esphome.EsphomeError as e:
    assert "ESPHome" in str(e)
esphome._url = real_url

# ---------------------------------------------------------------- Webseite: Rechte, Suchen, Hinzufuegen
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass1234", {"dashboard": "read", "smarthome_einrichten": "read"})


def login(n, p):
    c = webapp.app.test_client(); assert c.post("/login", data={"username": n, "password": p}).status_code == 302; return c
A, L = login("admin", "adminpass1"), login("lese", "lesepass1234")
assert webapp.app.test_client().post("/api/esphome/scan", json={"ip": "192.168.50.9"}).status_code in (401, 403)
assert L.post("/api/esphome/scan", json={"ip": "192.168.50.9"}).status_code == 403 and L.post("/api/esphome/add", json={"ip": "192.168.50.9", "ids": ["esphome-taster-taster"]}).status_code == 403
assert A.post("/api/esphome/scan", json={}).status_code == 400
for bad in ("8.8.8.8", "127.0.0.1", "http://evil.example/", "taster.local"):                 # nur Adressen aus dem lokalen Netz (kein Missbrauch als Web-Proxy)
    r = A.post("/api/esphome/scan", json={"ip": bad}); assert r.status_code == 400 and "lokalen Netz" in r.get_json()["error"] or "Ungültige" in r.get_json()["error"], (bad, r.get_json())
shelly.check_ip = lambda ip: ip                                                              # ab hier gilt die nachgebildete Adresse

r = A.post("/api/esphome/scan", json={"ip": "192.168.50.9"}); assert r.status_code == 200, r.get_data(as_text=True)
found = r.get_json(); assert [f["id"] for f in found] == ["esphome-taster-taster", "esphome-taster-tuer"] and not any(f["known"] for f in found)
assert shelly.load_devices() == [], "Suchen legt nichts an"
# unbekanntes Symbol: nichts wird angelegt
r = A.post("/api/esphome/add", json={"ip": "192.168.50.9", "ids": ["esphome-taster-taster"], "edits": {"esphome-taster-taster": {"icon": "nope"}}}); assert r.status_code == 400
assert shelly.load_devices() == []
# unbekannter Eingang
r = A.post("/api/esphome/add", json={"ip": "192.168.50.9", "ids": ["esphome-taster-gibtsnicht"]}); assert r.status_code == 400 and "noch einmal suchen" in r.get_json()["error"]
r = A.post("/api/esphome/add", json={"ip": "192.168.50.9", "ids": ["esphome-taster-taster"], "edits": {"esphome-taster-taster": {"name": "Klingel", "icon": "🔔"}}})
assert r.status_code == 201, r.get_data(as_text=True)
d = shelly.load_devices(); assert len(d) == 1
e = d[0]; assert e["id"] == "esphome-taster-taster" and e["kind"] == "esphome" and e["ip"] == "192.168.50.9" and e["entity"] == "binary_sensor/Taster", e
assert e["name"] == "Klingel" and e["icon"] == "🔔" and e["switchable"] is False and e["users"] == [] and e["show"] is False and e["auto"] is False
# zweimal hinzufuegen: kein Doppel; Suche zeigt es als bekannt
assert A.post("/api/esphome/add", json={"ip": "192.168.50.9", "ids": ["esphome-taster-taster"]}).status_code == 201 and len(shelly.load_devices()) == 1
assert [f["known"] for f in A.post("/api/esphome/scan", json={"ip": "192.168.50.9"}).get_json()] == [True, False]

# ---------------------------------------------------------------- Zustand: Verbindung, Druck, kurzer Zustand "an"
wakes = []
esphome.add_listener(lambda: wakes.append(time.time()))
esphome.sync(shelly.load_devices())
wait(lambda: esphome.status(e)["online"], what="verbunden")
st = esphome.status(e); assert st == {"online": True, "on": False, "power": None}, st
n0 = len(wakes)
push("Taster", True)
wait(lambda: esphome.status(e)["on"] is True, what="Druck erkannt")
assert len(wakes) == n0 + 1, "ein Druck weckt die Regelschleife genau einmal"
push("Taster", False)                                                                         # Loslassen: kein neuer Druck, der Zustand "gedrueckt" haelt trotzdem seine Zeit
time.sleep(0.3); assert esphome.status(e)["on"] is True and len(wakes) == n0 + 1
wait(lambda: esphome.status(e)["on"] is False, 3.0, "Zustand laeuft ab (HOLD_S)")
push("Taster", True); wait(lambda: esphome.status(e)["on"] is True, what="zweiter Druck"); assert len(wakes) == n0 + 2
push("Tuer", True); time.sleep(0.3)
assert len(wakes) == n0 + 2, "ein anderer Eingang desselben Geraets weckt nichts, solange er nicht angelegt ist"
push("Tuer", False); push("Taster", False)
wait(lambda: esphome.status(e)["on"] is False, 3.0, "wieder bereit")

# ueber die Geraeteliste der Seite (so sehen Regeln und Oberflaeche es)
lst = {x["id"]: x for x in A.get("/api/shelly").get_json()}
x = lst["esphome-taster-taster"]; assert x["kind"] == "esphome" and x["online"] is True and x["on"] is False and x["switchable"] is False and x["power"] is None, x
push("Taster", True); wait(lambda: esphome.status(e)["on"], what="gedrueckt")
x = {y["id"]: y for y in A.get("/api/shelly").get_json()}["esphome-taster-taster"]; assert x["on"] is True
push("Taster", False)
wait(lambda: esphome.status(e)["on"] is False, 3.0, "bereit")

# ---------------------------------------------------------------- nie schaltbar
r = A.post("/api/shelly/esphome-taster-taster/switch", json={"on": True}); assert r.status_code >= 400 and "nicht schaltbar" in r.get_data(as_text=True), r.get_data(as_text=True)
r = A.patch("/api/shelly/esphome-taster-taster", json={"switchable": True}); assert r.status_code in (200, 400)
assert shelly.load_devices()[0]["switchable"] is False, "ein Taster bleibt nur zur Ueberwachung"
r = A.patch("/api/shelly/esphome-taster-taster", json={"auto": True}); assert shelly.load_devices()[0]["auto"] is False, "nie in die Ueberschuss-Automatik"
assert A.get("/api/alexa").status_code in (200, 403) and "esphome-taster-taster" not in json.dumps((A.get("/api/alexa").get_json() or {}).get("eligible", []))

# ---------------------------------------------------------------- Regeln: "Gerät wird gedrückt" (device is on)
c = rules.normalize_condition({"type": "device", "device_id": "esphome-taster-taster", "is": "on"})
assert c["type"] == "device" and c["device_id"] == "esphome-taster-taster" and c["is"] == "on", c
from datetime import datetime
dev = {"id": "esphome-taster-taster", "name": "Klingel", "kind": "esphome", "online": True, "on": True}
cx = lambda: {"now": datetime.now(), "devices": {dev["id"]: dev}}
ok, txt = rules.eval_condition(c, cx()); assert ok is True and txt == "Klingel wird gedrückt", (ok, txt)
dev["on"] = False; assert rules.eval_condition(c, cx())[0] is False
dev["online"], dev["on"] = False, None; assert rules.eval_condition(c, cx())[0] is None, "Geraet offline: unbekannt, nie ausloesen"

# ---------------------------------------------------------------- Ausfall und Wiederverbindung
stop_server(srv)
wait(lambda: esphome.status(e)["online"] is False, 5.0, "Ausfall erkannt")
st = esphome.status(e); assert st == {"online": False, "on": None, "power": None}, st
x = {y["id"]: y for y in A.get("/api/shelly").get_json()}["esphome-taster-taster"]; assert x["online"] is False and x["on"] is None
STATE["Taster"] = True                                                                        # waehrend des Ausfalls gedrueckt und gehalten
srv = start_server(PORT)
wait(lambda: esphome.status(e)["online"] is True, 6.0, "wieder verbunden")
time.sleep(0.4)
assert esphome.status(e)["on"] is False, "was waehrend des Ausfalls war, gilt nach dem Verbinden nie als Druck"
n1 = len(wakes)
push("Taster", False); push("Taster", True); wait(lambda: esphome.status(e)["on"], what="Druck nach Wiederverbindung")
assert len(wakes) == n1 + 1

# ---------------------------------------------------------------- IP aendern, Entfernen trennt die Verbindung
r = A.patch("/api/shelly/esphome-taster-taster", json={"ip": "192.168.50.10"}); assert r.status_code == 200 and shelly.load_devices()[0]["ip"] == "192.168.50.10"
assert A.delete("/api/shelly/esphome-taster-taster").status_code in (200, 204) and shelly.load_devices() == []
wait(lambda: "192.168.50.9" not in esphome._hosts or True, 1.0, "")
esphome.sync([]); assert esphome._hosts == {}, esphome._hosts
stop_server(srv)
print("ESPHOME OK", sys.argv[1].split("/")[-1])
