import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, devicelog, auth
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
json.dump([{"id": "d1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Lampe", "icon": "💡", "model": "T", "show": True, "users": ["anna"]},
           {"id": "d2", "kind": "tasmota", "mac": "BB", "channel": 1, "gen": 0, "ip": "192.168.50.91", "name": "Nur Admin", "model": "T", "show": True, "users": []}], open(shelly.DEVICES_PATH, "w"))
webapp.users = UserStore(os.path.join(tmp, "u_l.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass123", {"dashboard": "write", "settings_geraete": "write", "smarthome_logbuch": "read"})
webapp.users.create("bert", "bertpass123", {"dashboard": "write", "settings_geraete": "write"})
cl = {}
for u, p in (("admin", "adminpass1"), ("anna", "annapass123"), ("bert", "bertpass123")):
    cl[u] = webapp.app.test_client(); cl[u].post("/login", data={"username": u, "password": p})
assert auth.normalize_permissions({"settings_geraete": "write"})["smarthome_logbuch"] == "none"                          # kein Erbe: Standard = nur Admin
devicelog.log("aktor", "device:d1", "Lampe", "eingeschaltet", True, by="Konto „anna“")
devicelog.log("aktor", "device:d2", "Nur Admin", "eingeschaltet", True, by="x")
devicelog.log("regel", "rule:r1", "Regel", "gelaufen", True, by="Regel")
devicelog.log("sicherheit", "nfc:alert", "NFC", "Fremder", False, by="Fremder Zugriff")
names = lambda u: [e["name"] for e in cl[u].get("/api/devicelog").get_json()["entries"]]
assert sorted(names("admin")) == ["Lampe", "NFC", "Nur Admin", "Regel"]
assert names("anna") == ["Lampe"]
assert cl["bert"].get("/api/devicelog").status_code == 403 and cl["anna"].get("/api/devicelog/last").status_code == 403
page = lambda u: cl[u].get("/smarthome").get_data(as_text=True)
assert "#logbuch" in page("admin") and "#logbuch" in page("anna") and "#logbuch" not in page("bert")
print("LOGBUCH-RECHT OK")
old = {a: "write" for a in auth.AREA_IDS if a not in ("smarthome_logbuch", "smarthome_wol")}        # Administrator aus der Zeit vor dem Recht
webapp.users.create("alt", "altpass12345", old)
cl["alt"] = webapp.app.test_client(); cl["alt"].post("/login", data={"username": "alt", "password": "altpass12345"})
assert auth.is_full_admin(auth.normalize_permissions(old)) and "#logbuch" in page("alt") and "#wol" in page("alt")
print("ALTER ADMIN OK")
bad = {a: "write" for a in auth.AREA_IDS}; bad["smarthome_logbuch"] = "none"; bad["smarthome_wol"] = "none"         # Admin mit versehentlich gespeichertem "Kein"
webapp.users.create("hof", "hofpass12345", bad)
cl["hof"] = webapp.app.test_client(); cl["hof"].post("/login", data={"username": "hof", "password": "hofpass12345"})
assert "#logbuch" in page("hof") and cl["hof"].get("/api/devicelog").status_code == 200
print("ADMIN MIT KEIN OK")
