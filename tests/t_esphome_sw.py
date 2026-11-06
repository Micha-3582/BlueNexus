"""ESPHome-Schalter/Relais (1.37.0): Das Geraet wird dem ersten Relais aus dem ESPHome-Baukasten nachgebildet (alte Kennung "switch/Relais",
ohne api, mit IP-Textsensor). Prueft: Suchen, Anlegen als schaltbarer Aktor (esphome_sw), Zustand, Schalten (an/aus), Schalten am Geraet selbst,
Befehl ohne Antwort (kommt trotzdem an / kommt nicht an), Ausfall."""
import sys, os, json, time, threading, queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import esphome, shelly

STATE = {"on": False}
STREAMS, POSTS = [], []
DROP = {"n": 0, "apply": False}


def state_json():
    return {"id": "switch/Relais", "domain": "switch", "name": "Relais", "entity_category": 0, "value": STATE["on"], "state": "ON" if STATE["on"] else "OFF", "assumed_state": False}


def push(j):
    for s in list(STREAMS):
        s.put("event: state\ndata: " + json.dumps(j) + "\n\n")


class Dev(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        POSTS.append(self.path)
        if self.path not in ("/switch/Relais/turn_on", "/switch/Relais/turn_off"):
            self.send_response(404); self.end_headers(); return
        drop = DROP["n"] > 0
        if drop:
            DROP["n"] -= 1
        if drop and not DROP["apply"]:
            return                                                       # Verbindung ohne Antwort schliessen, Befehl kommt nicht an
        STATE["on"] = self.path.endswith("turn_on")
        push(state_json())
        if drop:
            return
        self.send_response(200); self.end_headers()

    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        q = queue.Queue(); STREAMS.append(q)
        try:
            self.wfile.write(b'retry: 30000\nid: 1\nevent: ping\ndata: {"title":"3d_drucker_aktor","comment":"","ota":false,"log":false,"lang":"en","uptime":90}\n\n')
            for j in ({"id": "sensor/WLAN Signal", "domain": "sensor", "name": "WLAN Signal", "entity_category": 2, "value": -65, "state": "-65 dBm", "uom": "dBm"},
                      state_json(),
                      {"id": "text_sensor/IP-Adresse", "domain": "text_sensor", "name": "IP-Adresse", "entity_category": 2, "value": "192.168.2.129", "state": "192.168.2.129"}):
                self.wfile.write(("event: state\ndata: " + json.dumps(j) + "\n\n").encode("utf-8")); self.wfile.flush()
            while True:
                item = q.get()
                if item is None:
                    return
                self.wfile.write(item.encode("utf-8")); self.wfile.flush()
        except OSError:
            pass
        finally:
            if q in STREAMS:
                STREAMS.remove(q)


def wait(cond, sek=6.0, what=""):
    t0 = time.time()
    while time.time() - t0 < sek:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("Zeitueberschreitung: " + what)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Dev); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
esphome._url = lambda ip, path: f"http://127.0.0.1:{PORT}{path}"
esphome.PROBE_QUIET_S, esphome.BACKOFF_START_S, esphome.BACKOFF_MAX_S, esphome.SWITCH_WAIT_S = 0.5, 0.3, 0.6, 1.0

# ---------------------------------------------------------------- Suchen
found = shelly.esphome_scan("192.168.2.129")
assert [f["entity"] for f in found] == ["switch/Relais"], found                       # Messwerte stehen bei "Messwerte suchen"
assert found[0]["icon"] == "🔌" and found[0]["domain"] == "switch" and found[0]["known"] is False, found
dev_id = found[0]["id"]

# ---------------------------------------------------------------- Anlegen
added = shelly.add_esphome("192.168.2.129", [dev_id])
assert len(added) == 1 and added[0]["kind"] == "esphome_sw" and added[0]["switchable"] is True and added[0]["icon"] == "🔌" and "rkind" not in added[0], added
d = shelly.load_devices()[0]
assert shelly.add_esphome("192.168.2.129", [dev_id]) == [], "nicht doppelt anlegen"
assert shelly.esphome_scan("192.168.2.129")[0]["known"] is True

# ---------------------------------------------------------------- Zustand
wait(lambda: shelly.status(d).get("online"), 6.0, "Zustand da")
st = shelly.status(d)
assert st["on"] is False and st["online"] is True and st["power"] is None, st
assert shelly.status_cached(d)["on"] is False

# ---------------------------------------------------------------- Schalten
POSTS.clear()
r = shelly.set_state(dev_id, True)
assert POSTS == ["/switch/Relais/turn_on"] and r["on"] is True and STATE["on"] is True, (POSTS, r)
POSTS.clear()
r = shelly.set_state(dev_id, False)
assert POSTS == ["/switch/Relais/turn_off"] and r["on"] is False and STATE["on"] is False, (POSTS, r)

# am Geraet selbst geschaltet (Taste, Weboberflaeche): BlueNexus folgt ohne Abfrage
STATE["on"] = True; push(state_json())
wait(lambda: shelly.status(d).get("on") is True, 3.0, "Schalten am Geraet wird gemeldet")
STATE["on"] = False; push(state_json())
wait(lambda: shelly.status(d).get("on") is False, 3.0, "und wieder aus")

# ---------------------------------------------------------------- Befehl ohne Antwort
DROP.update(n=1, apply=True)                         # Geraet fuehrt aus, antwortet aber nicht: kein Fehler
r = shelly.set_state(dev_id, True)
assert r["on"] is True and STATE["on"] is True, r
DROP.update(n=1, apply=False)                        # Befehl kommt nicht an: zweiter Versuch klappt
POSTS.clear()
r = shelly.set_state(dev_id, False)
assert r["on"] is False and STATE["on"] is False and len(POSTS) == 2, (POSTS, r)
DROP.update(n=99, apply=False)                       # nimmt nichts mehr an: klare Fehlermeldung
try:
    shelly.set_state(dev_id, True); raise AssertionError("ohne Antwort muss ein Fehler kommen")
except shelly.ShellyError as e:
    assert "nicht angenommen" in str(e), e
DROP.update(n=0)
assert shelly.status(d)["on"] is False

# ---------------------------------------------------------------- Ausfall
for s in list(STREAMS):
    s.put(None)
srv.shutdown(); srv.server_close()
esphome._url = lambda ip, path: "http://127.0.0.1:1" + path
wait(lambda: shelly.status(d).get("online") is True and shelly.status(d).get("on") is False, 3.0, "kurzer Abbruch: letzter Zustand gilt noch")
try:
    shelly.set_state(dev_id, True); raise AssertionError("offline darf nicht schalten")
except shelly.ShellyError:
    pass
print("ok")
