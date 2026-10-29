import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
root = sys.argv[1]
import ps_common
webapp, store, cfg, tmp = ps_common.setup(root)
from auth import UserStore, UserError

# Frisches, isoliertes users.json statt der echten Datei im App-Ordner.
webapp.users = UserStore(os.path.join(tmp, "users.json"))
users = webapp.users

admin = users.create("admin", "adminpass1")
assert admin["role"] == "admin"
u = users.create("anna", "userpass1", role="user")
assert u["role"] == "user"
d = users.create("gast", "demopass1", role="demo")
assert d["role"] == "demo"
import datetime
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
users.create("abgelaufen", "expiredpw1", role="demo", expires=yesterday)

app = webapp.app
app.testing = True
client = app.test_client()


def login(name, pw):
    return client.post("/login", data={"username": name, "password": pw}, follow_redirects=False)


# ---- Admin darf alles
r = login("admin", "adminpass1")
assert r.status_code == 302, r.status_code
r = client.get("/admin")
assert r.status_code == 200, r.status_code
r = client.get("/api/config")
assert r.status_code == 200, r.status_code
r = client.get("/api/users")
assert r.status_code == 200 and len(r.get_json()["users"]) == 4, r.get_json()
client.post("/logout")

# ---- "user"-Rolle: Dashboard + Geraete schalten, aber keine Einstellungen/Regeln
r = login("anna", "userpass1")
assert r.status_code == 302
r = client.get("/admin")
assert r.status_code != 200, "user-Rolle darf /admin nicht sehen"
r = client.get("/api/config")
assert r.status_code == 403, r.status_code
r = client.get("/api/status")
assert r.status_code == 200, r.status_code                     # Dashboard-Daten bleiben lesbar
r = client.post("/api/rules", json={"device_id": "x", "on": []})
assert r.status_code == 403, r.status_code                     # Regeln anlegen ist ihr verwehrt
r = client.post("/api/shelly/does-not-exist/switch", json={"on": True})
assert r.status_code != 403, r.status_code                     # Geraete schalten ist erlaubt (404 wg. unbekanntem Geraet ist ok)
r = client.post("/api/override", json={"on": True})
assert r.status_code != 403, r.status_code
r = client.get("/api/users")
assert r.status_code == 403, r.status_code                     # Benutzerverwaltung bleibt Admin vorbehalten
client.post("/logout")

# ---- "demo"-Rolle: rein lesend, auch kein Geraete-Schalten
r = login("gast", "demopass1")
assert r.status_code == 302
r = client.get("/api/status")
assert r.status_code == 200
r = client.get("/admin")
assert r.status_code != 200
r = client.post("/api/shelly/does-not-exist/switch", json={"on": True})
assert r.status_code == 403, r.status_code
r = client.post("/api/override", json={"on": True})
assert r.status_code == 403, r.status_code
client.post("/logout")

# ---- Abgelaufener Zugang kann sich gar nicht erst anmelden
r = login("abgelaufen", "expiredpw1")
assert r.status_code == 401, r.status_code

# ---- Letzter Admin ist geschuetzt (nicht loeschbar/degradierbar)
try:
    users.delete("admin")
    assert False, "haette UserError werfen muessen"
except UserError:
    pass
try:
    users.set_role("admin", "user")
    assert False, "haette UserError werfen muessen"
except UserError:
    pass
# aber ein zweiter Admin macht das wieder moeglich
users.set_role("anna", "admin")
users.delete("admin")                                          # jetzt ok, anna ist noch Admin
assert users.get("admin") is None

print("ROLES OK", root.split("/")[-1])

# ---- Admin-Zugaenge koennen kein Ablaufdatum bekommen
try:
    users.create("admin2", "adminpw123", role="admin", expires="2099-01-01")
except UserError:
    pass
else:
    a2 = users.get("admin2")
    assert a2["expires"] is None, "Admin mit Ablaufdatum angelegt - Bug!"
try:
    users.set_expires("anna", "2099-01-01") if users.get("anna") else None
except Exception:
    pass
# anna ist inzwischen Admin (siehe oben) - Ablauf setzen muss scheitern
try:
    users.set_expires("anna", "2099-01-01")
    assert False, "haette scheitern muessen (Admin kann nicht ablaufen)"
except UserError:
    pass
print("ADMIN-NO-EXPIRY OK")
