"""Live-Werte (Solar) teilen: nur lesend, Geber gibt sie frei, Empfaenger holt sie als Sensoren (Watt)."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import share, shelly, homematic
from auth import UserStore
share.SHARES_PATH = os.path.join(tmp, "shares.json"); share.SOURCES_PATH = os.path.join(tmp, "sources.json")
webapp.users = UserStore(os.path.join(tmp, "u_shlive.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("kind", "kindpass1234", {"dashboard": "write"})
webapp.opslog.log = lambda *a, **k: None
share.CACHE_TTL_S = 0
shelly._save([]); homematic._save_sensors([])

homematic._save_setpoints([
    {"id": "hmT-1", "address": "A:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "eTRV", "room": "Wohnzimmer", "name": "Wohnzimmer"},
    {"id": "hmT-2", "address": "B:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 6.0, "max": 28.0, "model": "eTRV", "room": "Bad", "name": "Bad (nur sehen)"},
    {"id": "hmT-geheim", "address": "C:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "eTRV", "room": "", "name": "Nicht geteilt"},
])
ccu = {"A:1": 21.0, "B:1": 20.0, "C:1": 19.0}
calls = []
def fake_call(method, params=None):
    if method == "Interface.setValue":
        ccu[params["address"]] = params["value"]; calls.append((params["address"], params["value"])); return {}
    if method == "Interface.getValue":
        return ccu[params["address"]]
    return {}
homematic._call = fake_call
homematic._get_value = lambda itf, addr, key: ccu[addr]

c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
class Resp:
    def __init__(self, r): self.status_code = r.status_code; self.ok = r.status_code < 400; self._j = r.get_json(silent=True)
    def json(self):
        if self._j is None: raise ValueError("kein JSON")
        return self._j
anon = webapp.app.test_client()
def fake_request(method, url, headers=None, timeout=None, json=None, params=None, **kw):
    path = url[len("http://geber.test"):]
    return Resp(anon.open(path, method=method, headers=headers or {}, json=json, query_string=params))
share.requests.request = fake_request


fake_sys = {"solar_total": 3207, "pv_inverter": {"l1": 0, "l2": 1049, "l3": 1280, "total": 2329}, "pv_charger": 878}
share.live_system = lambda: fake_sys
r = c.post("/api/shares", json={"name": "Mutter"}); tok = r.get_json()["token"]; sid = r.get_json()["share"]["id"]
cat = {x["ref"]: x for x in c.get("/api/shares").get_json()["shareable"]}
assert {"live:solar", "live:pv_inverter", "live:pv_inverter_l1", "live:pv_inverter_l2", "live:pv_inverter_l3", "live:pv_charger"} <= set(cat) and cat["live:solar"]["type"] == "sensor"
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "live:solar", "mode": "control"}, {"ref": "live:pv_inverter_l2", "mode": "view"}, {"ref": "live:pv_charger", "mode": "view"}]}).status_code == 200
H = {"Authorization": "Bearer " + tok}
refs = {x["ref"]: x for x in anon.get("/share/v1/items", headers=H).get_json()["items"]}
assert set(refs) == {"live:solar", "live:pv_inverter_l2", "live:pv_charger"}, set(refs)
assert refs["live:solar"]["state"]["value"] == 3207 and refs["live:pv_inverter_l2"]["state"]["value"] == 1049 and refs["live:pv_charger"]["state"]["value"] == 878
assert refs["live:solar"]["control"] is False and refs["live:solar"]["unit"] == "W" and refs["live:solar"]["icon"] == "☀️"          # auch "bedienen" wird zu nur sehen
assert anon.post("/share/v1/act", headers=H, json={"ref": "live:solar", "on": True}).status_code in (400, 403, 404)
print("Geber OK")
qid = c.post("/api/sources", json={"invite": share.make_invite("http://geber.test", tok)}).get_json()["id"]
its = c.get(f"/api/sources/{qid}/items").get_json(); assert len(its) == 3
r = c.post(f"/api/sources/{qid}/import", json={"refs": [i["ref"] for i in its]}); assert r.get_json()["added_sensors"] == 3, r.get_json()
loc = {s["name"]: s for s in homematic.load_sensors() if s.get("source") == "remote"}
assert loc["Solar gesamt"]["unit"] == "W" and loc["Solar gesamt"]["icon"] == "☀️", loc["Solar gesamt"]
vals = {s["name"]: s.get("value") for s in c.get("/api/sensors").get_json()}
assert vals.get("Solar gesamt") == 3207 and vals.get("PV-Wechselrichter L2") == 1049, vals
fake_sys = None; share.live_system = lambda: None
refs = {x["ref"]: x for x in anon.get("/share/v1/items", headers=H).get_json()["items"]}
assert refs["live:solar"]["state"]["value"] is None            # keine Messung: leer statt falscher Zahl
print("LIVE-TEILEN OK")
