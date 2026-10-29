import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic, notify
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
notify.STATE_PATH = os.path.join(tmp, "notify_state.json")
sent = []
notify.any_configured = lambda: True
notify._send_async = lambda text, to=None, system=False: sent.append(text)
webapp.too_many_attempts = lambda k: False
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_mon.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"}); N = webapp.app.test_client()
c = A.post("/api/thermo", json={"name": "Außen", "interval": 15, "wifi": {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}).get_json()
tid, H = c["device"]["id"], {"Authorization": "Bearer " + c["token"]}
post = lambda **b: N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50, **b}, headers=H).status_code
# frisch angelegt, noch keine Meldung: nichts melden
thermo.check_all(); assert sent == [], sent
assert post(bat=3.2) == 200; thermo.check_all(); assert sent == []
# 1) meldet sich nicht mehr (3 Intervalle + 2 min = 47 min): einmal melden, nicht doppelt
d = thermo._load(); d[0]["last_seen"] = time.time() - 60 * 60; thermo._save(d)
thermo.check_all(); thermo.check_all(); assert len(sent) == 1 and "meldet sich seit 60 min nicht mehr" in sent[0] and "Außen" in sent[0], sent
# 2) meldet sich wieder
post(bat=3.2); thermo.check_all(); assert len(sent) == 2 and "meldet sich wieder" in sent[1], sent
# 3) Batterie: erst nach 2 Meldungen in Folge unter 3,0 V
sent.clear(); post(bat=2.9); thermo.check_all(); assert sent == []
post(bat=2.9); thermo.check_all(); thermo.check_all(); assert len(sent) == 1 and "Batterie bald wechseln" in sent[0] and "2,9" in sent[0], sent
post(bat=3.3); thermo.check_all(); assert len(sent) == 2 and "wieder in Ordnung" in sent[1], sent
# ohne Batteriemessung (< 1 V = nicht verdrahtet): nie Batterie-Meldung
sent.clear(); post(bat=0.7); post(bat=0.7); post(bat=0.7); thermo.check_all(); assert sent == [], sent
# 4) Schalter in den Einstellungen
cfg["notify_events"] = {"thermo_offline": False}
d = thermo._load(); d[0]["last_seen"] = time.time() - 90 * 60; thermo._save(d); thermo.check_all(); assert sent == [], sent
cfg["notify_events"] = {}
post(bat=3.2); thermo.check_all()
# 5) Entfernen raeumt offene Meldungen auf
d = thermo._load(); d[0]["last_seen"] = time.time() - 90 * 60; thermo._save(d); thermo.check_all()
st = notify._state()["events"]; assert "thermo_off:" + tid in st, st
assert A.delete("/api/thermo/" + tid).status_code == 200
assert "thermo_off:" + tid not in notify._state()["events"] and "thermo_bat:" + tid not in notify._state()["events"]
# 6) Einstellungs-Liste: nur mit Modul Smart Home
cfg["modules"] = {"energy": True, "smarthome": True, "verlauf": True, "cameras": True, "alexa": False}
keys = [e["key"] for e in A.get("/api/notify").get_json()["events"]]; assert "thermo_offline" in keys and "thermo_battery" in keys, keys
cfg["modules"] = {"energy": True, "smarthome": False, "verlauf": True, "cameras": True, "alexa": False}
keys = [e["key"] for e in A.get("/api/notify").get_json()["events"]]; assert "thermo_offline" not in keys, keys
print("THERMO MELDUNGEN OK")
