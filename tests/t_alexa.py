"""Alexa-Anbindung (Hue-Emulation): Register, Freigabe, HTTP-Schnittstelle, SSDP, PIN-Schutz, Modul."""
import sys, os, json, socket, time, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import alexa, shelly, virtual, rules
alexa.ALEXA_PATH = os.path.join(tmp, "alexa.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "smarthome_einrichten": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")
def freeport(udp=False):
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM); s_.bind(("127.0.0.1", 0)); p_ = s_.getsockname()[1]; s_.close(); return p_

base = {"icon": "🔌", "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "mac": "A", "gen": 2, "channel": 0, "model": "x", "users": []}
shelly._save([{**base, "id": "d1", "name": "Flurlicht", "ip": "1.1.1.1"}, {**base, "id": "d2", "name": "Tuerschloss-Relais", "ip": "1.1.1.2", "pin_hash": "x", "pin_salt": "y"},
              {**base, "id": "d3", "name": "Monitor", "ip": "1.1.1.3", "switchable": False}])
sw = virtual.add("Warmwasser-Timer", "switch"); bt = virtual.add("Tueroeffner", "button"); pv = virtual.add("Geheim", "switch")
virtual.set_pin(pv["id"], "1234")
set_calls = []
shelly.set_state = lambda i, on, timer_s=None: set_calls.append((i, on, timer_s)) or {"ok": True}
shelly.list_with_status = lambda only_shown=False, ids=None, live=True: [{"id": "d1", "online": True, "on": True}] if (ids is None or "d1" in ids) else []

# --- Modul Alexa ist standardmaessig aus: kein Reiter, Bruecke aus
assert store.module_on("alexa") is False and not webapp.alexa_bridge.running
assert "alexa" not in [t["id"] for t in webapp._smarthome_tabs(webapp.auth.normalize_permissions({"smarthome_einrichten": "write"}))]

# --- Freigabe: nur schaltbare Geraete ohne PIN, nur Administratoren
el = A.get("/api/alexa").get_json()["eligible"]; names = {e["name"] for e in el}
assert names == {"Flurlicht", "Warmwasser-Timer", "Tueroeffner"}, names
assert I.get("/api/alexa").get_json()["eligible"] == [] and I.post("/api/alexa/devices", json={"kind": "shelly", "ref": "d1"}).status_code == 403
assert A.post("/api/alexa/devices", json={"kind": "shelly", "ref": "d2", "name": "x"}).status_code == 400
assert A.post("/api/alexa/devices", json={"kind": "virtual", "ref": pv["id"], "name": "x"}).status_code == 400
assert A.post("/api/alexa/devices", json={"kind": "shelly", "ref": "d1", "name": "  Flur   Licht ", "type": "light"}).status_code == 201
assert A.post("/api/alexa/devices", json={"kind": "shelly", "ref": "d1", "name": "Nochmal"}).status_code == 400
assert A.post("/api/alexa/devices", json={"kind": "virtual", "ref": sw["id"], "name": "flur licht"}).status_code == 400
assert A.post("/api/alexa/devices", json={"kind": "virtual", "ref": sw["id"], "name": "Warmwasser", "type": "plug"}).status_code == 201
assert A.post("/api/alexa/devices", json={"kind": "virtual", "ref": bt["id"], "name": "Tuer", "type": "kaputt"}).status_code == 400
assert A.post("/api/alexa/devices", json={"kind": "virtual", "ref": bt["id"], "name": "Tuer"}).status_code == 201
devs = {d["name"]: d for d in alexa.load()}; assert devs["Flur Licht"]["hid"] == 1 and devs["Warmwasser"]["type"] == "plug" and devs["Tuer"]["hid"] == 3
print("Freigabe OK")

# --- Bruecke auf freien Ports starten (Port 80 / Multicast nicht im Test)
b = webapp.alexa_bridge; b.http_port, b.ssdp_port, b.multicast = freeport(), freeport(True), False
assert A.post("/api/modules", json={"alexa": True}).status_code == 200 and b.running and not b.error, b.error
assert "alexa" in [t["id"] for t in webapp._smarthome_tabs(webapp.auth.normalize_permissions({"smarthome_einrichten": "write"}))]
BASE = f"http://127.0.0.1:{b.http_port}"
def http(method, path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        raw = r.read().decode()
        return r.status, (json.loads(raw) if raw.strip().startswith(("{", "[")) else raw)
st, x = http("GET", "/description.xml"); assert st == 200 and "Philips hue bridge" in x and f":{b.http_port}/" in x and "<UDN>uuid:2f402f80-da50-11e1-9b23-" in x
st, x = http("GET", "/api/config"); assert x["modelid"] == "BSB002" and "FFFE" in x["bridgeid"]
st, x = http("POST", "/api", {"devicetype": "alexa#echo"}); assert x == [{"success": {"username": alexa.username_for(b.serial)}}] and len(x[0]["success"]["username"]) == 40
st, x = http("POST", "/api", {"devicetype": "alexa#echo", "generateclientkey": True}); ck = x[0]["success"]["clientkey"]; assert len(ck) == 32 and ck == ck.upper()
st, x = http("GET", "/api/config"); assert x["apiversion"] == "1.17.0" and x["swversion"] == "01041302"      # alte Bridge-Version: Echo bleibt beim v1-Weg
st, x = http("GET", "/api/victron/lights"); assert set(x) == {"1", "2", "3"}
assert x["1"]["type"] == "Dimmable light" and x["1"]["name"] == "Flur Licht" and x["1"]["state"]["on"] is True and x["1"]["state"]["reachable"] is True
assert x["2"]["type"] == "Dimmable plug-in unit" and x["2"]["modelid"] == "Plug 01" and x["2"]["manufacturername"] == "OpenSource" and x["2"]["state"]["on"] is False and x["2"]["state"]["reachable"] is True
assert len({v["uniqueid"] for v in x.values()}) == 3
st, one = http("GET", "/api/anyuser/lights/2"); assert one["name"] == "Warmwasser"
assert all(v["state"]["reachable"] is True for v in x.values())                         # auch Geraete, die gerade offline sind, werden gemeldet
st, full = http("GET", "/api/victron"); assert set(full["lights"]) == {"1", "2", "3"} and "config" in full and full["groups"] == {}
st, x = http("GET", "/api/victron/lights/99"); assert "error" in x[0]
for p_ in ("groups", "scenes", "sensors", "rules", "schedules"):
    assert http("GET", f"/api/victron/{p_}")[1] == {}
print("Hue-Schnittstelle OK")

# --- Schalten per Sprache
st, x = http("PUT", "/api/victron/lights/1/state", {"on": False}); assert x == [{"success": {"/lights/1/state/on": False}}] and set_calls[-1] == ("d1", False, None)
st, x = http("PUT", "/api/victron/lights/1/state", {"on": True}); assert set_calls[-1] == ("d1", True, 0)
st, x = http("PUT", "/api/victron/lights/1/state", {"bri": 128}); assert set_calls[-1] == ("d1", True, 0) and any("bri" in list(e["success"])[0] for e in x)
st, x = http("PUT", "/api/victron/lights/2/state", {"on": True}); assert virtual.snapshot()[sw["id"]]["on"] is True
assert http("GET", "/api/victron/lights/2")[1]["state"]["on"] is True
http("PUT", "/api/victron/lights/2/state", {"on": False}); assert virtual.snapshot()[sw["id"]]["on"] is False
st, x = http("PUT", "/api/victron/lights/3/state", {"on": True}); assert virtual.snapshot()[bt["id"]]["pressed"] is True
n = len(set_calls); http("PUT", "/api/victron/lights/3/state", {"on": False}); assert len(set_calls) == n
assert b.seen > 5 and b.last_cmd
items = shelly.load_devices(); items[0]["pin_hash"], items[0]["pin_salt"] = "x", "y"; shelly._save(items)           # Geraet bekommt nachtraeglich eine PIN
n = len(set_calls); st, x = http("PUT", "/api/victron/lights/1/state", {"on": False}); assert "error" in x[0] and len(set_calls) == n
items = shelly.load_devices(); items[0].pop("pin_hash"); items[0].pop("pin_salt"); shelly._save(items)
shelly.set_state = lambda *a, **k: (_ for _ in ()).throw(shelly.ShellyError("offline"))
st, x = http("PUT", "/api/victron/lights/1/state", {"on": True}); assert "error" in x[0]
shelly.set_state = lambda i, on, timer_s=None: set_calls.append((i, on, timer_s)) or {"ok": True}
print("Schalten OK")

# --- SSDP: M-SEARCH wird beantwortet
u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(3)
u.sendto(b'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: urn:schemas-upnp-org:device:basic:1\r\n\r\n', ("127.0.0.1", b.ssdp_port))
data, _ = u.recvfrom(2048); t = data.decode()
assert t.startswith("HTTP/1.1 200 OK") and f":{b.http_port}/description.xml" in t and "hue-bridgeid:" in t and "IpBridge" in t, t
u.sendto(b'M-SEARCH * HTTP/1.1\r\nMAN: "ssdp:discover"\r\nST: urn:dial-multiscreen-org:service:dial:1\r\n\r\n', ("127.0.0.1", b.ssdp_port)); u.settimeout(0.6)
try:
    u.recvfrom(2048); raise SystemExit("fremde Suche darf nicht beantwortet werden")
except socket.timeout:
    pass
print("SSDP OK")

# --- Verwalten
hid = devs["Warmwasser"]["hid"]
assert A.patch(f"/api/alexa/devices/{hid}", json={"name": "Boiler", "type": "light"}).status_code == 200 and http("GET", "/api/victron/lights/2")[1]["name"] == "Boiler"
assert A.patch(f"/api/alexa/devices/{hid}", json={"name": "Flur Licht"}).status_code == 400 and I.patch(f"/api/alexa/devices/{hid}", json={"name": "x"}).status_code == 403
virtual.remove(sw["id"]); alexa.remove_ref("virtual", sw["id"])
assert "Boiler" not in {d["name"] for d in alexa.load()}
assert A.delete("/api/alexa/devices/1").status_code == 200 and A.delete("/api/alexa/devices/1").status_code == 404
d = A.get("/api/alexa").get_json(); assert d["module"] is True and d["status"]["running"] is True and d["devices"][0]["name"] == "Tuer"
alexa.add("shelly", "d1", "Flur", "light"); assert A.delete("/api/shelly/d1").status_code == 200 and not [x for x in alexa.load() if x["ref"] == "d1"]
print("Verwalten OK")

# --- Modul aus: Bruecke stoppt; Smart Home aus ebenso
assert A.post("/api/modules", json={"alexa": False}).status_code == 200 and not b.running
try:
    urllib.request.urlopen(BASE + "/description.xml", timeout=1); raise SystemExit("Bruecke laeuft noch")
except (urllib.error.URLError, OSError):
    pass
b.http_port, b.ssdp_port = freeport(), freeport(True)
A.post("/api/modules", json={"alexa": True}); assert b.running
A.post("/api/modules", json={"smarthome": False}); assert not b.running
A.post("/api/modules", json={"smarthome": True}); assert b.running
A.post("/api/modules", json={"alexa": False})
blocker = socket.socket(); blocker.bind(("0.0.0.0", 0)); blocker.listen(1); b.http_port = blocker.getsockname()[1]
A.post("/api/modules", json={"alexa": True}); assert not b.running and "nicht frei" in b.error and "Echo-Geräte brauchen Port 80" in b.error
assert "nicht frei" in A.get("/api/alexa").get_json()["status"]["error"]; blocker.close(); A.post("/api/modules", json={"alexa": False})
page = A.get("/smarthome").get_data(as_text=True); assert "alexa-card" in page and "Alexa (Sprachsteuerung)" in page
print("ALEXA OK")
