import sys, os, time, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_rep.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"}); N = webapp.app.test_client()
webapp.too_many_attempts = lambda k: False
sys.path.insert(0, "K:/Claude Projekte/BlueNexus-Thermometer/tools"); import make_cfg
W = {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}
c = A.post("/api/thermo", json={"name": "Außen", "interval": 15, "wifi": W}).get_json()
tid, old = c["device"]["id"], c["token"]
H = lambda t: {"Authorization": "Bearer " + t}
body = {"temp": 20, "hum": 50, "bat": 3.0}
assert N.post("/api/sensor/" + tid, json=body, headers=H(old)).status_code == 200
A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": 19.5})
sens_before = sorted(s["id"] for s in homematic.load_sensors() if s.get("source") == "thermo")
t_before = thermo.get(tid)["last_seen"]; time.sleep(1.1)
# Neu einrichten: gleiche ID und Sensoren, neuer Schluessel, Abgleich bleibt
r = A.post("/api/thermo", json={"name": "Aussen neu", "interval": 5, "replace": tid, "wifi": W}); assert r.status_code == 201, r.get_json()
j = r.get_json(); new = j["token"]
assert j["replaced"] is True and j["device"]["id"] == tid and new != old and j["device"]["name"] == "Aussen neu" and j["device"]["interval"] == 5, j
assert len(thermo.load()) == 1 and sorted(s["id"] for s in homematic.load_sensors() if s.get("source") == "thermo") == sens_before     # keine neuen Sensoren, kein zweites Geraet
assert make_cfg.parse(base64.b64decode(j["cfg"]))["id"] == tid and make_cfg.parse(base64.b64decode(j["cfg"]))["token"] == new
assert j["device"]["calib"]["temp"] is not None and j["device"]["last_seen"] == t_before         # Abgleich + letzte Meldung bleiben
assert next(s for s in homematic.load_sensors() if s["datapoint"] == "temp")["name"] == "Aussen neu Temperatur"
# Flashen scheitert: der alte Schluessel funktioniert weiter ...
assert N.post("/api/sensor/" + tid, json=body, headers=H(old)).status_code == 200
# ... das Geraet meldet sich mit dem neuen: der alte ist danach ungueltig
assert N.post("/api/sensor/" + tid, json=body, headers=H(new)).status_code == 200
assert N.post("/api/sensor/" + tid, json=body, headers=H(old)).status_code == 401
assert N.post("/api/sensor/" + tid, json=body, headers=H(new)).status_code == 200
# unbekannte ID: Fehler, nichts angelegt
n = len(thermo.load()); r = A.post("/api/thermo", json={"name": "x", "replace": "t-nixda123", "wifi": W}); assert r.status_code == 404 and len(thermo.load()) == n
# ungueltige WLAN-Angaben: nichts veraendert (Schluessel bleibt)
assert A.post("/api/thermo", json={"name": "x", "replace": tid, "wifi": {**W, "pass": "kurz"}}).status_code == 400
assert N.post("/api/sensor/" + tid, json=body, headers=H(new)).status_code == 200 and "pending_hash" not in thermo._load()[0]
print("THERMO ERSETZEN OK")
