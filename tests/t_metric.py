"""Messwerte eines Geraets als Sensor (Klimaanlage: Innen-/Aussen-/Solltemperatur, Steckdose: Leistung), einzeln teilbar ohne das Geraet."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, share
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
share.SHARES_PATH = os.path.join(tmp, "shares.json"); share.SOURCES_PATH = os.path.join(tmp, "sources.json")
json.dump([{"id": "midea-1", "kind": "midea", "ip": "192.168.50.232", "name": "Wohnzimmer", "icon": "❄️", "model": "Midea Klimaanlage", "show": True},
           {"id": "tas-1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Steckdose", "icon": "🔌", "model": "T", "show": True},
           {"id": "rem-1", "kind": "remote", "source": "q-1", "rref": "device:x", "name": "Fremd", "icon": "x", "model": "von X", "show": True}], open(shelly.DEVICES_PATH, "w"))
state = {"midea": {"online": True, "on": False, "power": None, "info": "aus", "mode": "cool", "target_c": 30, "indoor_c": 20.5, "outdoor_c": 13}, "w": 7.3}
orig = shelly._status_live
shelly._status_live = lambda d: dict(state["midea"]) if d["id"] == "midea-1" else {"online": True, "on": True, "power": state["w"]}
webapp.users = UserStore(os.path.join(tmp, "u_m.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})
reset = lambda: (shelly._st_cache.clear(), shelly._down.clear(), homematic._value_cache.clear())

# 1) verfuegbare Messwerte
reset(); ms = {m["metric"]: m for m in A.get("/api/shelly/midea-1/metrics").get_json()}
assert set(ms) == {"indoor_c", "outdoor_c", "target_c"} and ms["outdoor_c"]["value"] == 13.0 and ms["indoor_c"]["unit"] == "°C" and ms["indoor_c"]["label"] == "Innentemperatur" and not ms["indoor_c"]["exists"], ms
reset(); tm = {m["metric"]: m for m in A.get("/api/shelly/tas-1/metrics").get_json()}; assert set(tm) == {"power"} and tm["power"]["value"] == 7.3 and tm["power"]["kind"] == "power"
assert A.get("/api/shelly/rem-1/metrics").status_code == 400 and A.get("/api/shelly/gibtsnicht/metrics").status_code == 400 and L.get("/api/shelly/midea-1/metrics").status_code == 403
state["midea"].pop("outdoor_c"); reset(); assert "outdoor_c" not in {m["metric"] for m in A.get("/api/shelly/midea-1/metrics").get_json()}; state["midea"]["outdoor_c"] = 13
# 2) Sensor anlegen
assert L.post("/api/shelly/midea-1/metric-sensor", json={"metric": "outdoor_c"}).status_code == 403 and A.post("/api/shelly/midea-1/metric-sensor", json={"metric": "quatsch"}).status_code == 400
r = A.post("/api/shelly/midea-1/metric-sensor", json={"metric": "outdoor_c"}); assert r.status_code == 201 and r.get_json()["name"] == "Wohnzimmer – Außentemperatur", r.get_data(as_text=True)
r = A.post("/api/shelly/midea-1/metric-sensor", json={"metric": "indoor_c", "name": "Wohnzimmer innen"}); assert r.status_code == 201 and r.get_json()["name"] == "Wohnzimmer innen"
assert A.post("/api/shelly/midea-1/metric-sensor", json={"metric": "outdoor_c"}).status_code == 400                         # nur einmal je Messwert
reset(); assert {m["metric"]: m["exists"] for m in A.get("/api/shelly/midea-1/metrics").get_json()} == {"indoor_c": True, "outdoor_c": True, "target_c": False}
sn = {s["id"]: s for s in homematic.load_sensors()}; o = sn["devM-midea-1-outdoor_c"]
assert o["kind"] == "temperature" and o["unit"] == "°C" and o["binary"] is False and o["source"] == "device" and o["metric"] == "outdoor_c" and o["users"] == [] and "invert" not in o
# 3) Werte lesen (Zahl, unbekannt bei offline/fehlendem Wert); Geraet bleibt unveraendert
val = lambda sid: next(s for s in A.get("/api/sensors").get_json() if s["id"] == sid)["value"]
reset(); assert val("devM-midea-1-outdoor_c") == 13.0 and val("devM-midea-1-indoor_c") == 20.5
state["midea"]["outdoor_c"] = 12.5; state["midea"]["indoor_c"] = 21.04; reset(); assert val("devM-midea-1-outdoor_c") == 12.5 and val("devM-midea-1-indoor_c") == 21.0
state["midea"].pop("outdoor_c"); reset(); assert val("devM-midea-1-outdoor_c") is None                                   # Klimaanlage meldet keinen Wert (z. B. aus) -> unbekannt
state["midea"]["online"] = False; reset(); assert val("devM-midea-1-indoor_c") is None; state["midea"]["online"] = True; state["midea"]["outdoor_c"] = 13
dv = next(d for d in shelly.load_devices() if d["id"] == "midea-1"); assert dv.get("switchable") is not False and "as_sensor" not in dv   # Klimaanlage bleibt wie sie war
# Leistung einer Steckdose
assert A.post("/api/shelly/tas-1/metric-sensor", json={"metric": "power"}).status_code == 201
reset(); assert val("devM-tas-1-power") == 7.3 and next(s for s in A.get("/api/sensors").get_json() if s["id"] == "devM-tas-1-power")["kind"] == "power"
# 4) Nur den Sensor teilen, nicht die Klimaanlage
r = A.post("/api/shares", json={"name": "Oma"}); sid = r.get_json()["share"]["id"]
cat = {x["ref"] for x in A.get("/api/shares").get_json()["shareable"]}; assert "sensor:devM-midea-1-outdoor_c" in cat and "device:midea-1" in cat
assert A.patch("/api/shares/" + sid, json={"items": [{"ref": "sensor:devM-midea-1-outdoor_c", "mode": "view"}]}).status_code == 200
tok = share._load(share.SHARES_PATH)[0]; items = share.provider_items(tok)
assert [x["ref"] for x in items] == ["sensor:devM-midea-1-outdoor_c"] and items[0]["state"]["value"] == 13.0 and items[0]["unit"] == "°C" and "device:midea-1" not in json.dumps(items), items       # nur dieser Wert, nichts von der Klimaanlage
# 5) Sensor loeschen (Sensorliste), Geraet bleibt; Symbol/Name aenderbar wie bei jedem Sensor
assert A.patch("/api/sensors/devM-midea-1-outdoor_c", json={"name": "Außen", "icon": "🌡️"}).status_code == 200
assert A.delete("/api/sensors/devM-midea-1-indoor_c").status_code == 200 and not any(s["id"] == "devM-midea-1-indoor_c" for s in homematic.load_sensors())
assert any(d["id"] == "midea-1" for d in shelly.load_devices())
print("MESSWERT-SENSOR OK")
