"""Geraete-Logbuch: Bedienung (Hand/Regel/Automatik/Alexa/Freigabe), Thermostate, Schloesser, Rollladen, Sensor-Wechsel, Rechte, Hinweise, Kappung."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import devicelog, shelly, tasmota, homematic, virtual, wol
from auth import UserStore

webapp.opslog.log = lambda *a, **k: None
json.dump([{"id": "t1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Steckdose", "icon": "🔌", "model": "T", "show": True, "users": ["anna"]},
           {"id": "t2", "kind": "tasmota", "mac": "BB", "channel": 1, "gen": 0, "ip": "192.168.50.91", "name": "Nur Admin", "icon": "🔌", "model": "T", "show": True, "users": []}], open(shelly.DEVICES_PATH, "w"))
state = {"fail": False}
def fake(ip, cmnd, timeout, auth=None):
    if state["fail"]: raise tasmota.requests.ConnectionError("weg")
    return {"POWER": "ON" if cmnd.lower().rstrip().endswith("on") else "OFF"}
tasmota._cmd = fake
tasmota._pulse_zero.clear()
homematic._save_setpoints([{"id": "hmT-1", "address": "A:1", "interface": "x", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "m", "room": "", "name": "Bad", "users": ["anna"]}])
homematic._save_locks([{"id": "hmK-1", "address": "L:1", "interface": "x", "model": "m", "room": "", "name": "Haustür", "allow_open": False}])
homematic._save_blinds([{"id": "hmR-1", "address": "R:1", "interface": "x", "model": "m", "room": "", "name": "Terrasse", "icon": "🪟", "users": ["anna"]}])
homematic._call = lambda method, params=None: {}
homematic._get_value = lambda itf, addr, key: 1
homematic._unreach = lambda x: False
homematic._save_sensors([{"id": "hm-d", "kind": "contact", "address": "D", "interface": "x", "datapoint": "STATE", "unit": "", "binary": True, "name": "Fenster Bad", "model": "m", "room": "", "users": ["anna"]},
                         {"id": "hm-m", "kind": "motion", "address": "M", "interface": "x", "datapoint": "MOTION", "unit": "", "binary": True, "name": "Flur Bewegung", "model": "m", "room": "", "users": []},
                         {"id": "hm-t", "kind": "temperature", "address": "T", "interface": "x", "datapoint": "T", "unit": "°C", "binary": False, "name": "Temp", "model": "m", "room": ""}])

webapp.users = UserStore(os.path.join(tmp, "u_dl.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass1", {"dashboard": "write", "settings_geraete": "read"})
webapp.users.create("nodash", "nodashpass1", {"dashboard": "read"})
webapp.users.create("nosec", "nosecpass123", {"dashboard": "write", "settings_geraete": "read", "smarthome_sicherheit": "none"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, M, N, S = login("admin", "adminpass1"), login("anna", "annapass1"), login("nodash", "nodashpass1"), login("nosec", "nosecpass123")
get = lambda c, q="": c.get("/api/devicelog" + q).get_json()["entries"]

assert get(A) == []
# 1) Von Hand ueber die Oberflaeche: Konto steht drin
r = M.post("/api/shelly/t1/switch", json={"on": True}); assert r.status_code == 200, r.get_data(as_text=True)
e = get(A)[0]; assert e["ref"] == "device:t1" and e["name"] == "Steckdose" and "eingeschaltet" in e["text"] and e["cat"] == "aktor" and "anna" in e["by"].lower() and e["ok"] is True, e
# 2) Durch eine Regel / Automatik / Alexa / Freigabe: Aktor wird genannt
with devicelog.actor("Regel „Abend“"): shelly.set_state("t1", False)
assert get(A)[0]["by"] == "Regel „Abend“" and "ausgeschaltet" in get(A)[0]["text"]
fn = devicelog.as_actor(lambda x: "Überschuss-Automatik")(lambda x: shelly.set_state("t1", True, 600)); fn(1)
assert get(A)[0]["by"] == "Überschuss-Automatik" and "Timer 10 min" in get(A)[0]["text"], get(A)[0]
# 3) Fehlschlag wird als Fehler protokolliert und die Ausnahme bleibt
state["fail"] = True
try: shelly.set_state("t1", True); raise SystemExit("haette scheitern muessen")
except shelly.ShellyError: pass
f = get(A)[0]; assert f["ok"] is False and "fehlgeschlagen" in f["text"], f
state["fail"] = False
# 4) Thermostat, Schloss, Rollladen
homematic.set_setpoints(["hmT-1"], 21.5)
assert get(A)[0]["cat"] == "thermostat" and get(A)[0]["ref"] == "setpoint:hmT-1" and "21,5" in get(A)[0]["text"].replace(".", ",") or "21.5" in get(A)[0]["text"], get(A)[0]
homematic.lock_action("hmK-1", "lock")
assert get(A)[0]["cat"] == "sicherheit" and get(A)[0]["text"] == "verriegelt" and get(A)[0]["ref"] == "lock:hmK-1"
try: homematic.lock_action("hmK-1", "unlock"); raise SystemExit("allow_open fehlt")
except homematic.HomematicError: pass
assert get(A)[0]["text"] == "verriegelt" or "fehlgeschlagen" in get(A)[0]["text"]
homematic.lock_action("hmK-1", "open", manual=True); assert get(A)[0]["text"] == "geöffnet"
homematic.blind_set("hmR-1", 40); assert get(A)[0]["text"] == "Rollladen auf 40 % gefahren" and get(A)[0]["ref"] == "blind:hmR-1"
homematic.blind_stop("hmR-1"); assert get(A)[0]["text"] == "Rollladen angehalten"
# 5) Sensoren: erste Abfrage still, danach nur Wechsel; Bewegung nur "erkannt"; Zahlen nie
sens = {s["id"]: s for s in homematic.load_sensors()}
n = len(get(A, "?cat=sensor"))
homematic._get_value = lambda itf, addr, key: 0; homematic._value_cache.clear()
homematic.read_sensor(sens["hm-d"]); homematic.read_sensor(sens["hm-t"]); homematic.read_sensor(sens["hm-m"])
assert len(get(A, "?cat=sensor")) == n                                                   # nur Ausgangszustand gemerkt
homematic._get_value = lambda itf, addr, key: 1; homematic._value_cache.clear()
homematic.read_sensor(sens["hm-d"]); homematic.read_sensor(sens["hm-m"]); homematic.read_sensor(sens["hm-t"])
se = get(A, "?cat=sensor"); assert {x["name"]: x["text"] for x in se} == {"Fenster Bad": "offen", "Flur Bewegung": "Bewegung erkannt"}, se
homematic._get_value = lambda itf, addr, key: 0; homematic._value_cache.clear()
homematic.read_sensor(sens["hm-d"]); homematic.read_sensor(sens["hm-m"])
se = get(A, "?cat=sensor"); assert se[0]["name"] == "Fenster Bad" and se[0]["text"] == "geschlossen" and sum(1 for x in se if x["name"] == "Flur Bewegung") == 1     # "keine Bewegung" wird nicht geloggt
# 6) Virtueller Schalter, Wake-on-LAN
v = virtual.add("Gong", "button"); virtual.press(v["id"]); assert get(A)[0]["text"] == "gedrückt" and get(A)[0]["name"] == "Gong"
# 7) Filter + Suche
assert all(x["cat"] == "thermostat" for x in get(A, "?cat=thermostat")) and get(A, "?cat=thermostat")
assert all("terrasse" in (x["name"] + x["text"] + x["by"]).lower() for x in get(A, "?q=terrasse")) and get(A, "?q=terrasse")
assert get(A, "?cat=gibtsnicht") and len(get(A, "?limit=3")) == 3
# 8) Nur Administratoren: normale Benutzer (auch mit Schreibrechten, auch Anna) sehen weder Logbuch noch "zuletzt"-Hinweise
for cl in (M, N, S):
    assert cl.get("/api/devicelog").status_code == 403 and cl.get("/api/devicelog/last").status_code == 403, cl
assert webapp.app.test_client().get("/api/devicelog").status_code in (401, 302, 403)
with devicelog.actor("x"): shelly.set_state("t2", True)
# 9) Admin: "zuletzt" je Geraet (ohne Sensoren)
la = A.get("/api/devicelog/last").get_json()
assert "device:t1" in la and "lock:hmK-1" in la and "sensor:hm-d" not in la and "device:t2" in la
# 10) Datei wird begrenzt, bleibt lesbar
devicelog.MAX_BYTES = 6000
for i in range(120): devicelog.log("aktor", "device:t1", "Steckdose", f"Test {i}")
assert os.path.getsize(devicelog.PATH) < 9000 and get(A)[0]["text"] == "Test 119"
# 11) Reiter vorhanden (Anna mit Lese-Recht) und Seite rendert
assert b"#logbuch" in A.get("/smarthome").data and b"#logbuch" not in M.get("/smarthome").data           # Reiter nur fuer Administratoren
print("GERAETE-LOGBUCH OK")
