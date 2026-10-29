"""Homematic-Wandtaster: Taste kurz/lang gedrueckt als Sensor (nur per Push) und als Ausloeser fuer Ablaeufe."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, rules, flows
from datetime import datetime

devs = [{"interface": "BidCos-RF", "type": "HM-PB-2-WM55", "name": "Flur - Wandtaster", "id": 1, "channels": [
    {"address": "NEQ0009000:0", "channelType": "MAINTENANCE", "name": "x:0", "id": 10},
    {"address": "NEQ0009000:1", "channelType": "KEY", "name": "Flur unten", "id": 11},
    {"address": "NEQ0009000:2", "channelType": "KEY", "name": "Flur oben", "id": 12},
    {"address": "NEQ0009000:3", "channelType": "KEYMATIC", "name": "kein Taster", "id": 13},
    {"address": "CCU:5", "channelType": "VIRTUAL_KEY", "name": "virtuell", "id": 14}]}]
homematic._call = lambda m, p=None: devs if m == "Device.listAllDetail" else []
KEYDESC = {"PRESS_SHORT": {"OPERATIONS": 6}, "PRESS_LONG": {"OPERATIONS": 6}, "INSTALL_TEST": {"OPERATIONS": 4}}
KEYDESC_REL = {**KEYDESC, "PRESS_LONG_RELEASE": {"OPERATIONS": 6}}
homematic._param_desc = lambda iface, addr: KEYDESC if addr.split(":")[1] in ("1", "2") else {}
found = {f["id"]: f for f in homematic.discover_sensors(set())}
assert set(found) == {f"hmS-NEQ0009000-{c}-{dp}" for c in (1, 2) for dp in ("PRESS_SHORT", "PRESS_LONG")}, found.keys()    # (Loslassen nur, wenn der Kanal es meldet)
f = found["hmS-NEQ0009000-2-PRESS_LONG"]
assert f["kind"] == "key_long" and f["binary"] and f["name"] == "Flur oben – Taste lang gedrückt", f
print("Tasten gefunden OK")

sen = homematic.build_sensors(["hmS-NEQ0009000-2-PRESS_LONG"])[0]
assert "invert" not in sen
# ohne Push: unbekannt
homematic._push_on = False
assert homematic.read_sensor(sen) is None
homematic._push_on = True
homematic._push_state = {"BidCos-RF": {"ok": True, "ts": time.time()}}
assert homematic.push_active() and homematic.read_sensor(sen) is False                # kein Druck bisher
homematic._on_event("victron-BidCos-RF", "NEQ0009000:2", "PRESS_LONG", True)
assert homematic.read_sensor(sen) is True                                           # gerade gedrueckt
sh = {**sen, "id": "x", "datapoint": "PRESS_SHORT", "kind": "key_short"}
assert homematic.read_sensor(sh) is False                                           # kurz != lang
k = ("BidCos-RF", "NEQ0009000:2", "PRESS_LONG"); t, v = homematic._pushed[k]
homematic._pushed[k] = (t - homematic.KEY_HOLD_S - 1, v)
assert homematic.read_sensor(sen) is False                                          # nach 5 s wieder FALSE
print("Tastendruck lesen OK")

# Ablauf: lange oben -> Geraete an, 120 s warten, aus (wie das ioBroker-Skript)
body = {"name": "Flur lang oben", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "sensor", "sensor_id": sen["id"], "is": True}]},
        "then": [{"device_id": "a", "state": "on"}, {"type": "wait", "seconds": 120}, {"device_id": "a", "state": "off"}], "else": []}
r = rules.normalize_rule(body, "t1")
flows.STATE_PATH = os.path.join(tmp, "fs.json"); eng = flows.FlowEngine()
now = datetime(2026, 10, 4, 21, 0)
vals = {"v": False}
ctx = lambda: {"sensors": {sen["id"]: vals["v"]}, "sensor_info": {sen["id"]: sen}}
eng.step(now, ctx(), [r]); vals["v"] = True
ev = eng.step(now, ctx(), [r]); assert [e[0] for e in ev] == ["start"] and "lang gedrückt" in ev[0][2], ev
assert [x["step"].get("device_id") for x in eng.advance(1000.0)] == ["a"]
txt = rules.eval_condition(rules.normalize_condition({"type": "sensor", "sensor_id": sen["id"], "is": True}), {"now": now, "sensors": {sen["id"]: True}, "sensor_info": {sen["id"]: sen}})[1]
assert "lang gedrückt" in txt and "TRUE" in txt, txt
print("Ablauf OK")

# Seiten rendern
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
assert "key_long" in c.get("/rules").get_data(as_text=True) and "key_long" in c.get("/smarthome").get_data(as_text=True) and "key_long" in c.get("/").get_data(as_text=True)
print("TASTEN OK")

# Fehlersuche: letzte CCU-Meldungen
homematic._recent_events.clear()
homematic._on_event("victron-BidCos-RF", "NEQ0009000:2", "PRESS_LONG", True)
homematic._on_event("victron-BidCos-RF", "NEQ0009000:2", "RSSI_DEVICE", -60)          # Rauschen wird nicht gelistet
homematic._on_event("victron-BidCos-RF", "ABC:1", "STATE", False)
ev = homematic.recent_events()
assert [(e["address"], e["key"]) for e in ev] == [("ABC:1", "STATE"), ("NEQ0009000:2", "PRESS_LONG")], ev
homematic._save_sensors([{**sen, "name": "Flur oben lang"}])
assert homematic.recent_events()[1]["sensor"] == "Flur oben lang"
r = c.get("/api/homematic/events"); assert r.status_code == 200 and len(r.get_json()["events"]) == 2
assert "hm-events" in c.get("/smarthome").get_data(as_text=True)
print("EVENTS OK")

# Taster, die bei langem Druck nur das Loslassen melden
homematic._param_desc = lambda iface, addr: KEYDESC_REL if addr.endswith(":2") else (KEYDESC if addr.split(":")[1] == "1" else {})
f2 = {f["id"]: f for f in homematic.discover_sensors(set())}
assert "hmS-NEQ0009000-2-PRESS_LONG_RELEASE" in f2 and "hmS-NEQ0009000-1-PRESS_LONG_RELEASE" not in f2
rel = f2["hmS-NEQ0009000-2-PRESS_LONG_RELEASE"]; assert rel["kind"] == "key_long_release" and rel["name"].endswith("Taste lang losgelassen"), rel
homematic._push_on = True; homematic._push_state = {"BidCos-RF": {"ok": True, "ts": time.time()}}
relsen = homematic.build_sensors([rel["id"]])[0]
assert homematic.read_sensor(relsen) is False
homematic._on_event("victron-BidCos-RF", "NEQ0009000:2", "PRESS_LONG_RELEASE", True)
assert homematic.read_sensor(relsen) is True
print("LOSLASSEN OK")

# lang gedrueckt auch ueber PRESS_CONT (Taster ohne PRESS_LONG-Meldung)
homematic._pushed.clear()
assert homematic.read_sensor(sen) is False
homematic._on_event("victron-BidCos-RF", "NEQ0009000:2", "PRESS_CONT", True)
assert homematic.read_sensor(sen) is True and homematic.read_sensor(sh) is False
homematic._on_event("victron-BidCos-RF", "NEQ0009000:1", "PRESS_CONT", True)
assert homematic.read_sensor({**sen, "address": "NEQ0009000:3"}) is False            # andere Taste bleibt unberuehrt
print("CONT OK")

# HmIP-Klingelsignalsensor: Kanal KEY_TRANSCEIVER; als Kontakt/Schalter eingestellt ist STATE lesbar -> zusaetzlich "Eingang"
devs[:] = [{"interface": "HmIP-RF", "type": "HmIP-DSD-PCB", "name": "Klingeltaster", "id": 5, "channels": [
    {"address": "0026E0C998CD78:0", "channelType": "MAINTENANCE", "name": "x:0", "id": 50},
    {"address": "0026E0C998CD78:1", "channelType": "KEY_TRANSCEIVER", "name": "Klingeltaster", "id": 51}]}]
homematic._param_desc = lambda iface, addr: {"PRESS_SHORT": {"OPERATIONS": 6}, "PRESS_LONG": {"OPERATIONS": 6}, "STATE": {"OPERATIONS": 5}} if addr.endswith(":1") else {}
f = {x["id"]: x for x in homematic.discover_sensors(set())}
assert "hmS-0026E0C998CD78-1-STATE" in f and f["hmS-0026E0C998CD78-1-STATE"]["kind"] == "input" and f["hmS-0026E0C998CD78-1-STATE"]["binary"], f.keys()
homematic._param_desc = lambda iface, addr: {"PRESS_SHORT": {"OPERATIONS": 6}, "PRESS_LONG": {"OPERATIONS": 6}} if addr.endswith(":1") else {}
f = {x["id"]: x for x in homematic.discover_sensors(set())}
assert set(f) == {"hmS-0026E0C998CD78-1-PRESS_SHORT", "hmS-0026E0C998CD78-1-PRESS_LONG"}, f.keys()               # Tastermodus: wie bisher nur Tasten
print("KLINGELSENSOR OK")
