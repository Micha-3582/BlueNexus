import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic, hashlib
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_thsa.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})
N = webapp.app.test_client()                                                   # ohne Anmeldung = das Geraet

import base64
EXT = {"CF-Connecting-IP": "203.0.113.9", "X-Forwarded-For": "203.0.113.9"}         # so kommt eine Meldung ueber den Tunnel an
B = {"temp": 12.5, "hum": 60.0, "bat": 3.7, "rssi": -60, "fw": "1.2.0-sa"}
# Geraet ohne USB anlegen: nur Administratoren, Adresse muss https sein, Kopplungscode wie in der Notiz
assert L.post("/api/thermo", json={"standalone": True, "name": "x", "server": "https://b.example.de"}).status_code == 403
r = A.post("/api/thermo", json={"standalone": True, "name": "Bauhof", "location": "Bauhof Nord", "interval": 15, "server": "http://b.example.de"}); assert r.status_code == 400
assert not thermo.load(), "bei ungueltiger Adresse darf nichts zurueckbleiben"
r = A.post("/api/thermo", json={"standalone": True, "name": "Bauhof", "location": "Bauhof Nord", "interval": 15, "server": "https://b.example.de/"}); assert r.status_code == 201, r.get_data(as_text=True)
j = r.get_json(); tid = j["device"]["id"]; code = j["code"]
assert code.startswith("bnxthermo1_") and j["device"]["standalone"] is True and j["device"]["location"] == "Bauhof Nord"
d = json.loads(base64.b64decode(code[len("bnxthermo1_"):])); assert d["server"] == "https://b.example.de" and d["id"] == tid and len(d["token"]) >= 24 and set(d) == {"server", "id", "token"}
assert d["token"] not in open(thermo.THERMO_PATH, encoding="utf-8").read()            # nur der Hash liegt auf der Platte
H = {"Authorization": "Bearer " + d["token"]}
# Meldung von aussen (Tunnel): geht, aber zu schnell hintereinander wird gebremst
r = N.post("/api/sensor/" + tid, json=B, headers={**H, **EXT}); assert r.status_code == 200 and r.get_json()["ok"], r.get_data(as_text=True)
assert N.post("/api/sensor/" + tid, json=B, headers={**H, **EXT}).status_code == 429
assert thermo.get(tid)["last"]["temp"] == 12.5
# falscher Schluessel von aussen -> 401; ein normales (USB-)Geraet bleibt von aussen gesperrt
assert N.post("/api/sensor/" + tid, json=B, headers={"Authorization": "Bearer falsch", **EXT}).status_code == 401
r = A.post("/api/thermo", json={"name": "Innen", "interval": 15, "wifi": {"ssid": "T", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}); c = r.get_json()
assert N.post("/api/sensor/" + c["device"]["id"], json=B, headers={"Authorization": "Bearer " + c["token"], **EXT}).status_code == 404
assert N.post("/api/sensor/" + c["device"]["id"], json=B, headers={"Authorization": "Bearer " + c["token"]}).status_code == 200          # im lokalen Netz wie bisher
# Standort aendern
assert A.patch("/api/thermo/" + tid, json={"location": "Garten"}).status_code == 200 and thermo.get(tid)["location"] == "Garten"
# Heimnetz-Weg: Code mit http-Adresse, Geraet bleibt von aussen gesperrt
r = A.post("/api/thermo", json={"standalone": True, "mode": "lan", "name": "Flur", "server": "https://b.example.de"}); assert r.status_code == 400
r = A.post("/api/thermo", json={"standalone": True, "mode": "lan", "name": "Flur", "server": "http://192.168.50.40:5005"}); assert r.status_code == 201, r.get_data(as_text=True)
j = r.get_json(); d2 = json.loads(base64.b64decode(j["code"][len("bnxthermo1_"):]))
assert d2["server"] == "http://192.168.50.40:5005" and j["device"]["paired"] is True and j["device"]["standalone"] is False
H2 = {"Authorization": "Bearer " + d2["token"]}
x = N.post("/api/sensor/" + d2["id"], json=B, headers={**H2, **EXT}); assert x.status_code == 404, (x.status_code, x.get_data(as_text=True))
x = N.post("/api/sensor/" + d2["id"], json=B, headers=H2); assert x.status_code == 200, (x.status_code, x.get_data(as_text=True))
# Kopplungscode spaeter wieder ansehen: nur mit Passwort, nur bei Geraeten mit Code
assert A.post("/api/thermo/" + tid + "/code", json={"password": "falsch"}).status_code == 403
assert L.post("/api/thermo/" + tid + "/code", json={"password": "lesepass123"}).status_code == 403            # ohne Verwaltungsrecht gesperrt
r = A.post("/api/thermo/" + tid + "/code", json={"password": "adminpass1"}); assert r.status_code == 200 and r.get_json()["code"] == code
assert A.post("/api/thermo/" + c["device"]["id"] + "/code", json={"password": "adminpass1"}).status_code == 404         # USB-Geraet: kein Code gespeichert
assert next(x for x in thermo.listing() if x["id"] == tid)["has_code"] is True
assert "bnxthermo1_" not in A.get("/api/thermo").get_data(as_text=True)                            # die Liste verraet den Code nicht
print("THERMO-STANDALONE OK")
