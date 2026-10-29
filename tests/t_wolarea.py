import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import wol, auth
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
wol._save([{"id": "w-1", "name": "PC", "icon": "💻", "mac": "AA:BB:CC:DD:EE:FF", "ip": "", "show": True, "users": ["anna"]}])
webapp.users = UserStore(os.path.join(tmp, "u_w.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("alt", "altpass12345", {"dashboard": "write", "settings_geraete": "write"})                       # altes Konto ohne Eintrag smarthome_wol
webapp.users.create("anna", "annapass123", {"dashboard": "write", "settings_geraete": "write", "smarthome_wol": "none"})
webapp.users.create("bert", "bertpass123", {"dashboard": "write", "settings_geraete": "write", "smarthome_wol": "read"})
webapp.users.create("cora", "corapass123", {"dashboard": "write", "settings_geraete": "write", "smarthome_wol": "write"})
cl = {}
for u, p in (("admin", "adminpass1"), ("alt", "altpass12345"), ("anna", "annapass123"), ("bert", "bertpass123"), ("cora", "corapass123")):
    cl[u] = webapp.app.test_client(); cl[u].post("/login", data={"username": u, "password": p})
assert auth.normalize_permissions({"settings_geraete": "write"})["smarthome_wol"] == "write"                              # Erbe des alten Bereichs
assert auth.normalize_permissions({"settings_geraete": "read"})["smarthome_wol"] == "read"
tabs = lambda u: [t["id"] for t in webapp._smarthome_tabs_for(u)] if hasattr(webapp, "_smarthome_tabs_for") else None
wols = lambda u: [x["id"] for x in (lambda j: j if isinstance(j, list) else [])(cl[u].get("/api/wol?light=1").get_json())]
assert wols("admin") == ["w-1"]
webapp.users.update_permissions("bert", {"dashboard": "write", "settings_geraete": "write", "smarthome_wol": "read"}) if hasattr(webapp.users, "update_permissions") else None
# anna: Recht "Kein" -> nichts, Aufwecken verboten
assert wols("anna") == [] and cl["anna"].post("/api/wol/w-1/wake").status_code == 403
# bert hat Lesen, aber der Rechner ist nur fuer anna freigegeben -> sieht nichts; Aufwecken nicht erlaubt
assert wols("bert") == [] and cl["bert"].post("/api/wol/w-1/wake").status_code in (403, 404)
# freigeben fuer bert/cora/alt
it = wol.load(); it[0]["users"] = ["anna", "bert", "cora", "alt"]; wol._save(it)
assert wols("bert") == ["w-1"] and wols("anna") == [] and wols("alt") == ["w-1"]
assert cl["bert"].post("/api/wol/w-1/wake").status_code == 403                                                               # Lesen reicht nicht zum Aufwecken
wol.wake = lambda wid: 1
assert cl["cora"].post("/api/wol/w-1/wake").status_code == 200
page = lambda u: cl[u].get("/smarthome").get_data(as_text=True)
import re
def tab_ids(u): return set(re.findall(r'#(wol)\b', page(u)))
assert tab_ids("admin") and tab_ids("cora") and tab_ids("bert") and not tab_ids("anna")
it = wol.load(); it[0]["users"] = ["anna"]; wol._save(it)
assert not tab_ids("cora") and tab_ids("admin")                                                                                 # kein Rechner freigegeben: Reiter weg
print("WOL-RECHT OK")
