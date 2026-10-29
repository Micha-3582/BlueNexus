"""Reolink-Bewegung/KI als Sensoren: Suche, Anlegen, Werte, Regeln, Fehlerfaelle, Kamera loeschen."""
import sys, os, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, homematic, rules
from auth import UserStore

camera.CAMERAS_PATH = os.path.join(tmp, "cameras_m.json")
homematic.SENSORS_PATH = os.path.join(tmp, "sensors_m.json")
for p in (camera.CAMERAS_PATH, homematic.SENSORS_PATH):
    if os.path.exists(p):
        os.remove(p)

ST = {"md": 0, "people": 0, "vehicle": 0, "dog_cat": 0, "ai": True, "fail": False}
CALLS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query); n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"[]")
        cmd = q.get("cmd", [""])[0]; CALLS.append(cmd)
        if cmd == "Login":
            return self._json([{"cmd": "Login", "code": 0, "value": {"Token": {"name": "TOK", "leaseTime": 3600}}}])
        if q.get("token", [""])[0] != "TOK":
            return self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -6}}])
        if cmd == "GetDevInfo":
            return self._json([{"cmd": cmd, "code": 0, "value": {"DevInfo": {"name": "Hofkamera", "model": "RLC-810A", "firmVer": "v3"}}}])
        if cmd == "GetMdState":
            assert body[0]["param"] == {"channel": 0}, body
            return self._json([{"cmd": cmd, "code": 0, "value": {"state": ST["md"]}}])
        if cmd == "GetAiState":
            if not ST["ai"]:
                return self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -9}}])
            return self._json([{"cmd": cmd, "code": 0, "value": {"channel": 0, "people": {"alarm_state": ST["people"], "support": 1}, "vehicle": {"alarm_state": ST["vehicle"], "support": 1},
                                                                  "dog_cat": {"alarm_state": ST["dog_cat"], "support": 0}, "face": {"alarm_state": 0, "support": 1},
                                                                  **({"visitor": {"alarm_state": ST.get("visitor", 0), "support": 1}} if ST.get("doorbell") else {})}}])
        self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -9}}])


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
assert camera.MOTION_TTL_S == 0.5
camera.MOTION_TTL_S = 0.0                                   # Test: immer frisch lesen

webapp.users = UserStore(os.path.join(tmp, "users_m.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)

# ohne Kamera: nichts zu finden
assert c.post("/api/cameras/motion/scan").get_json() == []
assert c.get("/api/device-families").get_json()["families"]["camera"] is False

r = c.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "x", "name": "Hof"}); assert r.status_code == 201, r.get_json()
cid = r.get_json()["id"]
assert c.get("/api/device-families").get_json()["families"]["camera"] is True

# 1) Suche: Bewegung + KI (Person, Fahrzeug; Tier nicht unterstuetzt; Gesicht nicht angeboten)
found = c.post("/api/cameras/motion/scan").get_json()
assert {f["name"] for f in found} == {"Hof – Bewegung", "Hof – Person", "Hof – Fahrzeug"}, found
assert all(f["kind"] == "motion" and f["binary"] and f["source"] == "camera" and not f["known"] for f in found)
print("1) Suche OK")

# 2) Anlegen mit Namen/Symbol, Sichtbarkeit nur Admin
ids = [f["id"] for f in found]
r = c.post("/api/cameras/motion/add", json={"ids": ids, "edits": {ids[0]: {"name": "Hof Bewegung", "icon": "🚶"}}}); assert r.status_code == 200, r.get_json()
reg = {s["id"]: s for s in homematic.load_sensors()}
assert len(reg) == 3 and reg[ids[0]]["name"] == "Hof Bewegung" and reg[ids[0]]["users"] == [] and reg[ids[0]]["source"] == "camera"
assert c.post("/api/cameras/motion/add", json={"ids": ids}).get_json()["added"] == []                    # nichts doppelt
assert all(f["known"] for f in c.post("/api/cameras/motion/scan").get_json())
print("2) Anlegen OK")

# 3) Werte
sens = homematic.load_sensors()
vals = homematic.read_values(sens)
assert set(vals.values()) == {False}, vals
ST["md"], ST["people"] = 1, 1; homematic._value_cache.clear()
vals = homematic.read_values(sens)
byname = {s["name"]: vals[s["id"]] for s in sens}
assert byname == {"Hof Bewegung": True, "Hof – Person": True, "Hof – Fahrzeug": False}, byname
n = len(CALLS); camera.MOTION_TTL_S = 5.0; homematic.read_values(sens); homematic._value_cache.clear(); homematic.read_values(sens)
assert len(CALLS) - n <= 2, "alle Sensoren einer Kamera teilen eine Abfrage"
camera.MOTION_TTL_S = 0.0; homematic._value_cache.clear()
api = {s["id"]: s for s in c.get("/api/sensors").get_json()}
assert api[ids[0]]["source"] == "camera"
ST["md"] = 0                                                                              # kein zusaetzlicher Sekunden-Zwischenspeicher: Aenderung sofort sichtbar
assert homematic.read_values(sens)[ids[0]] is False
ST["md"] = 1
assert homematic.read_values(sens)[ids[0]] is True
print("3) Werte OK")

# 4) Kamera ohne KI-Erkennung: Bewegung bleibt, KI-Sensoren unbekannt (None)
ST["ai"] = False; homematic._value_cache.clear()
vals = homematic.read_values(sens)
assert vals[ids[0]] is True and vals[ids[1]] is None and vals[ids[2]] is None, vals
ST["ai"] = True; homematic._value_cache.clear()
print("4) ohne KI OK")

# 5) Regel mit Kamera-Sensor: Kamera darf nicht geloescht werden, solange benutzt
rule = {"name": "Bewegung Hof", "mode": "flow", "enabled": True, "when": {"mode": "all", "conds": [{"type": "sensor", "sensor_id": ids[0], "is": True}]},
        "then": [{"type": "photo", "id": cid}], "else": []}
r = c.post("/api/automation", json={"rules": [rule]}); assert r.status_code == 200, r.get_json()
r = c.delete("/api/cameras/" + cid); assert r.status_code == 409, (r.status_code, r.get_json())
assert camera.get(cid) and len(homematic.load_sensors()) == 3
print("5) Loeschschutz OK")

# 6) Kamera weg (Netz): alle Werte None, kein Absturz
srv.shutdown(); srv.server_close()
homematic._value_cache.clear(); camera._motion_cache.clear()
assert set(homematic.read_values(homematic.load_sensors()).values()) == {None}
print("6) Kamera nicht erreichbar OK")

# 7) Regel entfernt -> Kamera loeschen entfernt ihre Bewegungs-Sensoren mit
assert c.post("/api/automation", json={"rules": []}).status_code == 200
assert c.delete("/api/cameras/" + cid).status_code == 200
assert camera.get(cid) is None and homematic.load_sensors() == []
print("7) Kamera loeschen entfernt Sensoren OK")
print("CAM MOTION OK")
