import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth
from auth import UserStore, UserError, PRESETS
webapp.opslog.log = lambda *a, **k: None

# 1) Hauptkonto = erstes Konto
path = os.path.join(tmp, "u_adm.json")
webapp.users = us = UserStore(path)
us.create("max", "michapass1")
assert us.get("max")["owner"] is True and us.get("max")["permissions"]["user_management"] == "write"
us.create("oma", "omapass12", {"dashboard": "write", "settings_geraete": "write", "user_management": "write"}, admin=False)        # Schreiben in der Tabelle macht nicht zum Admin
assert not us.get("oma").get("owner") and us.get("oma")["permissions"]["user_management"] == "read" and us.get("oma")["permissions"]["settings_geraete"] == "write"
us.create("zweit", "zweitpass12", None, admin=True)
assert auth.is_full_admin(us.get("zweit")["permissions"]) and all(v == "write" for v in us.get("zweit")["permissions"].values()) and not us.get("zweit").get("owner")
print("1) Hauptkonto/Admin-Kennzeichen OK")

# 2) Hauptkonto ist geschuetzt
for fn in (lambda: us.delete("max"), lambda: us.set_admin("max", False)):
    try: fn(); raise SystemExit("sollte scheitern")
    except UserError: pass
us.set_permissions("max", PRESETS["demo"]); assert us.get("max")["permissions"]["user_management"] == "write"
us.rename("max", "Max"); assert us.get("max")["owner"] is True                                        # umbenennen geht
us.update_password("max", "neuespass123")
us.set_admin("zweit", False); assert not auth.is_full_admin(us.get("zweit")["permissions"])
us.set_admin("zweit", True)
us.delete("zweit")                                                                                              # ein zugewiesener Admin ist loeschbar
print("2) Hauptkonto geschuetzt OK")

# 3) Altbestand ohne Kennzeichen: aeltester Administrator wird Hauptkonto
old = {"users": {"b": {"username": "b", "pw_hash": "x", "created": 200, "permissions": dict(PRESETS["admin"])},
                 "a": {"username": "a", "pw_hash": "x", "created": 100, "permissions": dict(PRESETS["user"])},
                 "c": {"username": "c", "pw_hash": "x", "created": 300, "permissions": dict(PRESETS["admin"])}}}
p2 = os.path.join(tmp, "u_old.json"); json.dump(old, open(p2, "w")); u2 = UserStore(p2)
assert [k for k, v in u2._users.items() if v.get("owner")] == ["b"], u2._users                                  # a ist kein Admin -> b (aeltester Admin)
assert json.load(open(p2))["users"]["b"]["owner"] is True                                                        # und gespeichert
assert auth.is_full_admin(u2.get("c")["permissions"])                                                            # bestehende Admins bleiben Admins
print("3) Migration OK")

# 4) Ueber die Oberflaeche/API
webapp.users = us = UserStore(os.path.join(tmp, "u_api.json"))
us.create("chef", "chefpass123"); us.create("oma", "omapass12", {"dashboard": "write", "settings_geraete": "write"})
c = webapp.app.test_client(); c.post("/login", data={"username": "chef", "password": "chefpass123"})
j = c.get("/api/users").get_json(); byn = {u["username"]: u for u in j["users"]}
assert byn["chef"]["admin"] and byn["chef"]["owner"] and not byn["oma"]["admin"] and "admin" not in j["presets"] and "admin" not in j["preset_labels"]
r = c.post("/api/users", json={"username": "vize", "password": "vizepass123", "admin": True}); assert r.status_code == 200 and r.get_json()["user"]["admin"] is True
r = c.post("/api/users", json={"username": "gast1", "password": "gastpass123", "permissions": {**PRESETS["admin"]}}); assert r.get_json()["user"]["admin"] is False       # Tabelle allein = kein Admin
assert c.patch("/api/users/oma", json={"admin": True}).get_json()["user"]["admin"] is True
assert c.patch("/api/users/oma", json={"admin": False}).get_json()["user"]["admin"] is False
assert c.patch("/api/users/chef", json={"admin": False}).status_code == 400
assert c.delete("/api/users/chef").status_code == 400
# anderer Admin darf das Hauptkonto nicht anfassen
v = webapp.app.test_client(); v.post("/login", data={"username": "vize", "password": "vizepass123"})
for m, body in (("patch", {"password": "hacker12345"}), ("patch", {"admin": False}), ("patch", {"permissions": PRESETS["demo"]}), ("delete", None)):
    r = getattr(v, m)("/api/users/chef", **({"json": body} if body else {})); assert r.status_code == 403, (m, r.status_code)
assert us.verify("chef", "chefpass123")
assert v.patch("/api/users/oma", json={"password": "omaneu1234"}).status_code == 200                           # andere Konten darf er
assert v.delete("/api/users/gast1").status_code == 200
# normales Konto: nie Benutzerverwaltung
m = webapp.app.test_client(); m.post("/login", data={"username": "oma", "password": "omaneu1234"})
assert m.get("/api/users").status_code == 403
# Seite
h = c.get("/admin").data.decode(); assert 'id="nu-isadmin"' in h and "u-isadmin" in h
print("4) API OK")
print("ADMIN OK")
