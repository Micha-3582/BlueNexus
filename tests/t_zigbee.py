"""Zigbee (Phoscon/deCONZ): Pairing, Lichter/Steckdosen, Sensoren, Thermostate, Cache, Fehlerfaelle - gegen einen Mock-Gateway."""
import sys, os, json, threading, time, re
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import zigbee, shelly, homematic
for _p in (zigbee.CREDENTIALS_PATH, shelly.DEVICES_PATH, homematic.SENSORS_PATH, homematic.SETPOINTS_PATH, os.path.join(tmp, "users.json")):
    if os.path.exists(_p):
        os.remove(_p)                                                  # sauberer Start (das Testverzeichnis bleibt zwischen Laeufen bestehen)

KEY = "ABCDEF1234"
MAC = "00:15:8d:00:02:a4:3c:7e"
state = {"link": False, "requests": 0}
LIGHTS = {
    "1": {"name": "Flurlicht", "type": "Dimmable light", "modelid": "LWB010", "uniqueid": "00:17:88:01:00:aa:bb:01-0b", "state": {"on": False, "bri": 100, "reachable": True}},
    "2": {"name": "Steckdose Bad", "type": "Smart plug", "modelid": "lumi.plug", "uniqueid": MAC + "-01", "state": {"on": True, "reachable": True}},
    "3": {"name": "Rollo", "type": "Window covering device", "modelid": "X", "uniqueid": "00:00:00:00:00:00:00:03-01", "state": {"lift": 50, "reachable": True}},
    "4": {"name": "Gartenlicht", "type": "On/Off light", "modelid": "Y", "uniqueid": "00:00:00:00:00:00:00:04-01", "state": {"on": False, "reachable": False}},
}
SENSORS = {
    "10": {"name": "Fenster Bad", "type": "ZHAOpenClose", "modelid": "lumi.sensor_magnet", "uniqueid": "00:15:8d:00:02:aa:aa:aa-01-0006", "state": {"open": False}, "config": {"reachable": True}},
    "11": {"name": "Wohnzimmer", "type": "ZHATemperature", "modelid": "lumi.weather", "uniqueid": "00:15:8d:00:02:bb:bb:bb-01-0402", "state": {"temperature": 2146}, "config": {"reachable": True}},
    "12": {"name": "Wohnzimmer", "type": "ZHAHumidity", "modelid": "lumi.weather", "uniqueid": "00:15:8d:00:02:bb:bb:bb-01-0405", "state": {"humidity": 5812}, "config": {"reachable": True}},
    "13": {"name": "Flur Bewegung", "type": "ZHAPresence", "modelid": "lumi.motion", "uniqueid": "00:15:8d:00:02:cc:cc:cc-01-0406", "state": {"presence": True}, "config": {"reachable": False}},
    "14": {"name": "Steckdose Bad", "type": "ZHAPower", "modelid": "lumi.plug", "uniqueid": MAC + "-01-0b04", "state": {"power": 42.5}, "config": {"reachable": True}},
    "15": {"name": "Bad Heizkoerper", "type": "ZHAThermostat", "modelid": "eTRV", "uniqueid": "00:15:8d:00:02:dd:dd:dd-01-0201", "state": {"on": False}, "config": {"heatsetpoint": 2100, "reachable": True}},
    "16": {"name": "Taster", "type": "ZHASwitch", "modelid": "lumi.remote", "uniqueid": "00:15:8d:00:02:ee:ee:ee-01-0012", "state": {"buttonevent": 1002}, "config": {}},
}
GROUPS = {"1": {"name": "Bad", "lights": ["2"]}}


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
        state["requests"] += 1
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}") if method in ("POST", "PUT") else None
        path = self.path
        if method == "POST" and path == "/api":
            if not state["link"]:
                return self._send(403, [{"error": {"type": 101, "description": "link button not pressed"}}])
            return self._send(200, [{"success": {"username": KEY}}])
        m = re.match(r"^/api/([^/]+)(/.*)?$", path)
        if not m or m.group(1) != KEY:
            return self._send(403, [{"error": {"type": 1, "description": "unauthorized user"}}])
        p = m.group(2) or ""
        if method == "GET":
            return self._send(200, {"/lights": LIGHTS, "/sensors": SENSORS, "/groups": GROUPS, "/config": {"name": "Phoscon-GW", "websocketport": 443}}.get(p, {}))
        mm = re.match(r"^/lights/(\d+)/state$", p)
        if method == "PUT" and mm:
            LIGHTS[mm.group(1)]["state"].update(body)
            return self._send(200, [{"success": {f"/lights/{mm.group(1)}/state/on": body.get("on")}}])
        mm = re.match(r"^/sensors/(\d+)/config$", p)
        if method == "PUT" and mm:
            if body.get("heatsetpoint") is not None and not (500 <= body["heatsetpoint"] <= 3000):
                return self._send(200, [{"error": {"type": 7, "description": "invalid value"}}])
            SENSORS[mm.group(1)]["config"].update(body)
            return self._send(200, [{"success": {}}])
        return self._send(404, {})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# 1) Adress-Pruefung (echter Code)
for bad in ("127.0.0.1", "8.8.8.8", "gateway.local", "", "192.168.50.66:99999", "http://10.0.0.1.evil.com"):
    try:
        zigbee.save_credentials(bad)
        raise AssertionError(f"{bad!r}")
    except zigbee.ZigbeeError:
        pass
zigbee.save_credentials("192.168.50.66")
assert zigbee.load_credentials()["host"] == "192.168.50.66" and {k: v for k, v in zigbee.credentials_public().items() if k != "gateways"} == {"configured": False, "host": "192.168.50.66", "key_set": False}
zigbee.save_credentials("http://192.168.50.66:8080")
assert zigbee.load_credentials()["host"] == "192.168.50.66:8080"
print("1) Adress-Pruefung OK")

zigbee._save_gateways([])                                    # Mock-Adresse soll kein zweites Gateway werden
_real_split = zigbee._split_host
zigbee._split_host = lambda host: ("127.0.0.1", PORT)          # ab hier: Mock
# 2) Pairing
try:
    zigbee.pair("192.168.50.66")
    raise AssertionError("ohne Freigabe")
except zigbee.ZigbeeError as e:
    assert "App autorisieren" in str(e)
state["link"] = True
assert zigbee.pair("192.168.50.66") == KEY and zigbee.load_credentials()["key"] == KEY
assert zigbee.credentials_public()["configured"] and "key" not in zigbee.credentials_public()
info = zigbee.test_connection()
assert (info["name"], info["devices"]) == ("Phoscon-GW", 11), info
zigbee.save_credentials("192.168.50.66", "FALSCH")
try:
    zigbee.test_connection()
    raise AssertionError("falscher Schluessel")
except zigbee.ZigbeeError as e:
    assert "Schlüssel" in str(e)
zigbee.save_credentials("192.168.50.66", KEY)
print("2) Pairing, Test, falscher Schluessel OK")

# 3) Lichter/Steckdosen
found = zigbee.discover(set())
assert {f["name"] for f in found} == {"Flurlicht", "Steckdose Bad", "Gartenlicht"}, found                  # Rollo (kein on/off) fehlt
assert next(f for f in found if f["name"] == "Steckdose Bad")["room"] == "Bad"
added = shelly.add_zigbee([f["id"] for f in found])
assert len(added) == 3 and shelly.add_zigbee([added[0]["id"]]) == []
dev = {d["name"]: d for d in shelly.load_devices()}
assert dev["Steckdose Bad"]["icon"] == "🔌" and dev["Flurlicht"]["icon"] == "💡" and dev["Flurlicht"]["kind"] == "zigbee"
st = shelly.status(dev["Steckdose Bad"])
assert st == {"online": True, "on": True, "power": 42.5}, st                                              # Leistung vom ZHAPower-Sensor
assert shelly.status(dev["Flurlicht"]) == {"online": True, "on": False, "power": None}
g = shelly.status(dev["Gartenlicht"])
assert g["online"] is False and "nicht erreichbar" in g["error"]
r = shelly.set_state(dev["Flurlicht"]["id"], True, timer_s=600)
assert r["on"] is True and LIGHTS["1"]["state"]["on"] is True
shelly.set_state(dev["Flurlicht"]["id"], False)
assert LIGHTS["1"]["state"]["on"] is False
zigbee._invalidate()
n = state["requests"]
shelly.status(dev["Flurlicht"]); shelly.status(dev["Steckdose Bad"]); shelly.status(dev["Flurlicht"])
assert state["requests"] - n <= 3, state["requests"] - n                                                   # eine Abfrage (lights+sensors+groups) fuer alles
print("3) Lichter/Steckdosen: suchen, anlegen, Status+Leistung, schalten, Cache OK")

# 4) Sensoren
sf = zigbee.sensors_scan()
assert {f["kind"] for f in sf} == {"contact", "temperature", "humidity", "motion", "power"} and len(sf) == 5, sf   # Thermostat/Taster nicht dabei
assert next(f for f in sf if f["kind"] == "temperature")["name"] == "Wohnzimmer – Temperatur"
assert len(zigbee.add_sensors([f["id"] for f in sf])) == 5 and zigbee.add_sensors([sf[0]["id"]]) == []
reg = {s["id"]: s for s in homematic.load_sensors()}
assert all(s["source"] == "zigbee" for s in reg.values()) and [s for s in reg.values() if s["kind"] == "contact"][0]["invert"] is True
zigbee._invalidate()
vals = homematic.read_values(homematic.load_sensors())
byk = {reg[i]["kind"]: v for i, v in vals.items()}
assert byk == {"contact": True, "temperature": 21.5, "humidity": 58.1, "motion": None, "power": 42.5}, byk     # Fenster zu + Standard-Umkehr -> TRUE; Bewegung nicht erreichbar -> None
print("4) Sensoren: suchen, anlegen, Werte (Umkehr, nicht erreichbar) OK")

# 5) Thermostate
tf = zigbee.setpoints_scan()
assert [f["name"] for f in tf] == ["Bad Heizkoerper"]
assert len(zigbee.add_setpoints([tf[0]["id"]])) == 1
zigbee._invalidate()
assert [x["value"] for x in homematic.list_setpoints_with_values()] == [21.0]
res = homematic.set_setpoints(["*"], 0)                                      # 0 Grad -> auf 5 Grad (Bereich) begrenzt
assert res == [("Bad Heizkoerper", 5.0, None)] and SENSORS["15"]["config"]["heatsetpoint"] == 500, res
res = homematic.set_setpoints([tf[0]["id"]], 99)
assert res[0][1] == 30.0 and SENSORS["15"]["config"]["heatsetpoint"] == 3000
print("5) Thermostate: Suche, Sollwert (begrenzt) OK")

# 6) Endpunkte
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "users.json"))
webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client()
c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
fam = c.get("/api/device-families").get_json()["families"]
assert fam["zigbee"] is True and fam["shelly"] is False                                                    # Zigbee: Geraete/Zugang vorhanden
info = c.get("/api/zigbee").get_json()
assert info["configured"] is True and "key" not in json.dumps(info).lower().replace("key_set", "")
zigbee._split_host = _real_split
assert c.post("/api/zigbee/credentials", json={"host": "8.8.8.8"}).status_code == 400
zigbee._split_host = lambda host: ("127.0.0.1", PORT)
assert c.post("/api/zigbee/credentials", json={"host": "192.168.50.66", "key": KEY}).get_json()["devices"] == 11
assert len(c.post("/api/zigbee/scan").get_json()) == 3 and c.post("/api/zigbee/sensors/scan").status_code == 200 and c.post("/api/zigbee/setpoints/scan").status_code == 200
assert c.post("/api/zigbee/add", json={"ids": ["zb-nope"]}).status_code == 400
sensors = c.get("/api/sensors").get_json()
assert len(sensors) == 5 and {s["source"] for s in sensors} == {"zigbee"}
assert any(x["source"] == "zigbee" for x in c.get("/api/homematic/setpoints").get_json())
print("6) Endpunkte OK")

# 7) Gateway weg -> verstaendliche Fehler, nichts crasht
srv.shutdown()
srv.server_close()
zigbee._invalidate()
s1 = shelly.status(dev["Flurlicht"])
assert s1["online"] is False and "nicht erreichbar" in s1["error"]
try:
    shelly.set_state(dev["Flurlicht"]["id"], True)
    raise AssertionError("Gateway weg")
except shelly.ShellyError as e:
    assert "Gateway" in str(e)
assert set(homematic.read_values(homematic.load_sensors()).values()) == {None}
print("7) Gateway weg OK")
print("ZIGBEE OK")
