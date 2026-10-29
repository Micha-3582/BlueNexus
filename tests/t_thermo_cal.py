import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_cal.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"}); N = webapp.app.test_client()
webapp.too_many_attempts = lambda k: False
c = A.post("/api/thermo", json={"name": "Außen", "wifi": {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}).get_json()
tid, tok = c["device"]["id"], c["token"]
H = {"Authorization": "Bearer " + tok}
def val(metric):
    homematic._value_cache.clear()
    return homematic.read_sensor(next(s for s in homematic.load_sensors() if s.get("datapoint") == metric))
# ohne Messung: Fehler
r = A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": 21}); assert r.status_code == 400 and "noch keine Messung" in r.get_json()["error"]
N.post("/api/sensor/" + tid, json={"temp": 22.30, "hum": 48.0, "bat": 3.02, "rssi": -60, "fw": "1.0.1"}, headers=H)
assert val("temp") == 22.3 and val("hum") == 48.0
# Abgleich Temperatur: Referenz 21,8 -> Korrektur -0,5; Feuchte unberuehrt
r = A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": "21,8"}); assert r.status_code == 200, r.get_json()
j = r.get_json(); assert j["calib"] == {"temp": -0.5, "hum": None} and j["device"]["last"]["temp"] == 21.8 and j["device"]["raw"]["temp"] == 22.3, j
assert val("temp") == 21.8 and val("hum") == 48.0
# neue Messung: Korrektur gilt weiter
N.post("/api/sensor/" + tid, json={"temp": 15.0, "hum": 60.0, "bat": 3.0, "rssi": -60}, headers=H)
assert val("temp") == 14.5
# Feuchte dazu, Temperatur bleibt
r = A.post("/api/thermo/" + tid + "/calibrate", json={"ref_hum": 55}); assert r.get_json()["calib"] == {"temp": -0.5, "hum": -5.0}
assert val("hum") == 55.0 and val("temp") == 14.5
# Begrenzung auf 0..100 %
N.post("/api/sensor/" + tid, json={"temp": 15.0, "hum": 98.0}, headers=H); d = thermo._load(); d[0]["calib"]["hum"] = 10; thermo._save(d)
assert val("hum") == 100.0
# Fehler: zu grosse Abweichung, keine Zahl, nichts angegeben, zu alte Messung
N.post("/api/sensor/" + tid, json={"temp": 15.0, "hum": 50.0}, headers=H)
assert A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": 40}).status_code == 400
assert "Zahl" in A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": "abc"}).get_json()["error"]
assert A.post("/api/thermo/" + tid + "/calibrate", json={}).status_code == 400
d = thermo._load(); d[0]["last_seen"] = time.time() - 900; thermo._save(d)
r = A.post("/api/thermo/" + tid + "/calibrate", json={"ref_temp": 15}); assert r.status_code == 400 and "RESET" in r.get_json()["error"]
# zuruecksetzen geht auch ohne frische Messung
r = A.post("/api/thermo/" + tid + "/calibrate", json={"reset": True}); assert r.status_code == 200 and r.get_json()["calib"] == {"temp": None, "hum": None}
N.post("/api/sensor/" + tid, json={"temp": 15.0, "hum": 50.0}, headers=H); assert val("temp") == 15.0
# Rechte + Liste
assert L.post("/api/thermo/" + tid + "/calibrate", json={"reset": True}).status_code == 403
assert A.post("/api/thermo/t-nixda123/calibrate", json={"ref_temp": 1}).status_code == 400
lst = A.get("/api/thermo").get_json()["devices"][0]; assert "calib" in lst and "raw" in lst and lst["last"]["temp"] == 15.0
print("THERMO CAL OK")
