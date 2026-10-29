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
import auth
P = auth.PRESETS
assert auth.is_full_admin(auth.normalize_permissions(admin["permissions"]))        # erstes Konto = Administrator
u = users.create("anna", "userpass1", P["user"])
assert u["permissions"]["dashboard"] == "write" and u["permissions"]["user_management"] == "none"
d = users.create("gast", "demopass1", P["demo"])
assert d["permissions"]["dashboard"] == "read" and not auth.is_full_admin(auth.normalize_permissions(d["permissions"]))
import datetime
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
users.create("abgelaufen", "expiredpw1", P["demo"], expires=yesterday)

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
r = client.get("/admin")                                      # die Seite oeffnet fuer jedes Konto (Konto, Meine Ansicht) - die Administrator-Karten fehlen
assert r.status_code == 200, r.status_code
r = client.get("/api/inventory")
assert r.status_code == 403 and "devices" not in (r.get_json() or {}), (r.status_code, r.data[:100])      # Geraeteuebersicht nur fuer Administratoren
r = client.get("/api/config")                                     # lesbar, aber Zugangsdaten/Adressen sind leer (nur "..._set" zeigt, ob etwas hinterlegt ist)
j = r.get_json(); assert r.status_code == 200 and j["tibber_token"] == "" and j["cerbo_host"] == "" and j["tibber_token_set"] is True, r.status_code
client.post("/api/config", json={"dry_run": False, "tibber_token": "HACK"})                  # Felder ohne Schreibrecht werden stillschweigend uebergangen
assert cfg.get("dry_run") is True and cfg.get("tibber_token") == "x", cfg                       # Einstellungen aendern darf sie nicht
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
assert r.status_code == 200
r = client.get("/api/inventory"); assert r.status_code == 403, r.status_code
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
users.set_permissions("admin", P["user"])                      # Rechte eines Administrators aendern sich dadurch nicht
assert auth.is_full_admin(users.get("admin")["permissions"])
try:
    users.set_admin("admin", False)
    assert False, "haette UserError werfen muessen"
except UserError:
    pass
# ein zweiter Administrator: das Hauptkonto (erster Administrator) bleibt trotzdem unloeschbar und immer Administrator
users.set_admin("anna", True)
try:
    users.delete("admin")
    assert False, "Hauptkonto darf nicht geloescht werden"
except UserError:
    pass
users.set_admin("anna", False)                                 # ein zweiter Administrator darf wieder herabgestuft werden ...
users.set_admin("anna", True)                                  # ... und wieder befoerdert
assert users.get("admin") is not None

print("ROLES OK", root.split("/")[-1])

# ---- Admin-Zugaenge koennen kein Ablaufdatum bekommen
try:
    users.create("admin2", "adminpw123", P["admin"], expires="2099-01-01")
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
