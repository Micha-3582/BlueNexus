import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_int.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"}); N = webapp.app.test_client()
webapp.too_many_attempts = lambda k: False
c = A.post("/api/thermo", json={"name": "T", "wifi": {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}).get_json()
tid, H = c["device"]["id"], {"Authorization": "Bearer " + c["token"]}
body = {"temp": 20, "hum": 50, "bat": 3.0}
assert N.post("/api/sensor/" + tid, json=body, headers=H).get_json()["interval"] == 15
def temp():
    homematic._value_cache.clear(); return homematic.read_sensor(next(s for s in homematic.load_sensors() if s["datapoint"] == "temp"))
# Intervall auf 1 Minute stellen: das Geraet schlaeft noch 15 Minuten -> darf nicht sofort als "weg" gelten
assert A.patch("/api/thermo/" + tid, json={"interval": 1}).status_code == 200
d = thermo._load(); d[0]["last_seen"] = time.time() - 20 * 60; thermo._save(d)
assert temp() == 20 and A.get("/api/thermo").get_json()["devices"][0]["online"] is True
# nach der naechsten Meldung gilt das neue Intervall: Antwort 1, danach nach ~5 Minuten Stille offline
assert N.post("/api/sensor/" + tid, json=body, headers=H).get_json()["interval"] == 1
d = thermo._load(); d[0]["last_seen"] = time.time() - 6 * 60; thermo._save(d)
assert temp() is None and A.get("/api/thermo").get_json()["devices"][0]["online"] is False
# Grenzen
assert A.patch("/api/thermo/" + tid, json={"interval": 99999}).status_code == 200 and thermo.get(tid)["interval"] == 1440
print("THERMO INTERVALL OK")
