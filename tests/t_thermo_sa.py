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
# Kopplungscode spaeter wieder ansehen: nur Administratoren, nur bei Geraeten mit Code
assert L.post("/api/thermo/" + tid + "/code", json={}).status_code == 403            # ohne Verwaltungsrecht gesperrt
r = A.post("/api/thermo/" + tid + "/code", json={}); assert r.status_code == 200 and r.get_json()["code"] == code
assert A.post("/api/thermo/" + c["device"]["id"] + "/code", json={}).status_code == 404         # USB-Geraet: kein Code gespeichert
assert next(x for x in thermo.listing() if x["id"] == tid)["has_code"] is True
assert "bnxthermo1_" not in A.get("/api/thermo").get_data(as_text=True)                            # die Liste verraet den Code nicht
print("THERMO-STANDALONE OK")

# ---- Funk-Update (OTA) ab Firmware 2.0.0: die mitgelieferte (neueste) Firmware ist 2.0.7 ----
import json as _j, hashlib as _h
FWD = os.path.join(os.path.dirname(webapp.__file__), "static", "firmware", "thermo", "2.0.7")
R = _j.load(open(os.path.join(FWD, "release.json"), encoding="utf-8"))["ota"]
def rep(tid_, tok, fw, hdr=None):
    d_ = thermo._load(); [x for x in d_ if x["id"] == tid_][0]["last_seen"] = 0; thermo._save(d_)           # 20-s-Bremse fuer den Test umgehen
    return N.post("/api/sensor/" + tid_, json={**B, "fw": fw}, headers={"Authorization": "Bearer " + tok, **(hdr or {})})
def upd(tid_): return [y for y in A.get("/api/thermo").get_json()["devices"] if y["id"] == tid_][0]["update"]
# Firmware 1.1.1: kein Funk-Update moeglich
r = rep(d2["id"], d2["token"], "1.1.1"); assert r.status_code == 200 and "ota" not in r.get_json()
assert upd(d2["id"]) is False and A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 400
# schon die neueste (2.0.7): nichts zu tun
r = rep(d2["id"], d2["token"], "2.0.7"); assert "ota" not in r.get_json() and upd(d2["id"]) is False
assert A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 400
# Geraet mit 2.0.0: Update verfuegbar
rep(d2["id"], d2["token"], "2.0.0"); assert upd(d2["id"]) is True
assert L.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 403                         # nur Administratoren
assert N.get("/api/sensor/" + d2["id"] + "/fw.bin", headers=H2).status_code == 404                       # ohne Vormerkung keine Datei
assert "ota" not in rep(d2["id"], d2["token"], "2.0.0").get_json()                                       # und kein Angebot
assert A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 200
o = rep(d2["id"], d2["token"], "2.0.0").get_json()["ota"]
assert o == {"version": "2.0.7", "md5": R["md5"], "url": "/api/sensor/" + d2["id"] + "/fw.bin"}, o
assert N.get(o["url"], headers={"Authorization": "Bearer falsch"}).status_code == 401                    # ohne den Schluessel des Geraets keine Datei
g = N.get(o["url"], headers=H2); assert g.status_code == 200 and int(g.headers["Content-Length"]) == R["size"] and len(g.data) == R["size"]
assert _h.md5(g.data).hexdigest() == R["md5"]
assert N.get(o["url"], headers={**H2, **EXT}).status_code == 404                                         # Heimnetz-Geraet: nicht ueber den Tunnel
r = rep(d2["id"], d2["token"], "2.0.7"); assert r.status_code == 200 and "ota" not in r.get_json()      # neue Version gemeldet: Vormerkung weg, keine Schleife
assert thermo.get(d2["id"]).get("ota_pending") is None
# Geraet schafft es nicht (bleibt auf 2.0.0): nach OTA_MAX_OFFERS Angeboten Schluss
assert A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 400                         # meldet 2.0.7 = aktuell
rep(d2["id"], d2["token"], "2.0.0"); assert A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 200
n = sum(1 for _ in range(8) if "ota" in rep(d2["id"], d2["token"], "2.0.0").get_json())
assert n == thermo.OTA_MAX_OFFERS and thermo.get(d2["id"]).get("ota_failed") == "2.0.7", (n, thermo.get(d2["id"]))
# Nie zurueck: ein Geraet mit NEUERER Version als im Paket bekommt weder "Update verfuegbar" noch ein Angebot (die Firmware spielt jede abweichende Version ein)
rep(d2["id"], d2["token"], "2.0.8"); assert upd(d2["id"]) is False and A.post("/api/thermo/" + d2["id"] + "/update", json={}).status_code == 400
rep(d2["id"], d2["token"], "2.0.1"); assert upd(d2["id"]) is True                                         # aeltere Version: Update verfuegbar
d_ = thermo._load(); [x for x in d_ if x["id"] == d2["id"]][0]["ota_pending"] = True; thermo._save(d_)   # selbst bei vorgemerktem Update:
assert "ota" not in rep(d2["id"], d2["token"], "2.0.8").get_json() and thermo.get(d2["id"]).get("ota_pending") is None
# Internet-Geraet (ohne USB): Offer und Datei auch ueber den Tunnel
rep(tid, d["token"], "2.0.0", EXT); assert A.post("/api/thermo/" + tid + "/update", json={}).status_code == 200
r = rep(tid, d["token"], "2.0.0", EXT); assert r.status_code == 200 and "ota" in r.get_json(), r.get_data(as_text=True)
assert N.get("/api/sensor/" + tid + "/fw.bin", headers={**H, **EXT}).status_code == 200
# Neuen Kopplungscode fuer ein Geraet ohne gespeicherten Code (z. B. alte Firmware): ID bleibt, alter Schluessel gilt bis zur ersten Meldung mit dem neuen
c_old = c["device"]["id"]
r = A.post("/api/thermo/" + c_old + "/code", json={"new": True, "server": "https://x.example.de"}); assert r.status_code == 400            # Heimnetz-Geraet: http noetig
r = A.post("/api/thermo/" + c_old + "/code", json={"new": True, "server": "http://192.168.50.40:5005"}); assert r.status_code == 200, r.get_data(as_text=True)
d3 = _j.loads(base64.b64decode(r.get_json()["code"][len("bnxthermo1_"):])); assert d3["id"] == c_old and d3["token"] != c["token"]
assert N.post("/api/sensor/" + c_old, json=B, headers={"Authorization": "Bearer " + c["token"]}).status_code == 200          # alter Schluessel gilt noch
thermo._save([{**x, "last_seen": 0} if x["id"] == c_old else x for x in thermo._load()])
assert N.post("/api/sensor/" + c_old, json=B, headers={"Authorization": "Bearer " + d3["token"]}).status_code == 200          # neuer Schluessel wird angenommen
thermo._save([{**x, "last_seen": 0} if x["id"] == c_old else x for x in thermo._load()])
assert N.post("/api/sensor/" + c_old, json=B, headers={"Authorization": "Bearer " + c["token"]}).status_code == 401             # und ersetzt den alten
assert A.post("/api/thermo/" + c_old + "/code", json={}).get_json()["code"].startswith("bnxthermo1_")                          # jetzt auch wieder ansehbar
print("THERMO-OTA OK")
