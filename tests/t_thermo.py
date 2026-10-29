import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic, hashlib
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_th.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})
N = webapp.app.test_client()                                                   # ohne Anmeldung = das Geraet

# 1) Rechte: nur Administratoren richten ein
assert L.get("/api/thermo").status_code == 403 and L.post("/api/thermo", json={"name": "x", "wifi": {}}).status_code == 403 and N.get("/api/thermo").status_code == 401
j = A.get("/api/thermo").get_json()
fw = j["firmware"]; assert fw["version"] == "1.1.1" and fw["offset"] == 0 and fw["cfg_offset"] == 0x1F0000 and fw["cfg_size"] == 4096 and fw["url"].endswith("thermo-1.1.1.bin"), fw
fp = os.path.join(os.path.dirname(webapp.__file__), fw["url"].lstrip("/").replace("/", os.sep))
assert hashlib.sha256(open(fp, "rb").read()).hexdigest() == fw["sha256"]       # mitgelieferte Firmware passt zur Pruefsumme
assert A.get(fw["url"]).status_code == 200                                      # und ist auslieferbar
# 2) Anlegen
r = A.post("/api/thermo", json={"name": "Außen", "interval": 15, "wifi": {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}); assert r.status_code == 201
c = r.get_json(); tid, token = c["device"]["id"], c["token"]
assert tid.startswith("t-") and len(token) >= 24 and "token_hash" not in c["device"], c
raw = open(thermo.THERMO_PATH, encoding="utf-8").read(); assert token not in raw and hashlib.sha256(token.encode()).hexdigest() in raw       # nur der Hash liegt auf der Platte
sens = [s for s in homematic.load_sensors() if s.get("source") == "thermo"]
assert {s["datapoint"] for s in sens} == {"temp", "hum", "bat", "rssi"} and all(s["address"] == tid for s in sens), sens
assert {s["kind"] for s in sens} == {"temperature", "humidity", "voltage", "signal"} and next(s for s in sens if s["datapoint"] == "temp")["name"] == "Außen Temperatur"
assert all(s["users"] == [] for s in sens)                                      # neue Sensoren: zunaechst nur Administratoren
# 2b) Diagnose: gescheiterte Versuche eines bekannten Geraets werden angezeigt
N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50}, headers={"Authorization": "Bearer falsch"})
at = A.get("/api/thermo/" + tid + "/status").get_json()["device"]["attempt"]; assert at and at["why"] == "falscher Schlüssel" and at["age_s"] < 5 and at["ip"], at
N.post("/api/sensor/t-unbekannt9", json={}, headers={"Authorization": "Bearer x"})                      # unbekannte ID: nichts gespeichert
webapp.failed_attempts.clear() if hasattr(webapp, "failed_attempts") else None
# 3) Annahme der Messwerte
H = lambda t: {"Authorization": "Bearer " + t}
body = {"temp": 24.83, "hum": 60.1, "bat": 3.02, "rssi": -62, "fw": "1.0.1"}
assert N.post("/api/sensor/" + tid, json=body).status_code == 401                                    # ohne Schluessel
assert N.post("/api/sensor/" + tid, json=body, headers=H("falsch")).status_code == 401
assert N.post("/api/sensor/t-unbekannt1", json=body, headers=H(token)).status_code == 401
assert N.post("/api/sensor/" + tid, json={"temp": 99, "hum": 200}, headers=H(token)).status_code == 400          # unplausibel
assert N.post("/api/sensor/" + tid, data="kein json", headers=H(token)).status_code == 400
assert N.get("/api/thermo/" + tid + "/status").status_code == 401
assert A.get("/api/thermo/" + tid + "/status").get_json()["device"]["last_seen"] is None
_tma = webapp.too_many_attempts; webapp.too_many_attempts = lambda k: False                                                                 # Bremse hier nicht Teil des Tests (eigener Abschnitt unten)
ok = N.post("/api/sensor/" + tid, json=body, headers=H(token)); assert ok.status_code == 200 and ok.get_json() == {"ok": True, "interval": 15}, ok.get_json()
st = A.get("/api/thermo/" + tid + "/status").get_json()["device"]
assert st["attempt"] is None and st["online"] and st["fw"] == "1.0.1" and st["last"]["temp"] == 24.83 and st["last"]["bat"] == 3.02, st
homematic._value_cache.clear()
val = {s["datapoint"]: homematic.read_sensor(s) for s in homematic.load_sensors() if s.get("source") == "thermo"}
assert val == {"temp": 24.8, "hum": 60.1, "bat": 3.02, "rssi": -62.0}, val                           # round(.,1) wie bei allen Sensoren
# Batterie ohne Messung (USB-Betrieb, Zufallswerte unter 1 V) -> keine Zahl
N.post("/api/sensor/" + tid, json={**body, "bat": 0.7}, headers=H(token)); homematic._value_cache.clear()
assert homematic.read_sensor(next(s for s in homematic.load_sensors() if s.get("datapoint") == "bat")) is None
# nur Temperatur/Feuchte gueltig, Rest fehlt -> ok; Intervall aus der Antwort
A.patch("/api/thermo/" + tid, json={"interval": 30}); assert N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50}, headers=H(token)).get_json()["interval"] == 30
# 3b) Diagnosefelder ab Firmware 1.1 (laufende Nummer + Startgrund)
N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50, "n": 7, "rr": 8, "fw": "1.1.0"}, headers=H(token))
m = A.get("/api/thermo/" + tid + "/status").get_json()["device"]["meta"]; assert m == {"n": 7, "rr": 8}, m
N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50, "n": 8, "rr": 1, "ap": "AA:BB:CC:00:11:22"}, headers=H(token))
assert A.get("/api/thermo/" + tid + "/status").get_json()["device"]["meta"] == {"n": 8, "rr": 1, "ap": "aa:bb:cc:00:11:22"}
N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50, "ap": "kein-mac"}, headers=H(token))
assert A.get("/api/thermo/" + tid + "/status").get_json()["device"]["meta"]["ap"] == "aa:bb:cc:00:11:22"      # ungueltige Adresse wird ignoriert
N.post("/api/sensor/" + tid, json={"temp": 20, "hum": 50, "n": "x", "rr": 99999}, headers=H(token))
assert A.get("/api/thermo/" + tid + "/status").get_json()["device"]["meta"] == {"n": 8, "rr": 1, "ap": "aa:bb:cc:00:11:22"}                    # Unsinn wird ignoriert
# 4) Offline nach 3 verpassten Intervallen
d = thermo._load(); d[0]["last_seen"] = time.time() - (30 * 60 * 3 + 200); thermo._save(d); homematic._value_cache.clear()
assert homematic.read_sensor(next(s for s in homematic.load_sensors() if s.get("datapoint") == "temp")) is None
assert A.get("/api/thermo").get_json()["devices"][0]["online"] is False
# 5) Umbenennen: Sensornamen ziehen mit
assert A.patch("/api/thermo/" + tid, json={"name": "Garten"}).status_code == 200
assert next(s for s in homematic.load_sensors() if s.get("datapoint") == "hum")["name"] == "Garten Luftfeuchte"
# 7) Bremse gegen Raten
webapp.too_many_attempts = _tma
codes = [N.post("/api/sensor/" + tid, json=body, headers=H("x" + str(i))).status_code for i in range(30)]
assert 429 in codes, codes
webapp.failed_attempts.clear() if hasattr(webapp, "failed_attempts") else None
# 8) Entfernen: Sensoren weg
assert A.delete("/api/thermo/" + tid).status_code == 200 and A.delete("/api/thermo/" + tid).status_code == 404
assert not [s for s in homematic.load_sensors() if s.get("source") == "thermo"] and thermo.load() == []
# 9) Karte nur mit Modul Smart Home
cfg["modules"] = {"energy": True, "smarthome": True, "verlauf": True, "cameras": True, "alexa": False}
h = A.get("/admin").get_data(as_text=True); assert 'id="thermo-card"' in h and "thermo-flash.js?v=" in h and "thermo-cfg.js" not in h and 'id="th-pass" type="password"' in h and 'data-for="th-pass"' in h
cfg["modules"] = {"energy": True, "smarthome": False, "verlauf": True, "cameras": True, "alexa": False}
h = A.get("/admin").get_data(as_text=True); assert 'id="thermo-card"' not in h
# 10) Konfig bytegleich zur Referenz des Thermometer-Chats (make_cfg.py)
sys.path.insert(0, "K:/Claude Projekte/BlueNexus-Thermometer/tools")
import make_cfg
cb = make_cfg.build({"v": 1, "name": "Außen", "ssid": "Test", "pass": "geheim123", "ip": None, "server": "http://192.168.50.40:5005", "id": "t-abcd1234", "token": "tok", "interval": 15})
assert len(cb) == 4096 and make_cfg.parse(cb)["ssid"] == "Test"
print("THERMO OK")
