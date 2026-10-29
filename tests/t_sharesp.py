"""Thermostate teilen: Geber gibt Thermostate frei (sehen / bedienen), Empfaenger holt sie und stellt sie ein."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import share, shelly, homematic
from auth import UserStore
share.SHARES_PATH = os.path.join(tmp, "shares.json"); share.SOURCES_PATH = os.path.join(tmp, "sources.json")
webapp.users = UserStore(os.path.join(tmp, "u_shsp.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("kind", "kindpass1234", {"dashboard": "write"})
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

# Geber: Freigabe, Thermostate teilbar
r = c.post("/api/shares", json={"name": "Oma"}); tok = r.get_json()["token"]; sid = r.get_json()["share"]["id"]
cat = {x["ref"]: x for x in c.get("/api/shares").get_json()["shareable"]}
assert cat["setpoint:hmT-1"]["detail"] == "Thermostat" and cat["setpoint:hmT-1"]["type"] == "setpoint"
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "setpoint:nix", "mode": "view"}]}).status_code == 400
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "setpoint:hmT-1", "mode": "control"}, {"ref": "setpoint:hmT-2", "mode": "view"}]}).status_code == 200
# Angebot: nur die freigegebenen, mit Wert und Bereich (auf 5..30 begrenzt)
H = {"Authorization": "Bearer " + tok}
j = anon.get("/share/v1/items", headers=H).get_json(); refs = {x["ref"]: x for x in j["items"]}
assert set(refs) == {"setpoint:hmT-1", "setpoint:hmT-2"} and "Nicht geteilt" not in json.dumps(j) and "A:1" not in json.dumps(j)
assert refs["setpoint:hmT-1"]["state"]["value"] == 21.0 and refs["setpoint:hmT-1"]["control"] is True and refs["setpoint:hmT-2"]["control"] is False
assert (refs["setpoint:hmT-2"]["min"], refs["setpoint:hmT-2"]["max"]) == (6.0, 28.0) and (refs["setpoint:hmT-1"]["min"], refs["setpoint:hmT-1"]["max"]) == (5.0, 30.0)
# Rechte an der Schnittstelle
assert anon.post("/share/v1/act", headers=H, json={"ref": "setpoint:hmT-2", "value": 22}).status_code == 403          # nur sehen
assert anon.post("/share/v1/act", headers=H, json={"ref": "setpoint:hmT-geheim", "value": 22}).status_code == 404
assert anon.post("/share/v1/act", headers={"Authorization": "Bearer x"}, json={"ref": "setpoint:hmT-1", "value": 22}).status_code == 401
assert anon.post("/share/v1/act", headers=H, json={"ref": "setpoint:hmT-1", "value": "abc"}).status_code == 400
assert not calls
print("Geber OK")

# Empfaenger: Quelle, Import
qid = c.post("/api/sources", json={"invite": share.make_invite("http://geber.test", tok)}).get_json()["id"]
its = c.get(f"/api/sources/{qid}/items").get_json(); assert {i["type"] for i in its} == {"setpoint"} and len(its) == 2
r = c.post(f"/api/sources/{qid}/import", json={"refs": [i["ref"] for i in its]}); assert r.get_json() == {"added_devices": 0, "added_sensors": 0, "added_setpoints": 2, "added_other": 0}, r.get_json()
assert c.post(f"/api/sources/{qid}/import", json={"refs": ["setpoint:hmT-1"]}).get_json()["added_setpoints"] == 0           # nichts doppelt
assert all(i["already"] for i in c.get(f"/api/sources/{qid}/items").get_json())
# die geteilten Thermostate stehen neben eigenen, unter eigener ID, mit Wert vom Geber
local = {s["name"]: s for s in homematic.load_setpoints() if s.get("source") == "remote"}
wz, bad = local["Wohnzimmer"], local["Bad (nur sehen)"]
assert wz["switchable"] is True and bad["switchable"] is False and wz["id"] != "hmT-1" and wz["model"].startswith("von ")
assert (bad["min"], bad["max"]) == (6.0, 28.0)
lst = {s["name"]: s for s in c.get("/api/homematic/setpoints").get_json()}
assert lst["Wohnzimmer"]["value"] == 21.0 and lst["Bad (nur sehen)"]["value"] == 20.0, lst
# Einstellen: geht zum Geber, der es mit SEINEM Zugang setzt
r = c.post(f"/api/homematic/setpoints/{wz['id']}/value", json={"value": 23.5}); assert r.status_code == 200 and r.get_json()["value"] == 23.5, r.get_data(as_text=True)
assert ccu["A:1"] == 23.5 and ("A:1", 23.5) in calls
assert {s["name"]: s["value"] for s in c.get("/api/homematic/setpoints").get_json()}["Wohnzimmer"] == 23.5
# Begrenzung beim Empfaenger (Bereich des Geraets)
assert c.post(f"/api/homematic/setpoints/{wz['id']}/value", json={"value": 99}).get_json()["value"] == 30.0 and ccu["A:1"] == 30.0
# nur zum Ansehen freigegeben: Fehlermeldung, am Geraet aendert sich nichts
r = c.post(f"/api/homematic/setpoints/{bad['id']}/value", json={"value": 25}); assert r.status_code == 400 and "nur zum Ansehen" in r.get_json()["error"], r.get_data(as_text=True)
assert ccu["B:1"] == 20.0
# Weitergeben unmoeglich
assert not any(x["ref"].startswith("setpoint:r-") for x in c.get("/api/shares").get_json()["shareable"])
# Geber nimmt zurueck -> Wert nicht mehr lesbar, Einstellen scheitert sauber
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "setpoint:hmT-2", "mode": "view"}]}).status_code == 200
lst = {s["name"]: s for s in c.get("/api/homematic/setpoints").get_json()}; assert lst["Wohnzimmer"]["value"] is None
r = c.post(f"/api/homematic/setpoints/{wz['id']}/value", json={"value": 20}); assert r.status_code == 400 and "freigegeben" in r.get_json()["error"], r.get_data(as_text=True)
# Quelle entfernen nimmt auch die Thermostate mit; in einer Regel benutzt -> Sperre
import rules
r_ = c.delete(f"/api/sources/{qid}"); assert r_.status_code == 200 and r_.get_json()["removed"] == 2, r_.get_data(as_text=True)
assert not [s for s in homematic.load_setpoints() if s.get("source") == "remote"] and len(homematic.load_setpoints()) == 3
print("Empfaenger OK")
print("THERMOSTATE TEILEN OK")
