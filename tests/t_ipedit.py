"""IP-Adresse nachtraeglich aendern: Geraete (Shelly/Tasmota/WLED/Tuya/Midea lokal), mehrere Kanaele, Pruefungen, Rechte, WOL."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, wol, auth
from auth import UserStore

devs = [
    {"id": "tuya1", "kind": "tuya", "dev_id": "abc", "local_key": "k", "ip": "192.168.50.50", "version": "3.3", "name": "Heizer Küche", "icon": "🔥", "model": "SP1", "show": True},
    {"id": "sh-a", "kind": "shelly", "mac": "AA11", "channel": 0, "gen": 2, "ip": "192.168.50.60", "name": "Shelly Kanal 1", "icon": "💡", "model": "Plus 2PM", "show": True},
    {"id": "sh-b", "kind": "shelly", "mac": "AA11", "channel": 1, "gen": 2, "ip": "192.168.50.60", "name": "Shelly Kanal 2", "icon": "💡", "model": "Plus 2PM", "show": True},
    {"id": "sh-c", "kind": "shelly", "mac": "BB22", "channel": 0, "gen": 2, "ip": "192.168.50.61", "name": "Anderes Gerät", "icon": "💡", "model": "Plus 1", "show": True},
    {"id": "tas1", "kind": "tasmota", "mac": "CC33", "channel": 1, "gen": 0, "ip": "192.168.50.62", "name": "Tasmota", "icon": "🔌", "model": "T", "show": True},
    {"id": "midea-1", "kind": "midea", "ip": "192.168.50.232", "port": 6444, "device_id": 1, "name": "Klima", "icon": "❄", "show": True},
    {"id": "midea-c", "kind": "midea", "cloud": True, "ip": "", "port": 0, "device_id": 2, "name": "Cloud-Klima", "icon": "❄", "show": True},
    {"id": "rem1", "kind": "remote", "ip": "", "name": "Geteilt", "icon": "🔌", "show": True},
]
json.dump(devs, open(shelly.DEVICES_PATH, "w"))
live = {"192.168.50.55": True}
shelly.status = lambda d: {"online": bool(live.get(d.get("ip"), False)), "on": False, "power": None}

webapp.users = UserStore(os.path.join(tmp, "u_ip.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "settings_geraete": "write"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")
ip_of = lambda i: next(d for d in shelly.load_devices() if d["id"] == i)["ip"]

# Tuya: neue Adresse, Antwort mit Erreichbarkeit; Name/Regeln-ID bleiben
r = A.patch("/api/shelly/tuya1", json={"ip": "192.168.50.55"}); assert r.status_code == 200, r.get_data(as_text=True)
j = r.get_json(); assert j["ok"] and j["ip"] == "192.168.50.55" and j["online"] is True, j
assert ip_of("tuya1") == "192.168.50.55" and next(d for d in shelly.load_devices() if d["id"] == "tuya1")["name"] == "Heizer Küche"
r = A.patch("/api/shelly/tuya1", json={"ip": "192.168.50.99"}); assert r.status_code == 200 and r.get_json()["online"] is False       # antwortet dort nicht: trotzdem gespeichert, aber gemeldet
assert ip_of("tuya1") == "192.168.50.99"
# mehrere Kanaele eines Geraets (gleiche MAC) wandern gemeinsam; ein anderes Geraet nicht
assert A.patch("/api/shelly/sh-a", json={"ip": "192.168.50.70"}).status_code == 200
assert ip_of("sh-a") == "192.168.50.70" and ip_of("sh-b") == "192.168.50.70" and ip_of("sh-c") == "192.168.50.61"
assert A.patch("/api/shelly/tas1", json={"ip": "192.168.50.71"}).status_code == 200 and ip_of("tas1") == "192.168.50.71"
assert A.patch("/api/shelly/midea-1", json={"ip": "192.168.50.233"}).status_code == 200 and ip_of("midea-1") == "192.168.50.233"
# Pruefungen: ungueltig, nicht lokal, leer, Cloud/geteilt; nichts wird dabei veraendert
before = json.dumps(shelly.load_devices(), sort_keys=True)
for bad in ("abc", "8.8.8.8", "127.0.0.1", "192.168.2", "http://192.168.50.5", "", "fe80::1", "192.168.50.5/24"):
    r = A.patch("/api/shelly/tuya1", json={"ip": bad, "name": "Soll nicht gelten"}); assert r.status_code == 400, (bad, r.status_code)
assert json.dumps(shelly.load_devices(), sort_keys=True) == before
assert A.patch("/api/shelly/midea-c", json={"ip": "192.168.50.80"}).status_code == 400            # Cloud-Anlage
assert A.patch("/api/shelly/rem1", json={"ip": "192.168.50.80"}).status_code == 400               # geteiltes Geraet
assert A.patch("/api/shelly/gibtsnicht", json={"ip": "192.168.50.80"}).status_code in (404, 400)
# nur Administratoren
assert I.patch("/api/shelly/tuya1", json={"ip": "192.168.50.81"}).status_code == 403 and ip_of("tuya1") == "192.168.50.99"
# nicht-Admins sehen die Adresse nicht im Klartext
webapp.users.create("lese", "lesepass123", {"dashboard": "read", "settings_geraete": "read"})
L = login("lese", "lesepass123")
rows = [x for x in L.get("/api/shelly").get_json() if x["id"] == "tuya1"]
assert rows and all(x.get("ip") == "•.•.•.•" and x.get("ip_hidden") for x in rows)          # ohne Schreibrecht auf die Geraeteverwaltung: Adresse maskiert (und damit kein IP-Feld im Bearbeiten-Bereich)
# normales Umbenennen ohne IP aendert die Adresse nicht
assert A.patch("/api/shelly/tuya1", json={"name": "Neuer Name"}).status_code == 200 and ip_of("tuya1") == "192.168.50.99"

# WOL: IP und MAC nachtraeglich aenderbar
w = wol.add("Rechner", "aa:bb:cc:dd:ee:ff", ip="192.168.50.50")
assert A.patch("/api/wol/" + w["id"], json={"users": None}).status_code == 200
assert A.patch("/api/wol/" + w["id"], json={"ip": "192.168.50.51"}).status_code == 200 and wol.load()[0]["ip"] == "192.168.50.51"
assert A.patch("/api/wol/" + w["id"], json={"mac": "11-22-33-44-55-66"}).status_code == 200 and wol.load()[0]["mac"] == "11:22:33:44:55:66"
assert A.patch("/api/wol/" + w["id"], json={"ip": "8.8.8.8"}).status_code == 400
print("IP AENDERN OK")
