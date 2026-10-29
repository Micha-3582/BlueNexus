"""Persoenlich ausblenden (Auge fuer Konten ohne Stift): Speichern, Rechte, Wirkung auf Dashboard/Geraeteliste, andere Konten unberuehrt."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, auth
from auth import UserStore

json.dump([{"id": "d1", "kind": "shelly", "mac": "AA", "channel": 0, "gen": 2, "ip": "192.168.50.60", "name": "Lampe", "icon": "💡", "model": "P", "show": True, "users": ["anna", "marie"]},
           {"id": "d2", "kind": "shelly", "mac": "BB", "channel": 0, "gen": 2, "ip": "192.168.50.61", "name": "Heizung", "icon": "🔥", "model": "P", "show": True, "users": ["anna", "marie"]},
           {"id": "d3", "kind": "shelly", "mac": "CC", "channel": 0, "gen": 2, "ip": "192.168.50.62", "name": "Nur Admin", "icon": "🔒", "model": "P", "show": True, "users": []}], open(shelly.DEVICES_PATH, "w"))
shelly.status = lambda d: {"online": True, "on": False, "power": None}

webapp.users = UserStore(os.path.join(tmp, "u_hide.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass1", {"dashboard": "write", "settings_geraete": "read"})
webapp.users.create("marie", "mariepass12", {"dashboard": "read"})
webapp.users.create("nodash", "nodashpass1", {"settings_geraete": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, M, R_, N = login("admin", "adminpass1"), login("anna", "annapass1"), login("marie", "mariepass12"), login("nodash", "nodashpass1")

# Speichern / Lesen
assert M.get("/api/hidden").get_json() == {"refs": []}
r = M.post("/api/hidden", json={"ref": "shelly:d1", "on": True}); assert r.status_code == 200 and r.get_json()["refs"] == ["shelly:d1"], r.get_data(as_text=True)
assert M.post("/api/hidden", json={"ref": "shelly:d1", "on": True}).get_json()["refs"] == ["shelly:d1"]          # doppelt: nur einmal
assert M.get("/api/hidden").get_json()["refs"] == ["shelly:d1"]
assert M.post("/api/hidden", json={"ref": "shelly:gibtsnicht", "on": True}).status_code == 404
assert M.post("/api/hidden", json={"ref": "shelly:d3", "on": True}).status_code == 404            # nur ausblenden, was das Konto auch sehen darf
for bad in ({}, {"ref": "x"}, {"ref": "foo:bar", "on": True}, {"ref": 5}):
    assert M.post("/api/hidden", json=bad).status_code == 400, bad
# Wirkung: eigenes Dashboard und eigene Geraeteseite kennen die Liste, andere Konten nicht
home = M.get("/").get_data(as_text=True); assert re.search(r'window\.HIDDEN = new Set\(\["shelly:d1"\]\)', home), "Dashboard kennt die Liste nicht"
_p = M.get("/smarthome"); print("smarthome", _p.status_code, "HIDDEN" in _p.get_data(as_text=True), "eyeBtn" in _p.get_data(as_text=True)); page = _p.get_data(as_text=True); assert 'window.HIDDEN = new Set(["shelly:d1"])' in page and "eyeBtn" in page
assert 'window.HIDDEN = new Set([])' in A.get("/").get_data(as_text=True) and 'window.HIDDEN = new Set([])' in R_.get("/").get_data(as_text=True)
# Die globale Einstellung des Administrators bleibt unberuehrt
assert next(d for d in shelly.load_devices() if d["id"] == "d1")["show"] is True
assert [d["id"] for d in A.get("/api/shelly?dashboard=1&light=1").get_json()] == ["d1", "d2", "d3"]
# wieder einblenden
assert M.post("/api/hidden", json={"ref": "shelly:d1", "on": False}).get_json()["refs"] == []
# Lesekonto darf auch, ohne Dashboard-Recht nicht
assert R_.post("/api/hidden", json={"ref": "shelly:d2", "on": True}).status_code == 200
assert N.get("/api/hidden").status_code == 403 and N.post("/api/hidden", json={"ref": "shelly:d2", "on": True}).status_code == 403
# nicht angemeldet
assert webapp.app.test_client().get("/api/hidden").status_code in (401, 302, 403)
# Persistenz ueber einen Neustart des Benutzerspeichers
webapp.users = UserStore(os.path.join(tmp, "u_hide.json"))
assert (webapp.users.get("marie") or {}).get("hidden_items") == ["shelly:d2"]
print("PERSOENLICH AUSBLENDEN OK")
