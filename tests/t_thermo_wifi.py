import sys, os, json, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import thermo, homematic
thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_thw.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
sys.path.insert(0, "K:/Claude Projekte/BlueNexus-Thermometer/tools")
import make_cfg

def post(**w):
    base = {"ssid": "Hanss WLAN", "pass": "geheim1234", "server": "http://192.168.50.40:5005", "ip": None}; base.update(w)
    return A.post("/api/thermo", json={"name": "Außen", "interval": 15, "remember": False, "wifi": base})

# 1) Server baut die Konfiguration, bytegleich zur Referenz des Thermometer-Projekts
r = post(); assert r.status_code == 201, r.get_json()
j = r.get_json(); dev, token = j["device"], j["token"]
cb = base64.b64decode(j["cfg"]); assert len(cb) == 4096
exp = make_cfg.build({"v": 1, "name": "Außen", "ssid": "Hanss WLAN", "pass": "geheim1234", "ip": None, "server": "http://192.168.50.40:5005", "id": dev["id"], "token": token, "interval": 15})
assert cb == exp, "cfg.bin weicht von make_cfg.py ab"
p = make_cfg.parse(cb); assert p["ssid"] == "Hanss WLAN" and p["pass"] == "geheim1234" and p["id"] == dev["id"] and p["token"] == token
assert not os.path.exists(thermo.WIFI_PATH) and j["wifi"]["saved"] is False                    # ohne "merken" bleibt nichts gespeichert
assert "geheim1234" not in open(thermo.THERMO_PATH, encoding="utf-8").read()
# 2) Merken: Name + Passwort gespeichert, Oberflaeche sieht nie das Passwort
r = A.post("/api/thermo", json={"name": "Hof", "interval": 15, "remember": True, "wifi": {"ssid": "Hanss WLAN", "pass": "geheim1234", "server": "http://192.168.50.40:5005"}}); assert r.status_code == 201
assert r.get_json()["wifi"] == {"saved": True, "ssid": "Hanss WLAN", "has_pass": True}
lst = A.get("/api/thermo").get_json(); assert lst["wifi"] == {"saved": True, "ssid": "Hanss WLAN", "has_pass": True} and "geheim1234" not in json.dumps(lst)
# 3) Weiteres Thermometer mit leerem Passwortfeld: gemerktes Passwort wird benutzt
r = A.post("/api/thermo", json={"name": "Garten", "interval": 30, "wifi": {"ssid": "Hanss WLAN", "pass": "", "server": "http://192.168.50.40:5005"}}); assert r.status_code == 201
p = make_cfg.parse(base64.b64decode(r.get_json()["cfg"])); assert p["pass"] == "geheim1234" and p["interval"] == 30 and p["name"] == "Garten", p
# anderes WLAN, leeres Passwort: NICHT das gemerkte Passwort des anderen WLANs verwenden
r = A.post("/api/thermo", json={"name": "Keller", "wifi": {"ssid": "Anderes WLAN", "pass": "", "server": "http://192.168.50.40:5005"}}); assert r.status_code == 201
assert make_cfg.parse(base64.b64decode(r.get_json()["cfg"]))["pass"] == ""
# 4) feste IP
r = A.post("/api/thermo", json={"name": "Fix", "wifi": {"ssid": "X", "pass": "geheim1234", "server": "http://192.168.50.40:5005", "ip": {"addr": "192.168.50.60", "gw": "192.168.50.1"}}}); assert r.status_code == 201
assert make_cfg.parse(base64.b64decode(r.get_json()["cfg"]))["ip"] == {"addr": "192.168.50.60", "gw": "192.168.50.1", "mask": "255.255.255.0", "dns": "192.168.50.1"}
# 5) Eingabefehler: 400 und es wird KEIN Thermometer angelegt
n = len(thermo.load())
for bad in ({"ssid": ""}, {"ssid": "x" * 40}, {"pass": "kurz"}, {"server": "https://x.de/pfad"}, {"server": "http://x/pfad"}, {"ip": {"addr": "999.1.1.1", "gw": "192.168.50.1"}}):
    r = post(**bad); assert r.status_code == 400 and r.get_json()["error"], (bad, r.get_json())
assert len(thermo.load()) == n
# 6) Vergessen
assert A.delete("/api/thermo_wifi").get_json()["wifi"]["saved"] is False and not os.path.exists(thermo.WIFI_PATH)
# 7) Rechte
L = webapp.app.test_client(); webapp.users.create("lese", "lesepass123", {"dashboard": "write"}); L.post("/login", data={"username": "lese", "password": "lesepass123"})
assert L.delete("/api/thermo_wifi").status_code == 403 and L.post("/api/thermo", json={"name": "x", "wifi": {}}).status_code == 403
# 8) ohne WLAN-Angaben (frueher "Ohne PC einrichten") gibt es keinen Weg mehr: 400, nichts angelegt
n = len(thermo.load()); r = A.post("/api/thermo", json={"name": "Handy", "interval": 15}); assert r.status_code == 400 and len(thermo.load()) == n
assert A.post("/api/thermo/t-abcd1234/key").status_code in (404, 405)
print("THERMO WLAN OK")
