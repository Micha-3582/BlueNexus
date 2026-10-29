"""Alle Symbole bei allem; Logbuch zeigt das eingestellte Symbol."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, wol, virtual, devicelog
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
json.dump([{"id": "d1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Lampe", "icon": "💡", "model": "T", "show": True},
           {"id": "d2", "kind": "tasmota", "mac": "BB", "channel": 1, "gen": 0, "ip": "192.168.50.91", "name": "Ohne Symbol", "model": "T", "show": True}], open(shelly.DEVICES_PATH, "w"))
homematic._save_sensors([{"id": "s1", "kind": "motion", "address": "A", "interface": "x", "datapoint": "M", "binary": True, "unit": "", "name": "Flur", "model": "m", "room": "", "icon": "🚶"},
                         {"id": "s2", "kind": "contact", "address": "B", "interface": "x", "datapoint": "S", "binary": True, "unit": "", "name": "Fenster", "model": "m", "room": ""}])
homematic._save_setpoints([{"id": "hmT-1", "address": "A:1", "interface": "x", "datapoint": "SET_POINT_TEMPERATURE", "min": 5, "max": 30, "model": "m", "room": "", "name": "Bad"}])
homematic._save_locks([{"id": "hmK-1", "address": "L:1", "interface": "x", "model": "m", "room": "", "name": "Haustür", "allow_open": False}])
wol._save([{"id": "w-1", "name": "PC", "icon": "💻", "mac": "AA:BB:CC:DD:EE:FF", "ip": "", "show": True}])
webapp.users = UserStore(os.path.join(tmp, "u_ic.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})

# 1) Eine Liste mit ALLEN Symbolen; alles, was sonst als Vorschlag stand, steckt darin (u. a. das laufende Maennchen)
icons = A.get("/api/shelly/icons").get_json()
assert len(icons) == len(set(icons)) and all(i in icons for i in ("🏃", "🧍", "🚶", "👤", "🏷️", "⏱️", "🔐", "🔌", "💡", "🔒", "🌡️")), [i for i in ("🏃", "🧍") if i not in icons]
for extra in ("🚪", "🏠", "🔑", "🚨", "📬", "🚗", "🚲", "🐕", "🐈", "🔥", "💦", "🌡️", "☀️", "⚡"):                                      # fruehere Sensor-Vorschlaege
    assert extra in icons, extra
# 2) Jedes Symbol bei jedem Ding einstellbar: Geraet, Sensor, Thermostat, Schloss, Rechner
assert A.patch("/api/shelly/d1", json={"icon": "🏃"}).status_code == 200 and next(d for d in shelly.load_devices() if d["id"] == "d1")["icon"] == "🏃"
assert A.patch("/api/sensors/s2", json={"icon": "🏃"}).status_code == 200
assert A.patch("/api/homematic/setpoints/hmT-1", json={"icon": "🏃"}).status_code == 200 and homematic.load_setpoints()[0]["icon"] == "🏃"
assert A.patch("/api/homematic/locks/hmK-1", json={"icon": "🏃"}).status_code == 200 and homematic.load_locks()[0]["icon"] == "🏃"
assert A.patch("/api/wol/w-1", json={"icon": "🏃"}).status_code == 200 and wol.load()[0]["icon"] == "🏃"
for url in ("/api/shelly/d1", "/api/homematic/setpoints/hmT-1", "/api/homematic/locks/hmK-1"):
    assert A.patch(url, json={"icon": "kein-symbol"}).status_code == 400, url                                                    # Unsinn weiter abgelehnt
assert L.patch("/api/homematic/locks/hmK-1", json={"icon": "🔑"}).status_code == 403 and L.patch("/api/homematic/setpoints/hmT-1", json={"icon": "🔑"}).status_code == 403
# 3) Logbuch: Eintraege tragen das EINGESTELLTE Symbol (aktuell, auch wenn es nachtraeglich geaendert wurde)
devicelog.log("aktor", "device:d1", "Lampe", "eingeschaltet", True, by="x")
devicelog.log("aktor", "device:d2", "Ohne Symbol", "eingeschaltet", True, by="x")
devicelog.log("sensor", "sensor:s1", "Flur", "Bewegung erkannt", True, by="Sensor")
devicelog.log("sensor", "sensor:s2", "Fenster", "offen", True, by="Sensor")
devicelog.log("thermostat", "setpoint:hmT-1", "Bad", "Solltemperatur 21 °C", True, by="x")
devicelog.log("sicherheit", "lock:hmK-1", "Haustür", "verriegelt", True, by="x")
devicelog.log("aktor", "wol:w-1", "PC", "aufgeweckt", True, by="x")
devicelog.log("sicherheit", "nfc:alert", "NFC", "Fremder", False, by="Fremder Zugriff")
devicelog.log("aktor", "device:geloescht", "Weg", "eingeschaltet", True, by="x")
e = {x["name"]: x for x in A.get("/api/devicelog?limit=50").get_json()["entries"]}
assert e["Lampe"]["icon"] == "🏃" and e["Ohne Symbol"]["icon"] is None                                                       # kein Symbol gesetzt: Oberflaeche nimmt den Standard
assert e["Flur"]["icon"] == "🚶" and e["Flur"]["skind"] == "motion" and e["Fenster"]["icon"] == "🏃" and e["Fenster"]["skind"] == "contact"
assert e["Bad"]["icon"] == "🏃" and e["Haustür"]["icon"] == "🏃" and e["PC"]["icon"] == "🏃"
assert e["NFC"]["icon"] is None and e["Weg"]["icon"] is None                                                                  # Meldungen ohne Geraet / geloeschtes Geraet: Standard
shelly.update("d1", icon="🔥"); assert next(x for x in A.get("/api/devicelog?limit=50").get_json()["entries"] if x["name"] == "Lampe")["icon"] == "🔥"
assert L.get("/api/devicelog").status_code == 403                                                                             # weiter nur Administratoren
print("SYMBOLE OK")
