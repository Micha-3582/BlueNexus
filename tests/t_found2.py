"""Trefferlisten Tuya/Homematic/Zigbee: Name/Symbol werden beim Hinzufuegen uebernommen."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, zigbee, tuya
homematic.LOCKS_PATH = os.path.join(tmp, "locks.json"); homematic.SETPOINTS_PATH = os.path.join(tmp, "sp.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
IC = shelly.ICONS

# Homematic-Geraete
homematic.build_entries = lambda addrs: [{"id": homematic.entry_id(a), "kind": "homematic", "address": a, "interface": "x", "datapoint": "STATE", "power_addr": None, "mac": None,
                                          "gen": 0, "channel": 1, "model": "HmIP", "name": "Orig " + a, "room": "", "ip": a, "icon": IC[0]} for a in addrs]
r = c.post("/api/homematic/add", json={"addresses": ["A1:1", "A2:1"], "edits": {"A1:1": {"name": " Kaffee ", "icon": IC[2]}}})
assert r.status_code == 201 and r.get_json()["added"] == 2, r.get_json()
d = {x["address"]: x for x in shelly.load_devices()}
assert d["A1:1"]["name"] == "Kaffee" and d["A1:1"]["icon"] == IC[2] and d["A2:1"]["name"] == "Orig A2:1" and d["A2:1"]["icon"] == IC[0]
r = c.post("/api/homematic/add", json={"addresses": ["A3:1"], "edits": {"A3:1": {"icon": "nix"}}}); assert r.status_code == 400
assert "A3:1" not in {x["address"] for x in shelly.load_devices()}, "ungueltiges Symbol: nichts angelegt"

# Homematic-Sensoren (Symbol laenger frei) / Thermostate / Schloesser
homematic.build_sensors = lambda ids: [{"id": i, "kind": "temperature", "address": "s", "interface": "x", "datapoint": "T", "unit": "C", "binary": False, "model": "m", "room": "", "name": "Sensor " + i, "source": "ccu"} for i in ids]
r = c.post("/api/homematic/sensors/add", json={"ids": ["s1", "s2"], "edits": {"s1": {"name": "Bad", "icon": "🛁"}}}); assert r.status_code == 201
sens = {x["id"]: x for x in homematic.load_sensors()}
assert sens["s1"]["name"] == "Bad" and sens["s1"]["icon"] == "🛁" and sens["s2"]["name"] == "Sensor s2" and sens["s1"]["users"] == []
homematic._setpoint_scan = {"t1": {"id": "t1", "address": "a", "interface": "x", "datapoint": "S", "min": 5, "max": 30, "model": "m", "room": "", "name": "Thermo"}}
homematic._setpoint_scan_ts = 10 ** 12
r = c.post("/api/homematic/setpoints/add", json={"ids": ["t1"], "edits": {"t1": {"name": "Wohnzimmer", "icon": "ignoriert"}}}); assert r.status_code == 200, r.get_json()
assert homematic.load_setpoints()[0]["name"] == "Wohnzimmer"
homematic._lock_scan = {"l1": {"id": "l1", "address": "a", "interface": "x", "model": "m", "room": "", "name": "Schloss"}}; homematic._lock_scan_ts = 10 ** 12
r = c.post("/api/homematic/locks/add", json={"ids": ["l1"], "edits": {"l1": {"name": "Haustuer"}}}); assert r.status_code == 200
assert homematic.load_locks()[0]["name"] == "Haustuer" and homematic.load_locks()[0]["allow_open"] is False

# Zigbee
zigbee.build_entries = lambda ids: [{"id": "zb-" + i, "kind": "zigbee", "uniqueid": i, "mac": None, "gen": 0, "channel": 0, "model": "m", "name": "Lampe " + i, "room": "", "ip": "x", "icon": IC[0]} for i in ids]
r = c.post("/api/zigbee/add", json={"ids": ["u1"], "edits": {"zb-u1": {"name": "Stehlampe", "icon": IC[4]}}}); assert r.status_code == 200, r.get_json()
z = {x["id"]: x for x in shelly.load_devices()}["zb-u1"]; assert z["name"] == "Stehlampe" and z["icon"] == IC[4]
zigbee._sensor_scan = {"zs": {"id": "zs", "kind": "contact", "address": "a", "interface": "x", "datapoint": "o", "unit": "", "binary": True, "model": "m", "room": "", "name": "Fenster", "source": "zigbee"}}
r = c.post("/api/zigbee/sensors/add", json={"ids": ["zs"], "edits": {"zs": {"name": "Balkon", "icon": "🪟"}}}); assert r.status_code == 200
assert {x["id"]: x for x in homematic.load_sensors()}["zs"]["name"] == "Balkon"

# Tuya
shelly.add_tuya = lambda dev_id, ip="": (lambda e: (shelly._save(shelly.load_devices() + [e]), e)[1])({"id": f"tuya-{dev_id}-1", "kind": "tuya", "dev_id": dev_id, "name": "Gosund", "icon": IC[0], "channel": 0, "model": "x", "ip": "1.1.1.1", "mac": None, "gen": 0, "users": []})
r = c.post("/api/tuya/add", json={"dev_id": "abc", "ip": "", "edits": {"abc": {"name": "Waschmaschine", "icon": IC[1]}}}); assert r.status_code == 201, r.get_json()
t = {x["id"]: x for x in shelly.load_devices()}["tuya-abc-1"]; assert t["name"] == "Waschmaschine" and t["icon"] == IC[1]

# ohne edits wie bisher
r = c.post("/api/homematic/add", json={"addresses": ["A9:1"]}); assert r.status_code == 201
assert {x.get("address"): x for x in shelly.load_devices()}["A9:1"]["name"] == "Orig A9:1"
page = c.get("/smarthome").get_data(as_text=True); assert "foundList" in page and "zbAddDevices" not in page
print("FOUND2 OK")
