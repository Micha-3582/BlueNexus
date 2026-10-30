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
SENSORS = {"Temperatur": (21.5, "°C"), "Luftfeuchte": (48.0, "%"), "Akku": (87.0, "%"), "CO2": (612.0, "ppm"), "Druck": (1008.0, "hPa"),
           "Leistung": (12.0, "W"), "Temp F": (70.0, "°F"), "Druck kPa": (101.3, "kPa"), "WLAN Signal": (-74.0, "dBm")}
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
            for name, (v, uom) in SENSORS.items():
                j = {"id": "sensor/" + name, "domain": "sensor", "name": name, "entity_category": 0, "value": v, "state": "%s %s" % (v, uom), "uom": uom}
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


def push_sensor(name, value):
    SENSORS[name] = (value, SENSORS[name][1])
    j = {"id": "sensor/" + name, "value": value, "state": str(value)}
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
esphome.DISPLAY_S, esphome.PROBE_QUIET_S, esphome.BACKOFF_START_S, esphome.BACKOFF_MAX_S = 1.2, 0.5, 0.3, 0.6

# ---------------------------------------------------------------- Suchen (nur Binaersensoren, Titel, Kennung)
info = esphome.probe("192.168.50.9")
assert info["title"] == "taster" and [e["name"] for e in info["entities"] if e["domain"] == "binary_sensor"] == ["Taster", "Tuer"], info
assert all(e["value"] is False for e in info["entities"] if e["domain"] == "binary_sensor")
assert {e["name"]: e["uom"] for e in info["entities"] if e["domain"] == "sensor"}["Temperatur"] == "°C"
assert esphome.entity_id("taster", "binary_sensor/Taster") == "esphome-taster-taster" and esphome.entity_id("Mein Taster", "binary_sensor/Pin D2") == "esphome-mein_taster-pin_d2"
assert all(ch.isalnum() or ch in "._:-" for ch in esphome.entity_id("a');x", "binary_sensor/b'\"c")), "Kennung nur mit harmlosen Zeichen"
real_url = esphome._url
esphome._url = lambda ip, path: "http://127.0.0.1:9" + path                    # nichts erreichbar
try:
    esphome.probe("192.168.50.9"); raise SystemExit("haette fehlschlagen muessen")
except esphome.EsphomeError as e:
    assert "ESPHome" in str(e)
esphome._url = real_url

# ---------------------------------------------------------------- Einheiten -> Sensorarten
sk = esphome.sensor_kind
assert sk("°C", "x") == ("temperature", "°C", None) and sk("°F", "x") == ("temperature", "°C", "f2c") and sk("hPa", "x") == ("pressure", "hPa", None)
assert sk("%", "Luftfeuchte") == ("humidity", "%", None) and sk("%", "Relative humidity")[0] == "humidity"
assert sk("%", "Akku") is None and sk("%", "Bodenfeuchte")[0] == "humidity" and sk("ppm", "CO2") is None and sk("", "x") is None and sk("W", "x")[0] == "power"
assert sk("dB", "WLAN") == ("signal", "dBm", None) and sk("V", "Akku")[0] == "voltage" and sk("lx", "Licht")[0] == "brightness"
assert abs(esphome._CONV["f2c"](70.0) - 21.11) < 0.01 and esphome._CONV["x10"](101.3) == 1013.0 and esphome._CONV["k"](1.5) == 1500.0
assert esphome._num(None) is None and esphome._num("NaN") is None and esphome._num(float("inf")) is None and esphome._num(True) is None and esphome._num("3.5") == 3.5
assert esphome.sensor_id("taster", "sensor/Temperatur") == "espS-taster-temperatur"

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
st = esphome.status(e); assert st == {"online": True, "on": False, "power": None, "shown": False}, st
def rules_pass():
    """So arbeitet eine Runde der Regelschleife: Stand merken, Zustand lesen, am Ende die gesehenen Druecke beenden."""
    snap = esphome.seqs(); on = esphome.status(e)["on"]; esphome.consume(snap); return on


n0 = len(wakes)
push("Taster", True)
wait(lambda: esphome.status(e)["on"] is True, what="Druck erkannt")
assert len(wakes) == n0 + 1, "ein Druck weckt die Regelschleife genau einmal"
assert esphome.status(e)["shown"] is True
push("Taster", False)                                                                         # Loslassen: kein neuer Druck; der Impuls wartet, bis die Regeln ihn gesehen haben
time.sleep(0.3); assert esphome.status(e)["on"] is True and len(wakes) == n0 + 1
assert rules_pass() is True and rules_pass() is False, "genau eine Runde lang an, dann wieder aus"
assert esphome.status(e)["shown"] is True, "die Anzeige haelt noch kurz"
wait(lambda: esphome.status(e)["shown"] is False, 3.0, "Anzeige laeuft ab (DISPLAY_S)")


def presses(n):
    for _ in range(n):
        k = esphome._state[("192.168.50.9", "binary_sensor/Taster")]["seq"]
        push("Taster", True); wait(lambda: esphome._state[("192.168.50.9", "binary_sensor/Taster")]["seq"] == k + 1, what="Druck eingegangen")
        push("Taster", False); time.sleep(0.05)


# Druecke mit Runden dazwischen: jeder Druck ist ein eigener Impuls
for _ in range(3):
    presses(1); assert rules_pass() is True and rules_pass() is False
# schnell aufeinanderfolgende Druecke VOR der naechsten Runde: jeder wird einzeln gesehen (an, Luecke, an, Luecke ...), und die Regeln werden dafuer erneut geweckt
w0 = len(wakes); presses(3)
assert len(wakes) == w0 + 3
seen = [rules_pass() for _ in range(6)]
assert seen == [True, False, True, False, True, False], seen
assert len(wakes) >= w0 + 3 + 2, "waehrend wartende Druecke uebrig sind, weckt das Ende einer Runde die Regeln wieder"
# ein Druck waehrend einer laufenden Runde geht nicht verloren
presses(1); snap = esphome.seqs(); assert esphome.status(e)["on"] is True
presses(1)                                                                                    # kommt mitten in der Runde
esphome.consume(snap)
assert [rules_pass() for _ in range(3)] == [False, True, False], "zweiter Druck: erst eine Luecke, dann an"

# Ablauf-Regel "WENN Taster gedrueckt": jeder schnelle Druck startet genau einen Ablauf (so wie die Regelschleife die Runden fuehrt)
import flows
from datetime import datetime
body = {"name": "Klingel", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "device", "device_id": e["id"], "is": "on"}]},
        "then": [{"device_id": "a", "state": "on"}], "else": []}
fr = rules.normalize_rule(body, "t1")
flows.STATE_PATH = os.path.join(tmp, "fs2.json"); eng = flows.FlowEngine()
tick = [1000.0]


def flow_pass():
    snap = esphome.seqs(); st = esphome.status(e); now = datetime(2026, 10, 30, 12, 0)
    ctx = {"now": now, "devices": {e["id"]: {"id": e["id"], "name": "Klingel", "kind": "esphome", "online": True, "on": st["on"]}}}
    ev = [x[0] for x in eng.step(now, ctx, [fr])]
    tick[0] += 10; eng.advance(tick[0]); esphome.consume(snap)
    return ev.count("start")


assert sum(flow_pass() for _ in range(3)) == 0, "ohne Druck startet nichts"
presses(1); assert [flow_pass() for _ in range(3)] == [1, 0, 0], "ein Druck, ein Ablauf"
presses(3)
starts = [flow_pass() for _ in range(8)]
assert sum(starts) == 3, ("drei schnelle Druecke, drei Ablaeufe", starts)
assert sum(flow_pass() for _ in range(3)) == 0, "danach ist Ruhe"
n0 = len(wakes) - 1                                                                           # ab hier zaehlt nur der naechste Block neu
push("Tuer", True); time.sleep(0.3)
assert len(wakes) == n0 + 1, "ein anderer Eingang desselben Geraets weckt nichts, solange er nicht angelegt ist"
push("Tuer", False)
assert esphome.status(e)["on"] is False

# ueber die Geraeteliste der Seite (so sehen Regeln und Oberflaeche es)
lst = {x["id"]: x for x in A.get("/api/shelly").get_json()}
x = lst["esphome-taster-taster"]; assert x["kind"] == "esphome" and x["online"] is True and x["on"] is False and x["switchable"] is False and x["power"] is None, x
push("Taster", True); wait(lambda: esphome.status(e)["on"], what="gedrueckt")
x = {y["id"]: y for y in A.get("/api/shelly").get_json()}["esphome-taster-taster"]; assert x["on"] is True and x["shown"] is True
push("Taster", False); rules_pass(); rules_pass()
x = {y["id"]: y for y in A.get("/api/shelly").get_json()}["esphome-taster-taster"]; assert x["on"] is False

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

# ---------------------------------------------------------------- Messwerte als Sensoren
import homematic
assert L.post("/api/esphome/sensors/scan", json={"ip": "192.168.50.9"}).status_code == 403 and L.post("/api/esphome/sensors/add", json={"ids": ["espS-taster-temperatur"]}).status_code == 403
assert A.post("/api/esphome/sensors/scan", json={}).status_code == 400
r = A.post("/api/esphome/sensors/scan", json={"ip": "192.168.50.9"}); assert r.status_code == 200, r.get_data(as_text=True)
fs = {f["name"]: f for f in r.get_json()}
assert set(fs) == {"Temperatur", "Luftfeuchte", "Druck", "Leistung", "Temp F", "Druck kPa", "WLAN Signal"}, set(fs)      # Akku (%) und CO2 (ppm) gibt es nicht als Art, Taster sind keine Messwerte
assert all(f["skipped"] == 2 and f["known"] is False for f in fs.values())
assert fs["Temperatur"]["kind"] == "temperature" and fs["Temperatur"]["value"] == 21.5 and fs["Temperatur"]["unit"] == "°C" and fs["Luftfeuchte"]["kind"] == "humidity"
assert fs["Temp F"]["value"] == 21.1 and fs["Temp F"]["conv"] == "f2c" and fs["Druck kPa"]["value"] == 1013.0 and fs["Leistung"]["unit"] == "W" and fs["WLAN Signal"]["kind"] == "signal"
assert homematic.load_sensors() == [], "Suchen legt nichts an"
r = A.post("/api/esphome/sensors/add", json={"ids": ["espS-taster-gibtsnicht"]}); assert r.status_code == 400 and "neu suchen" in r.get_json()["error"]
r = A.post("/api/esphome/sensors/add", json={"ids": ["espS-taster-temperatur"], "edits": {"espS-taster-temperatur": {"icon": ""}}}); assert r.status_code == 400
r = A.post("/api/esphome/sensors/add", json={"ids": ["espS-taster-temperatur", "espS-taster-luftfeuchte", "espS-taster-temp_f", "espS-taster-druck_kpa"],
                                              "edits": {"espS-taster-temperatur": {"name": "Flur Temperatur", "icon": "🌡️"}}})
assert r.status_code == 201 and r.get_json()["added"] == 4, r.get_data(as_text=True)
sens = {x["id"]: x for x in homematic.load_sensors()}
t1 = sens["espS-taster-temperatur"]
assert t1["source"] == "esphome" and t1["kind"] == "temperature" and t1["name"] == "Flur Temperatur" and t1["datapoint"] == "sensor/Temperatur" and t1["ip"] == "192.168.50.9" and t1["users"] == [] and t1["binary"] is False, t1
assert sens["espS-taster-temp_f"]["conv"] == "f2c" and "conv" not in t1
assert A.post("/api/esphome/sensors/scan", json={"ip": "192.168.50.9"}).get_json() and [f["known"] for f in A.post("/api/esphome/sensors/scan", json={"ip": "192.168.50.9"}).get_json() if f["name"] == "Temperatur"] == [True]
rd = lambda sid: (homematic._value_cache.clear(), homematic._read_sensor_now(sens[sid]))[1]
wait(lambda: rd("espS-taster-temperatur") == 21.5, 6.0, "Messwert gelesen")
assert rd("espS-taster-luftfeuchte") == 48.0 and rd("espS-taster-temp_f") == 21.1 and rd("espS-taster-druck_kpa") == 1013.0
push_sensor("Temperatur", 22.34); wait(lambda: rd("espS-taster-temperatur") == 22.3, 3.0, "Aenderung (ohne domain) uebernommen")
push_sensor("Temp F", 68.0); wait(lambda: rd("espS-taster-temp_f") == 20.0, 3.0, "Fahrenheit umgerechnet")
push_sensor("Luftfeuchte", None); wait(lambda: rd("espS-taster-luftfeuchte") is None, 3.0, "fehlender Wert (null) = nicht lesbar")
j = A.get("/api/sensors"); assert j.status_code == 200
assert "espS-taster-temperatur" in json.dumps(j.get_json()), "erscheint in der Sensorliste"
assert "WLAN Signal" not in json.dumps(j.get_json()), "nicht angelegte Messwerte erscheinen nicht"

pg = A.get("/smarthome").get_data(as_text=True)
assert "esphome-sensor-scan" in pg and "/api/esphome/sensors/scan" in pg and "Messwerte suchen" in pg, "die Seite bietet die Messwert-Suche an"

# ein nicht angelegter Messwert wird nicht mitgefuehrt
assert ("192.168.50.9", "sensor/WLAN Signal") not in esphome._values

# ---------------------------------------------------------------- Ausfall und Wiederverbindung
stop_server(srv)
wait(lambda: esphome.status(e)["online"] is False, 5.0, "Ausfall erkannt")
st = esphome.status(e); assert st == {"online": False, "on": None, "power": None, "shown": False}, st
x = {y["id"]: y for y in A.get("/api/shelly").get_json()}["esphome-taster-taster"]; assert x["online"] is False and x["on"] is None
assert rd("espS-taster-temperatur") == 22.3, "kurzer Ausfall: der letzte Messwert gilt noch (Schonfrist)"
esphome.VALUE_GRACE_S = 0.2; time.sleep(0.4)
assert rd("espS-taster-temperatur") is None, "nach der Schonfrist: nicht lesbar"
esphome.VALUE_GRACE_S = 120.0
STATE["Taster"] = True                                                                        # waehrend des Ausfalls gedrueckt und gehalten
srv = start_server(PORT)
wait(lambda: esphome.status(e)["online"] is True, 6.0, "wieder verbunden")
time.sleep(0.4)
assert esphome.status(e)["on"] is False, "was waehrend des Ausfalls war, gilt nach dem Verbinden nie als Druck"
wait(lambda: rd("espS-taster-temperatur") == 22.3, 6.0, "Messwert nach Wiederverbindung wieder da (Anfangszustand)")
n1 = len(wakes)
push("Taster", False); push("Taster", True); wait(lambda: esphome.status(e)["on"], what="Druck nach Wiederverbindung")
assert len(wakes) == n1 + 1

# ---------------------------------------------------------------- IP aendern: erneutes Suchen unter der neuen Adresse zieht Taster und Messwerte um
r = A.post("/api/esphome/scan", json={"ip": "192.168.50.77"}); assert r.status_code == 200
assert shelly.load_devices()[0]["ip"] == "192.168.50.77", "der Taster folgt der neuen Adresse"
r = A.post("/api/esphome/sensors/scan", json={"ip": "192.168.50.77"}); assert r.status_code == 200
assert all(x["ip"] == "192.168.50.77" for x in homematic.load_sensors() if x["source"] == "esphome"), "die Messwerte folgen"
wait(lambda: "192.168.50.9" not in esphome._hosts and "192.168.50.77" in esphome._hosts, 3.0, "Verbindung zieht auf die neue Adresse um")
shelly.update("esphome-taster-taster", ip="192.168.50.9"); esphome.resync()

# ---------------------------------------------------------------- IP aendern, Entfernen trennt die Verbindung
r = A.patch("/api/shelly/esphome-taster-taster", json={"ip": "192.168.50.10"}); assert r.status_code == 200 and shelly.load_devices()[0]["ip"] == "192.168.50.10"
assert A.delete("/api/shelly/esphome-taster-taster").status_code in (200, 204) and shelly.load_devices() == []
wait(lambda: "192.168.50.9" not in esphome._hosts or True, 1.0, "")
for sid in list(sens):                                                                        # auch die Messwerte entfernen: danach haelt BlueNexus keine Verbindung mehr
    homematic._save_sensors([x for x in homematic.load_sensors() if x["id"] != sid])
esphome.resync(); assert esphome._hosts == {}, esphome._hosts
stop_server(srv)
print("ESPHOME OK", sys.argv[1].split("/")[-1])
