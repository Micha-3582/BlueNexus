"""Thermostat von Hand einstellen: Rechte, Sichtbarkeit, Begrenzung, Fehler, Zigbee/Homematic."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, auth
from auth import UserStore

homematic._save_setpoints([
    {"id": "hmT-1", "address": "A:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "HM-CC-RT-DN", "room": "Bad", "name": "Bad"},
    {"id": "hmT-2", "address": "B:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "HM", "room": "Flur", "name": "Nur Admin", "users": []},
    {"id": "hmT-3", "address": "C:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 6.0, "max": 28.0, "model": "HM", "room": "Kind", "name": "Eng", "users": ["anna"]},
])
calls = []
def fake_call(method, params=None):
    calls.append((method, params))
    if method == "Interface.setValue" and params["address"] == "B:1":
        raise homematic.HomematicError("Gerät antwortet nicht")
    return {}
homematic._call = fake_call

webapp.users = UserStore(os.path.join(tmp, "u_sp.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass1", {"dashboard": "write", "settings_geraete": "read"})
webapp.users.create("marie", "mariepass12", {"dashboard": "read", "settings_geraete": "read"})
webapp.users.create("nodash", "nodashpass1", {"settings_geraete": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, M, R_, N = login("admin", "adminpass1"), login("anna", "annapass1"), login("marie", "mariepass12"), login("nodash", "nodashpass1")
url = lambda i: f"/api/homematic/setpoints/{i}/value"

# Einstellen + Begrenzung auf 5..30 und den Bereich des Thermostats
r = M.post(url("hmT-1"), json={"value": 21.5}); assert r.status_code == 200 and r.get_json()["value"] == 21.5, r.get_data(as_text=True)
last = calls[-1]; assert last[0] == "Interface.setValue" and last[1]["value"] == 21.5 and last[1]["address"] == "A:1" and last[1]["valueKey"] == "SET_POINT_TEMPERATURE"
assert M.post(url("hmT-1"), json={"value": 3}).get_json()["value"] == 5.0
assert M.post(url("hmT-1"), json={"value": 99}).get_json()["value"] == 30.0
assert M.post(url("hmT-3"), json={"value": 5}).get_json()["value"] == 6.0 and M.post(url("hmT-3"), json={"value": 30}).get_json()["value"] == 28.0   # engerer Bereich des Geraets
# ungueltige Werte werden abgelehnt, nichts gesendet
n = len(calls)
for bad in (None, "abc", True, [], {}, float("nan"), 1e9):
    r = M.post(url("hmT-1"), json={"value": bad}); assert r.status_code == 400, (bad, r.status_code)
assert M.post(url("hmT-1"), data="x", content_type="text/plain").status_code == 400
assert len(calls) == n
# Sichtbarkeit: Marie (nicht freigegeben fuer hmT-3) und Nur-Admin-Geraet -> 404
assert M.post(url("hmT-2"), json={"value": 20}).status_code == 404
assert R_.post(url("hmT-3"), json={"value": 20}).status_code in (403, 404)
assert A.post(url("hmT-2"), json={"value": 20}).status_code == 400 and "fehlgeschlagen" in A.post(url("hmT-2"), json={"value": 20}).get_json()["error"]     # Admin sieht es; Geraet meldet Fehler
assert A.post(url("gibtsnicht"), json={"value": 20}).status_code in (400, 404)
# Rechte: nur Lesen / kein Dashboard -> nicht schaltbar
assert R_.post(url("hmT-1"), json={"value": 20}).status_code == 403
assert N.post(url("hmT-1"), json={"value": 20}).status_code == 403
assert webapp.app.test_client().post(url("hmT-1"), json={"value": 20}).status_code in (401, 302, 403)
# Liste gefiltert
ids = lambda c: [s["id"] for s in c.get("/api/homematic/setpoints?light=1").get_json()]
assert ids(A) == ["hmT-1", "hmT-2", "hmT-3"] and ids(M) == ["hmT-1", "hmT-3"] and ids(R_) == ["hmT-1"], (ids(A), ids(M), ids(R_))
# Admin: Sichtbarkeit setzen, Benutzer ohne Admin darf das nicht
assert A.patch("/api/homematic/setpoints/hmT-1", json={"users": ["marie"]}).status_code == 200 and ids(M) == ["hmT-3"] and ids(R_) == ["hmT-1"]
assert M.patch("/api/homematic/setpoints/hmT-1", json={"users": None}).status_code == 403
# Zigbee-Thermostat nutzt dieselbe Schiene
import zigbee
zigbee.set_setpoint = lambda sp, value: round(value * 2) / 2
homematic._save_setpoints(homematic.load_setpoints() + [{"id": "zbT-9", "address": "z", "interface": "Zigbee", "datapoint": "heatsetpoint", "min": 5, "max": 30, "model": "Z", "room": "", "name": "ZB", "source": "zigbee"}])
assert A.post(url("zbT-9"), json={"value": 19.74}).get_json()["value"] == 19.5
# neu angelegte Thermostate: zunaechst nur Admin
homematic._setpoint_scan["hmT-7"] = {"id": "hmT-7", "address": "D:1", "interface": "HmIP-RF", "datapoint": "SET_POINT_TEMPERATURE", "min": 4.5, "max": 30.5, "model": "M", "room": "", "name": "Neu"}
homematic._setpoint_scan_ts = __import__("time").time()
assert homematic.add_setpoints(["hmT-7"])[0]["users"] == []
print("THERMOSTAT VON HAND OK")
