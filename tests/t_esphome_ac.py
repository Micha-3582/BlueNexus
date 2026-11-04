"""ESPHome-Klimaanlage (1.34.0) und neuere ESPHome-Staende: Kennungen "sensor-name" statt "sensor/Name", Leerzeile zwischen "event:" und "data:",
Einheit als Ersatzzeichen. Das Geraet wird dem echten SLWF-01-Stick (Midea-Stick mit ESPHome) nachgebildet.
Prueft: Suchen, Anlegen als Aktor (esphome_ac, rkind midea), Zustand, Klimafenster (Modi/Luefter/Schwenken), Setzen (Modus, Soll, Luefter, Schwenken, Aus/Ein), Ausfall."""
import sys, os, json, time, threading, queue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import esphome, shelly, rules

CLIMATE = {"id": "climate-air_conditioner", "name": "Air Conditioner", "icon": "", "entity_category": 0,
           "modes": ["OFF", "HEAT_COOL", "COOL", "HEAT", "FAN_ONLY", "DRY"], "fan_modes": ["AUTO", "LOW", "MEDIUM", "HIGH"], "custom_fan_modes": ["silent", "turbo"],
           "swing_modes": ["OFF", "BOTH", "VERTICAL", "HORIZONTAL"], "presets": ["NONE", "BOOST", "ECO", "SLEEP"],
           "mode": "OFF", "max_temp": "30.0", "min_temp": "17.0", "step": 0.5, "fan_mode": "HIGH", "preset": "NONE", "swing_mode": "OFF",
           "current_temperature": "19.0", "target_temperature": "30.0", "state": "30.0"}
SENS = [("sensor-air_conditioner_outdoor_temperature", "Air Conditioner Outdoor Temperature", 10, "�C"),
        ("sensor-air_conditioner_wi-fi_signal", "Air Conditioner Wi-Fi Signal", -58, "dBm"),
        ("sensor-air_conditioner_indoor_humidity", "Air Conditioner Indoor Humidity", 0, "%")]
STREAMS, POSTS = [], []


class Dev(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *a):
        pass

    def do_POST(self):
        u = urlparse(self.path)
        POSTS.append((u.path, {k: v[0] for k, v in parse_qs(u.query).items()}))
        if u.path != "/climate/air_conditioner/set":
            self.send_response(404); self.end_headers(); return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        for k, v in q.items():
            CLIMATE[k] = v
        j = {"id": CLIMATE["id"], **{k: v for k, v in CLIMATE.items() if k in q}, "state": CLIMATE["target_temperature"]}       # Aenderung: nur die geaenderten Felder
        for s in list(STREAMS):
            s.put("event: state\n\ndata: " + json.dumps(j) + "\n\n")
        self.send_response(200); self.end_headers()

    def do_GET(self):
        if self.path != "/events":
            self.send_response(404); self.end_headers(); return
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
        q = queue.Queue(); STREAMS.append(q)
        try:
            # wie das echte Geraet: Leerzeile zwischen "event:" und "data:"
            self.wfile.write(b'retry: 30000\n\nid: 1\n\nevent: ping\n\ndata: {"title":"Air Conditioner 88d226","comment":"","ota":true,"log":true,"lang":"en"}\n\n')
            for sid, name, v, uom in SENS:
                j = {"id": sid, "name": name, "icon": "", "entity_category": 0, "value": v, "state": "%s %s" % (v, uom), "uom": uom}
                self.wfile.write(("event: state\n\ndata: " + json.dumps(j) + "\n\n").encode("utf-8")); self.wfile.flush()
            self.wfile.write(("event: state\n\ndata: " + json.dumps(CLIMATE) + "\n\n").encode()); self.wfile.flush()
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
esphome.PROBE_QUIET_S, esphome.BACKOFF_START_S, esphome.BACKOFF_MAX_S, esphome.SET_WAIT_S = 0.5, 0.3, 0.6, 2.0

# ---------------------------------------------------------------- Kennungen und Parser
assert esphome.split_id("binary_sensor/Taster") == ("binary_sensor", "Taster") and esphome.split_id("sensor-air_conditioner_wi-fi_signal") == ("sensor", "air_conditioner_wi-fi_signal")
assert esphome.split_id("climate-air_conditioner") == ("climate", "air_conditioner")
assert list(esphome._parse_sse(["event: ping", "", 'data: {"a":1}', "", "event: state", "", "data: 2", ""])) == [("ping", '{"a":1}'), ("state", "2")]
assert esphome.sensor_kind("�C", "x")[0] == "temperature" and esphome.sensor_kind("�F", "x")[2] == "f2c"

# ---------------------------------------------------------------- Suchen
info = esphome.probe("192.168.50.9")
assert info["title"] == "Air Conditioner 88d226"
ents = {e["entity"]: e for e in info["entities"]}
assert set(ents) == {"climate-air_conditioner", "sensor-air_conditioner_outdoor_temperature", "sensor-air_conditioner_wi-fi_signal", "sensor-air_conditioner_indoor_humidity"}, set(ents)
assert ents["climate-air_conditioner"]["domain"] == "climate" and ents["sensor-air_conditioner_wi-fi_signal"]["value"] == -58.0

found = shelly.esphome_scan("192.168.50.9")
assert [f["entity"] for f in found] == ["climate-air_conditioner"], found                  # Messwerte stehen bei "Messwerte suchen"
assert found[0]["icon"] == "❄️" and found[0]["domain"] == "climate" and found[0]["known"] is False
dev_id = found[0]["id"]
assert dev_id == "esphome-air_conditioner_88d226-air_conditioner", dev_id

# ---------------------------------------------------------------- Anlegen als Aktor
added = shelly.add_esphome("192.168.50.9", [dev_id])
assert len(added) == 1 and added[0]["kind"] == "esphome_ac" and added[0]["rkind"] == "midea" and added[0]["switchable"] is True and added[0]["icon"] == "❄️", added
d = shelly.load_devices()[0]
assert shelly.add_esphome("192.168.50.9", [dev_id]) == [], "nicht doppelt anlegen"
assert shelly.esphome_scan("192.168.50.9")[0]["known"] is True

# ---------------------------------------------------------------- Zustand (Midea-Format)
wait(lambda: shelly.status(d).get("online"), 6.0, "Zustand da")
st = shelly.status(d)
assert st["on"] is False and st["target_c"] == 30.0 and st["indoor_c"] == 19.0 and st["fan"] == "high" and st["swing"] == "off" and st["mode"] == "cool", st
wait(lambda: shelly.status(d).get("outdoor_c") == 10.0, 3.0, "Aussentemperatur aus dem Messwert (Ersatzzeichen bei der Einheit stoert nicht)")
assert "außen 10 °C" in shelly.status(d)["info"]

# ---------------------------------------------------------------- Klimafenster
det = shelly.midea_details(dev_id)
assert [m["key"] for m in det["modes"]] == ["auto", "cool", "heat", "fan_only", "dry"] and [f["key"] for f in det["fans"]] == ["auto", "low", "medium", "high", "silent", "max"], det
assert [s["key"] for s in det["swings"]] == ["off", "both", "vertical", "horizontal"] and det["min"] == 17.0 and det["max"] == 30.0 and det["step"] == 0.5 and det["supports_eco"] is True
assert det["modes"][1]["label"] == "Kühlen"

# ---------------------------------------------------------------- Setzen
POSTS.clear()
r = shelly.midea_set(dev_id, power=True, mode="heat", target=22.5, fan="low", swing="vertical")
assert POSTS == [("/climate/air_conditioner/set", {"mode": "HEAT", "target_temperature": "22.5", "fan_mode": "LOW", "swing_mode": "VERTICAL"})], POSTS
assert r["on"] is True and r["mode"] == "heat" and r["target_c"] == 22.5 and r["fan"] == "low" and r["swing"] == "vertical", r
POSTS.clear(); r = shelly.midea_set(dev_id, power=False)
assert POSTS[0][1] == {"mode": "OFF"} and r["on"] is False and r["mode"] == "heat" and r["target_c"] == 22.5, (POSTS, r)          # aus: Soll und letzter Modus bleiben sichtbar
POSTS.clear(); shelly.set_state(dev_id, True)
assert POSTS[0][1] == {"mode": "HEAT"}, POSTS                                                                                # einschalten ohne Modus: der zuletzt benutzte
assert shelly.status(d)["on"] is True
POSTS.clear(); shelly.midea_set(dev_id, fan="max")
assert POSTS[0][1] == {"custom_fan_mode": "turbo"}, POSTS
for bad in (dict(target=5), dict(target=40), dict(mode="kaputt"), dict(fan="kaputt"), dict(swing="kaputt"), dict()):
    try:
        shelly.midea_set(dev_id, **bad); raise AssertionError(f"haette abgelehnt werden muessen: {bad}")
    except shelly.ShellyError:
        pass

# ---------------------------------------------------------------- Regelschritt "Klimaanlage einstellen" nimmt das Geraet an
base = {"name": "Klima", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]}, "else": []}
n = rules.normalize_rule({**base, "then": [{"type": "ac", "id": dev_id, "power": "on", "mode": "cool", "target": 24}]}, "k1")["then"][0]
assert n["type"] == "ac" and n["id"] == dev_id

# ---------------------------------------------------------------- Ausfall: nicht erreichbar, Befehl abgelehnt
for q in list(STREAMS):
    q.put(None)
srv.shutdown(); srv.server_close()
esphome.VALUE_GRACE_S = 0.2; time.sleep(0.5)
assert shelly.status(d)["online"] is False
try:
    shelly.midea_set(dev_id, power=True); raise AssertionError("Geraet weg: muss scheitern")
except shelly.ShellyError as e:
    assert "antwortet nicht" in str(e), e
print("t_esphome_ac OK")
