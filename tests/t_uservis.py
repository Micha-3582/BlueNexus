"""Sichtbarkeit je Benutzer gesammelt einstellen (Benutzerverwaltung) und Profil kopieren."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, virtual, wol
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
homematic._save_sensors([
    {"id": "s1", "kind": "temperature", "address": "A", "interface": "x", "datapoint": "T", "binary": False, "unit": "°C", "name": "Alle", "model": "m", "room": "", "show": True},                       # users fehlt = fuer alle
    {"id": "s2", "kind": "temperature", "address": "B", "interface": "x", "datapoint": "T", "binary": False, "unit": "°C", "name": "Nur Admin", "model": "m", "room": "", "show": True, "users": []},
    {"id": "s3", "kind": "temperature", "address": "C", "interface": "x", "datapoint": "T", "binary": False, "unit": "°C", "name": "Nur Anna", "model": "m", "room": "", "show": True, "users": ["anna"]}])
json.dump([{"id": "d1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Lampe", "icon": "💡", "model": "T", "show": True, "users": []}], open(shelly.DEVICES_PATH, "w"))
homematic._read_sensor_now = lambda s: 21.0
webapp.users = UserStore(os.path.join(tmp, "u_uv2.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("berta", "bertapass1", {"dashboard": "write", "settings_geraete": "read"})
webapp.users.create("anna", "annapass123", {"dashboard": "read"})
webapp.users.create("boss", "bosspass123", admin=True)
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
M = webapp.app.test_client(); M.post("/login", data={"username": "berta", "password": "bertapass1"})
vis = lambda cl, u: {i["id"]: i["on"] for g in cl.get(f"/api/users/{u}/visible").get_json()["groups"] if g["kind"] == "sensor" for i in g["items"]}
users_of = lambda sid: next(s for s in homematic.load_sensors() if s["id"] == sid).get("users", "ALLE")

# 1) Anzeige
assert vis(A, "berta") == {"s1": True, "s2": False, "s3": False} and vis(A, "anna") == {"s1": True, "s2": False, "s3": True}
g = {x["kind"]: x for x in A.get("/api/users/berta/visible").get_json()["groups"]}; assert {"sensor", "shelly"} <= set(g) and g["shelly"]["items"][0]["name"] == "Lampe" and g["shelly"]["items"][0]["on"] is False
# 2) Rechte / Fehler
assert M.get("/api/users/anna/visible").status_code == 403 and M.put("/api/users/anna/visible", json={"items": {}}).status_code == 403
assert A.get("/api/users/boss/visible").status_code == 400 and A.get("/api/users/gibtsnicht/visible").status_code == 404
assert A.put("/api/users/berta/visible", json={"items": "quatsch"}).status_code == 400 and A.put("/api/users/berta/visible", json={"items": {"sensor:s1": "ja"}}).status_code == 400
# 3) Setzen: Nur-Admin-Sensor freigeben, "fuer alle"-Sensor einem Konto wegnehmen, wieder allen geben
assert A.put("/api/users/berta/visible", json={"items": {"sensor:s2": True, "shelly:d1": True}}).status_code == 200
assert users_of("s2") == ["berta"] and next(d for d in shelly.load_devices() if d["id"] == "d1")["users"] == ["berta"]
assert A.put("/api/users/berta/visible", json={"items": {"sensor:s1": False}}).status_code == 200 and users_of("s1") == ["anna"]            # "fuer alle" wird zur Liste ohne Berta
assert A.put("/api/users/berta/visible", json={"items": {"sensor:s1": True}}).status_code == 200 and users_of("s1") == "ALLE"                 # alle normalen Konten dabei: wieder "fuer alle"
assert A.put("/api/users/anna/visible", json={"items": {"sensor:s3": False, "sensor:s2": True}}).status_code == 200 and users_of("s3") == [] and users_of("s2") == "ALLE"
assert A.put("/api/users/anna/visible", json={"items": {"sensor:s3": True, "art:unbekannt": True, "sensor:gibtsnicht": True}}).status_code == 200 and users_of("s3") == ["anna"]
# 4) Wirkung: Berta sieht jetzt genau das
assert sorted(s["id"] for s in M.get("/api/sensors").get_json()) == ["s1", "s2"]
assert [d["id"] for d in M.get("/api/shelly?dashboard=1&light=1").get_json()] == ["d1"]
# 5) Profil kopieren
assert M.post("/api/users/berta/copy", json={"username": "x", "password": "xxxxxxxx1"}).status_code == 403
assert A.post("/api/users/boss/copy", json={"username": "kopie", "password": "kopiepass123"}).status_code == 400
assert A.post("/api/users/berta/copy", json={"username": "berta", "password": "kopiepass123"}).status_code == 400 and A.post("/api/users/berta/copy", json={"username": "neu1", "password": "kurz"}).status_code == 400
assert A.post("/api/users/gibtsnicht/copy", json={"username": "neu1", "password": "kopiepass123"}).status_code == 404
assert A.put("/api/users/berta/visible", json={"items": {"sensor:s3": True}}).status_code == 200
webapp.users.set_dashboard_tiles("berta", ["show_sensors_card", "show_shelly_card"])
r = A.post("/api/users/berta/copy", json={"username": "Zimmer 2", "password": "kopiepass123"}); assert r.status_code == 200, r.get_data(as_text=True)
k = webapp.users.get("zimmer 2"); m_ = webapp.users.get("berta")
assert k["permissions"] == m_["permissions"] and k["dashboard_tiles"] == m_["dashboard_tiles"] and k["dashboard_order"] == m_["dashboard_order"] and not k.get("owner")
assert users_of("s2") == "ALLE" and users_of("s3") == "ALLE" and users_of("s1") == "ALLE" and "zimmer 2" in next(d for d in shelly.load_devices() if d["id"] == "d1")["users"]
assert "zimmer 2" not in users_of("s1") if isinstance(users_of("s1"), list) else True
Z = webapp.app.test_client(); Z.post("/login", data={"username": "Zimmer 2", "password": "kopiepass123"})
assert sorted(s["id"] for s in Z.get("/api/sensors").get_json()) == sorted(s["id"] for s in M.get("/api/sensors").get_json())            # sieht dasselbe wie das Vorbild
assert Z.get("/api/users").status_code == 403                                                                                          # normales Konto, keine Benutzerverwaltung
# 6) Umbenennen/Loeschen zieht die Listen nach (bestehende Logik)
assert A.delete("/api/users/Zimmer 2").status_code == 200 and "zimmer 2" not in str(next(d for d in shelly.load_devices() if d["id"] == "d1")["users"])
# 7) Diagramm-Einstellungen: Seite kennt die eingeschalteten Module (Karte wird ohne Energie ausgeblendet)
store.module_on = lambda n, cfg=None: True
cf = store.load_config(); cf["modules"] = {"energy": False, "smarthome": True, "cameras": False, "verlauf": False, "alexa": False}; store.save_config(cf)
page = A.get("/admin").get_data(as_text=True); m = re.search(r"window\.MOD = (\{[^;]*\});", page); assert m and json.loads(m.group(1))["energy"] is False, page[page.find("window.MOD"):][:120]
cf["modules"]["energy"] = True; store.save_config(cf); page = A.get("/admin").get_data(as_text=True); assert json.loads(re.search(r"window\.MOD = (\{[^;]*\});", page).group(1))["energy"] is True
print("BENUTZER-SICHTBARKEIT OK")
# globaler Dashboard-Haken gilt nur fuer Administratoren
homematic._save_sensors([{"id": "z1", "kind": "temperature", "address": "Z", "interface": "x", "datapoint": "T", "binary": False, "unit": "°C", "name": "Z", "model": "m", "room": "", "show": False, "users": ["anna"]}])
json.dump([{"id": "d9", "kind": "tasmota", "mac": "CC", "channel": 1, "gen": 0, "ip": "192.168.50.99", "name": "Aus", "icon": "💡", "model": "T", "show": False, "users": ["anna"]}], open(shelly.DEVICES_PATH, "w"))
N = webapp.app.test_client(); N.post("/login", data={"username": "anna", "password": "annapass123"})
assert [s["show"] for s in N.get("/api/sensors?light=1").get_json()] == [True] and [s["show"] for s in A.get("/api/sensors?light=1").get_json()] == [False]
assert [d["id"] for d in N.get("/api/shelly?dashboard=1&light=1").get_json()] == ["d9"] and A.get("/api/shelly?dashboard=1&light=1").get_json() == []
print("SHOW OK")
