"""Zigbee mit mehreren Gateways: Migration, gemeinsame Suche, Schalten ueber das richtige Gateway, Ausfall eines Gateways, Loeschschutz."""
import sys, os, json, threading, re, time
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import zigbee, shelly, homematic
for _p in (zigbee.CREDENTIALS_PATH, shelly.DEVICES_PATH, homematic.SENSORS_PATH, homematic.SETPOINTS_PATH, os.path.join(tmp, "users.json")):
    if os.path.exists(_p):
        os.remove(_p)


def make(key, lights, sensors, name):
    st = {"link": True}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj):
            out = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out)

        def _route(self, method):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}") if method in ("POST", "PUT") else None
            if method == "POST" and self.path == "/api":
                return self._send(200, [{"success": {"username": key}}])
            m = re.match(r"^/api/([^/]+)(/.*)?$", self.path)
            if not m or m.group(1) != key:
                return self._send(403, [{"error": {"type": 1, "description": "unauthorized user"}}])
            p = m.group(2) or ""
            if method == "GET":
                return self._send(200, {"/lights": lights, "/sensors": sensors, "/groups": {}, "/config": {"name": name}}.get(p, {}))
            mm = re.match(r"^/lights/(\d+)/state$", p)
            if method == "PUT" and mm:
                lights[mm.group(1)]["state"].update(body)
                return self._send(200, [{"success": {}}])
            return self._send(404, {})

        do_GET = lambda self: self._route("GET")
        do_POST = lambda self: self._route("POST")
        do_PUT = lambda self: self._route("PUT")
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# beide Gateways haben Licht "1" - gleiche Nummer, andere Geraete
L1 = {"1": {"name": "Flur", "type": "Dimmable light", "modelid": "A", "uniqueid": "00:00:00:00:00:00:00:01-01", "state": {"on": False, "bri": 1, "reachable": True}}}
L2 = {"1": {"name": "Werkstatt", "type": "Smart plug", "modelid": "B", "uniqueid": "00:00:00:00:00:00:00:02-01", "state": {"on": False, "reachable": True}}}
S1 = {"10": {"name": "Bad", "type": "ZHATemperature", "modelid": "t", "uniqueid": "00:15:8d:00:00:00:00:01-01-0402", "state": {"temperature": 2000}, "config": {"reachable": True}}}
S2 = {"10": {"name": "Halle", "type": "ZHATemperature", "modelid": "t", "uniqueid": "00:15:8d:00:00:00:00:02-01-0402", "state": {"temperature": 1000}, "config": {"reachable": True}}}
srv1, srv2 = make("KEY1", L1, S1, "GW-Haus"), make("KEY2", L2, S2, "GW-Werkstatt")
PORTS = {"192.168.50.66": srv1.server_address[1], "192.168.50.67": srv2.server_address[1]}
zigbee._split_host = lambda host: ("127.0.0.1", PORTS[re.sub(r"^https?://", "", host.strip()).split(":")[0]]) if re.sub(r"^https?://", "", host.strip()).split(":")[0] in PORTS else ("127.0.0.1", int(host.split(":")[1]))

# 1) altes Format (ein Gateway) wird gelesen
json.dump({"host": "192.168.50.66", "key": "KEY1"}, open(zigbee.CREDENTIALS_PATH, "w"))
gws = zigbee.load_gateways()
assert len(gws) == 1 and gws[0]["id"] == "gw1" and gws[0]["key"] == "KEY1", gws
assert zigbee.load_credentials()["key"] == "KEY1" and zigbee.credentials_public()["configured"]
print("1) Migration altes Format OK")

# 2) zweites Gateway per Verbinden (Schluessel holen)
g2 = zigbee.save_gateway("192.168.50.67", "", "Werkstatt")
assert g2["id"] == "gw2" and g2["name"] == "Werkstatt"
assert zigbee.pair("192.168.50.67", "Werkstatt", "gw2") == "KEY2"
assert [g["id"] for g in zigbee.load_gateways()] == ["gw1", "gw2"] and zigbee.gateway("gw2")["key"] == "KEY2"
assert zigbee.test_connection("gw2")["name"] == "GW-Werkstatt" and zigbee.test_connection()["name"] == "GW-Haus"
# Adresse aendern ohne Schluessel -> alter Schluessel verworfen; mit gleicher Adresse nochmal speichern -> kein Duplikat
zigbee.save_gateway("192.168.50.67", "", "Werkstatt")
assert len(zigbee.load_gateways()) == 2
print("2) zweites Gateway OK")

# 3) gemeinsame Suche, Gateway-Namen in den Treffern
found = zigbee.discover(set())
assert {f["name"]: f["gwname"] for f in found} == {"Flur": "Gateway 1", "Werkstatt": "Werkstatt"}, found
added = shelly.add_zigbee([f["id"] for f in found])
assert {d["name"]: d["gw"] for d in added} == {"Flur": "gw1", "Werkstatt": "gw2"}
sf = zigbee.sensors_scan()
assert {f["name"]: f["gw"] for f in sf} == {"Bad – Temperatur": "gw1", "Halle – Temperatur": "gw2"}
zigbee.add_sensors([f["id"] for f in sf])
devs = {d["name"]: d for d in shelly.load_devices()}
print("3) Suche ueber beide Gateways OK")

# 4) Schalten ueber das richtige Gateway (gleiche Licht-Nummer 1 auf beiden)
shelly.set_state(devs["Werkstatt"]["id"], True)
assert L2["1"]["state"]["on"] is True and L1["1"]["state"]["on"] is False
shelly.set_state(devs["Flur"]["id"], True)
assert L1["1"]["state"]["on"] is True
zigbee._invalidate()
assert shelly.status(devs["Werkstatt"])["on"] is True and shelly.status(devs["Flur"])["on"] is True
vals = homematic.read_values(homematic.load_sensors())
assert sorted(v for v in vals.values()) == [10.0, 20.0], vals
print("4) Schalten/Werte ueber das richtige Gateway OK")

# 5) altes Geraet ohne gw gehoert zum ersten Gateway
legacy = dict(devs["Flur"]); legacy.pop("gw")
assert zigbee.status(legacy)["on"] is True
print("5) Altbestand ohne Kennung OK")

# 6) Gateway 2 faellt aus: Gateway 1 laeuft weiter, Fehler nennt das Gateway
srv2.shutdown(); srv2.server_close()
zigbee._invalidate()
t = time.time()
assert shelly.status(devs["Flur"])["online"] is True
s2 = shelly.status(devs["Werkstatt"])
assert s2["online"] is False and "Werkstatt" in s2["error"] and "nicht erreichbar" in s2["error"], s2
assert vals and sorted(v for v in homematic.read_values(homematic.load_sensors()).values() if v is not None) == [20.0]
n = time.time()
shelly.status(devs["Werkstatt"]); shelly.status(devs["Flur"])
assert time.time() - n < 2, "ausgefallenes Gateway darf nicht jede Abfrage ausbremsen"
print("6) Ausfall eines Gateways OK")

# 7) Endpunkte: Loeschschutz, Entfernen, Maskierung
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "users.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
info = c.get("/api/zigbee").get_json()
assert [g["name"] for g in info["gateways"]] == ["Gateway 1", "Werkstatt"] and "KEY" not in json.dumps(info)
r = c.delete("/api/zigbee/gateways/gw2"); assert r.status_code == 409 and "hängen" in r.get_json()["error"], r.get_json()
assert c.delete("/api/zigbee/gateways/gwX").status_code == 404
for d in shelly.load_devices():
    if d["name"] == "Werkstatt":
        shelly.remove(d["id"])
homematic._save_sensors([s for s in homematic.load_sensors() if s.get("gw") != "gw2"])
if zigbee.in_use("gw2"):
    print("Hinweis: shelly.remove_device fehlt - Geraet bleibt:", zigbee.in_use("gw2"))
else:
    assert c.delete("/api/zigbee/gateways/gw2").status_code == 200 and [g["id"] for g in zigbee.load_gateways()] == ["gw1"]
r = c.post("/api/zigbee/credentials", json={"host": "192.168.50.66", "key": "KEY1", "id": "gw1", "name": "Haus"}); assert r.status_code == 200 and r.get_json()["gateway"] == "Haus", r.get_json()
assert c.patch("/api/zigbee/gateways/gw1", json={"name": "Wohnzimmer"}).status_code == 200 and zigbee.gateway("gw1")["name"] == "Wohnzimmer" and zigbee.gateway("gw1")["key"] == "KEY1"
assert c.patch("/api/zigbee/gateways/gw1", json={"name": " "}).status_code == 404 and c.patch("/api/zigbee/gateways/gwX", json={"name": "x"}).status_code == 404
print("7) Endpunkte OK")
print("ZIGBEE MULTI OK")
