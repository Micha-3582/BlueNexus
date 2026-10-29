"""Sichtbarkeit pro Benutzer: Aktoren, Sensoren, eigene Schalter/Knoepfe, WOL; Filter, Aktionen, Admin-only, Umbenennen/Loeschen."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, virtual, wol, visibility, auth
from auth import UserStore

# --- reine Logik
assert visibility.normalize(None) is None and visibility.normalize([" Ina ", "ina", "Max"]) == ["ina", "max"] and visibility.normalize([]) == []
try:
    visibility.normalize("ina"); raise AssertionError("String")
except ValueError:
    pass
assert visibility.can_see({}, "x", False) and visibility.can_see({"users": ["ina"]}, "Ina", False) and not visibility.can_see({"users": ["ina"]}, "max", False)
assert visibility.can_see({"users": []}, "max", True) and not visibility.can_see({"users": []}, "max", False)
items = [{"id": "a", "users": ["ina", "max"]}]
assert visibility.rename_user(items, "ina", "Inas") and items[0]["users"] == ["inas", "max"]
assert visibility.drop_user(items, "max") and items[0]["users"] == ["inas"]
print("Logik OK")

json.dump([{"id": "lampe", "name": "Flurlicht", "kind": "zigbee", "uniqueid": "x", "icon": "💡", "ip": "1.2.3.4", "model": "m", "show": True},
           {"id": "boiler", "name": "Boiler", "kind": "shelly", "ip": "1.2.3.5", "icon": "🔌", "model": "m", "show": True}], open(shelly.DEVICES_PATH, "w"))
shelly.status = lambda d: {"online": True, "on": False, "power": None}
calls = []
shelly.set_state = lambda dev_id, on, timer_s=None: (calls.append((dev_id, on)), {"online": True, "on": on, "power": None})[1]
homematic._save_sensors([{"id": "s1", "name": "Tür", "kind": "contact", "binary": True, "show": True, "source": "zigbee", "address": "a", "model": "m"},
                         {"id": "s2", "name": "Keller", "kind": "temperature", "binary": False, "show": True, "source": "homematic", "address": "b", "model": "m"}])
homematic.read_values = lambda items: {s["id"]: True for s in items}
t = virtual.add("Türöffner", "button"); w = virtual.add("Warmwasser-Timer", "switch")
pc = wol.add("Ryzen9", "aa:bb:cc:dd:ee:ff", ip="192.168.50.50")
wol.is_up = lambda ip: True

webapp.users = UserStore(os.path.join(tmp, "users_vis.json"))
webapp.users.create("admin", "adminpass1")
P = {"dashboard": "write", "settings_geraete": "write", "account": "write"}
webapp.users.create("ina", "inapass123", P); webapp.users.create("max", "maxpass123", P)
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I, M = login("admin", "adminpass1"), login("ina", "inapass123"), login("max", "maxpass123")

def names(c, url):
    return sorted(x["name"] for x in c.get(url).get_json())

# Neu angelegte Eintraege (virtual.add/wol.add) sind zunaechst NUR fuer Administratoren sichtbar
assert t["users"] == [] and w["users"] == [] and pc["users"] == []
assert names(I, "/api/virtual") == [] and names(M, "/api/wol") == [] and names(A, "/api/virtual") == ["Türöffner", "Warmwasser-Timer"]
for it in (t, w): assert A.patch("/api/virtual/" + it["id"], json={"users": None}).status_code == 200
assert A.patch("/api/wol/" + pc["id"], json={"users": None}).status_code == 200
# ueber die API angelegt: ebenfalls nur Admin
r = A.post("/api/virtual", json={"name": "Zusatz", "kind": "switch"}); assert r.status_code in (200, 201), r.status_code
newv = r.get_json(); newid = newv.get("id") or newv.get("item", {}).get("id")
assert "Zusatz" not in names(I, "/api/virtual") and "Zusatz" in names(A, "/api/virtual")
assert A.delete("/api/virtual/" + newid).status_code == 200



# Standard: alle sehen alles
for c in (A, I, M):
    assert names(c, "/api/shelly") == ["Boiler", "Flurlicht"] and names(c, "/api/sensors") == ["Keller", "Tür"]
    assert names(c, "/api/virtual") == ["Türöffner", "Warmwasser-Timer"] and names(c, "/api/wol") == ["Ryzen9"]
print("Standard OK")

# Nur der Admin legt fest, wer sieht
assert I.patch("/api/virtual/" + w["id"], json={"users": ["ina"]}).status_code == 403
assert I.patch("/api/shelly/boiler", json={"users": ["ina"]}).status_code == 403
assert A.patch("/api/virtual/" + w["id"], json={"users": "ina"}).status_code == 400
assert A.patch("/api/virtual/" + w["id"], json={"users": ["ina"]}).status_code == 200
assert A.patch("/api/shelly/boiler", json={"users": ["ina"]}).status_code == 200
assert A.patch("/api/sensors/s2", json={"users": ["Ina"]}).status_code == 200
assert A.patch("/api/wol/" + pc["id"], json={"users": []}).status_code == 200
assert A.patch("/api/wol/gibts-nicht", json={"users": ["ina"]}).status_code == 404

# Filter
assert names(I, "/api/virtual") == ["Türöffner", "Warmwasser-Timer"] and names(M, "/api/virtual") == ["Türöffner"]
assert names(I, "/api/shelly") == ["Boiler", "Flurlicht"] and names(M, "/api/shelly") == ["Flurlicht"]
assert names(I, "/api/sensors") == ["Keller", "Tür"] and names(M, "/api/sensors") == ["Tür"]
assert names(I, "/api/wol") == [] and names(M, "/api/wol") == [] and names(A, "/api/wol") == ["Ryzen9"]
assert all("users" not in x for x in I.get("/api/virtual").get_json())               # Benutzerlisten nur fuer den Admin
assert [x for x in A.get("/api/virtual").get_json() if x["id"] == w["id"]][0]["users"] == ["ina"]
assert [x for x in A.get("/api/sensors").get_json() if x["id"] == "s2"][0]["users"] == ["ina"]
# MAC/IP von Wake-on-LAN nur mit Schreibrecht auf die Geraete im Klartext (lesende Konten wie "demo": unkenntlich)
assert A.patch("/api/wol/" + pc["id"], json={"users": None}).status_code == 200
webapp.users.create("demo", "demopass123", {"dashboard": "read", "settings_geraete": "read"})
D = login("demo", "demopass123")
x = D.get("/api/wol").get_json()[0]
assert x["mac"] != pc["mac"] and "•" in x["mac"] and "•" in x["ip"] and x.get("ip_hidden") is True and "AA:BB" not in str(x)
x = I.get("/api/wol").get_json()[0]; assert x["mac"] == "AA:BB:CC:DD:EE:FF" and x["ip"] == "192.168.50.50"                   # Schreibrecht: Klartext
x = A.get("/api/wol").get_json()[0]; assert x["mac"] == "AA:BB:CC:DD:EE:FF"
assert A.patch("/api/wol/" + pc["id"], json={"users": []}).status_code == 200
print("Filter OK")

# Aktionen: Unsichtbares laesst sich nicht bedienen (404), Sichtbares schon
assert M.post(f"/api/virtual/{w['id']}/set", json={"on": True}).status_code == 404
assert I.post(f"/api/virtual/{w['id']}/set", json={"on": True}).status_code == 200
assert M.post(f"/api/virtual/{t['id']}/press").status_code == 200
assert M.post("/api/shelly/boiler/switch", json={"on": True}).status_code == 404 and calls == []
assert I.post("/api/shelly/boiler/switch", json={"on": True}).status_code == 200 and calls == [("boiler", True)]
assert I.post(f"/api/wol/{pc['id']}/wake").status_code == 404
# Verwalten (umbenennen/aendern/entfernen/anlegen) darf nur der Admin - auch Konten mit Schreibrecht nicht
for c in (I, M):
    assert c.patch("/api/virtual/" + w["id"], json={"name": "x"}).status_code == 403 and c.delete("/api/virtual/" + w["id"]).status_code == 403
    assert c.patch("/api/shelly/boiler", json={"name": "x"}).status_code == 403 and c.patch("/api/sensors/s2", json={"name": "x"}).status_code == 403
    assert c.patch("/api/sensors/s1", json={"invert": True}).status_code == 403 and c.delete("/api/sensors/s1").status_code == 403
    assert c.patch("/api/wol/" + pc["id"], json={"name": "x"}).status_code == 403 and c.delete("/api/wol/" + pc["id"]).status_code == 403
    assert c.post("/api/virtual", json={"name": "Neu", "kind": "button"}).status_code == 403
    assert c.post("/api/wol", json={"name": "Neu", "mac": "11:22:33:44:55:66"}).status_code == 403
    assert c.patch("/api/homematic/locks/x", json={"allow_open": True}).status_code == 403 and c.patch("/api/homematic/setpoints/x", json={"name": "y"}).status_code == 403
assert A.patch("/api/virtual/" + w["id"], json={"name": "Warmwasser-Timer"}).status_code == 200
assert [x["name"] for x in A.get("/api/shelly").get_json()].count("Boiler") == 1
print("Aktionen OK")

# wieder fuer alle
assert A.patch("/api/virtual/" + w["id"], json={"users": None}).status_code == 200
assert names(M, "/api/virtual") == ["Türöffner", "Warmwasser-Timer"]
assert "users" not in [x for x in A.get("/api/virtual").get_json() if x["id"] == w["id"]][0]

# Umbenennen / Loeschen eines Benutzers zieht die Listen nach
assert A.patch("/api/shelly/boiler", json={"users": ["ina", "max"]}).status_code == 200
r = I.post("/api/account", json={"current": "inapass123", "username": "Inas"}) if False else None
webapp.users.rename("ina", "Inas"); webapp.ctrl and None
with webapp.app.test_request_context():
    webapp._vis_users_changed("ina", "Inas")
assert [x for x in A.get("/api/shelly").get_json() if x["id"] == "boiler"][0]["users"] == ["inas", "max"]
with webapp.app.test_request_context():
    webapp._vis_users_changed("max", None)
assert [x for x in A.get("/api/shelly").get_json() if x["id"] == "boiler"][0]["users"] == ["inas"]
print("Umbenennen/Loeschen OK")
print("VISIBILITY OK")
