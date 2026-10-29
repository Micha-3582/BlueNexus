"""Sitzungen (Sicherheitsprüfung S-01/S-02, 1.28.0): Eine Sitzung endet, wenn das Passwort des Kontos geändert/zurückgesetzt wird (anderer Zähler)
oder das Konto gelöscht und unter gleichem Namen neu angelegt wird (andere Kennung). Die eigene Sitzung bleibt bei der eigenen Änderung gültig,
Cookies aus der Zeit vor der Änderung (ohne Kennung) gelten einmalig weiter."""
import sys, os, json, copy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth
from auth import UserStore

path = os.path.join(tmp, "u.json")
webapp.users = UserStore(path); users = webapp.users
users.create("admin", "adminpass1")
users.create("gast", "gastpass123", auth.PRESETS["user"])


def login(name, pw):
    c = webapp.app.test_client()
    r = c.post("/login", data={"username": name, "password": pw, "remember": "1"})
    assert r.status_code == 302, (name, r.status_code)
    return c


def ok(c, url="/api/status"):
    return c.get(url).status_code == 200


def clone(c):
    """Kopie des Cookies (wie ein gestohlenes Cookie in einem anderen Browser)."""
    n = webapp.app.test_client()
    with c.session_transaction() as s:
        data = dict(s)
    with n.session_transaction() as s:
        s.update(data)
        s.permanent = True
    return n


A = login("admin", "adminpass1")
G1, G2 = login("gast", "gastpass123"), login("gast", "gastpass123")
G_stolen = clone(G1)
assert ok(A) and ok(G1) and ok(G2) and ok(G_stolen)
assert users.get("gast")["uid"] and users.get("gast")["sess_epoch"] == 0

# ---- 1) Administrator setzt das Passwort eines anderen Kontos neu: alle Sitzungen dieses Kontos enden, die eigene nicht
r = A.patch("/api/users/gast", json={"password": "neuespass1234"}); assert r.status_code == 200, r.get_data(as_text=True)
assert not ok(G1) and not ok(G2) and not ok(G_stolen), "alte Sitzungen muessen enden"
assert G1.get("/api/status").status_code == 401 and G1.get("/", follow_redirects=False).status_code == 302
assert ok(A), "die Sitzung des Administrators bleibt"
assert ok(login("gast", "neuespass1234")), "mit dem neuen Passwort geht die Anmeldung"
assert "uid" not in json.dumps(A.get("/api/users").get_json()) and "sess_epoch" not in json.dumps(A.get("/api/users").get_json()), "Kennung nicht ausgeben"

# ---- 2) Eigenes Passwort aendern: diese Sitzung bleibt, die anderen Geraete enden (auch ein gestohlenes Cookie)
G_a, G_b = login("gast", "neuespass1234"), login("gast", "neuespass1234"); G_steal = clone(G_b)
r = G_a.post("/api/account", json={"current": "neuespass1234", "new": "nochneuer123", "new2": "nochneuer123"}); assert r.status_code == 200, r.get_data(as_text=True)
assert ok(G_a), "die eigene Sitzung bleibt"
assert not ok(G_b) and not ok(G_steal), "andere Geraete werden abgemeldet"
assert ok(login("gast", "nochneuer123"))

# ---- 3) Eigenen Benutzernamen aendern: die Sitzung bleibt; ein neues Konto mit dem alten Namen erbt sie nicht
G_c = login("gast", "nochneuer123"); G_old = clone(G_c)
r = G_c.post("/api/account", json={"current": "nochneuer123", "username": "gast2"}); assert r.status_code == 200, r.get_data(as_text=True)
assert ok(G_c), "umbenannt: die Sitzung bleibt"
users.create("gast", "gastpass9999", auth.PRESETS["admin"])                      # jemand legt den alten Namen als Administrator neu an
assert not ok(G_old, "/api/apikeys") and G_old.get("/api/apikeys").status_code in (401, 403), "altes Cookie darf nicht auf das neue Konto passen"
users.delete("gast")

# ---- 4) S-02: Konto loeschen und unter gleichem Namen neu anlegen: das alte Cookie gilt nicht fuer das neue Konto
users.create("ehemals", "ehemalspass1", auth.PRESETS["user"])
E_old = login("ehemals", "ehemalspass1"); assert ok(E_old)
users.delete("ehemals")
users.create("ehemals", "ganzandersss1", auth.PRESETS["admin"])
assert E_old.get("/api/apikeys").status_code in (401, 403) and not ok(E_old), "das neue Konto darf die alte Sitzung nicht erben"
assert ok(login("ehemals", "ganzandersss1"), "/api/apikeys")

# ---- 5) Passwort vergessen (Wiederherstellungsschluessel): Sitzungen enden
users.create("vergess", "vergesspass1", auth.PRESETS["user"])
key = users.set_recovery("vergess")
V = login("vergess", "vergesspass1"); V_steal = clone(V); assert ok(V) and ok(V_steal)
c = webapp.app.test_client()
r = c.post("/api/forgot/reset", json={"username": "vergess", "method": "key", "secret": key, "password": "zurueckgesetzt1", "password2": "zurueckgesetzt1"}); assert r.status_code == 200, r.get_data(as_text=True)
assert not ok(V) and not ok(V_steal), "nach dem Zuruecksetzen enden alle Sitzungen"

# ---- 6) Das eigene Passwort laesst sich ueber die Benutzerverwaltung nicht aendern (nur unter "Konto & Zugang", mit aktuellem Passwort): nichts aendert sich
A2 = login("admin", "adminpass1"); A2_other = login("admin", "adminpass1")
r = A2.patch("/api/users/admin", json={"password": "adminneu1234"}); assert r.status_code == 400, r.status_code
assert ok(A2) and ok(A2_other) and ok(login("admin", "adminpass1")), "abgelehnt: alle Sitzungen und das alte Passwort bleiben"
# Eigenes Passwort als Administrator ueber "Konto & Zugang": eigene Sitzung bleibt, die andere endet
r = A2.post("/api/account", json={"current": "adminpass1", "new": "adminneu1234", "new2": "adminneu1234"}); assert r.status_code == 200, r.get_data(as_text=True)
assert ok(A2) and not ok(A2_other), "eigene Sitzung bleibt, die andere endet"
assert ok(login("admin", "adminneu1234"))

# ---- 7) Cookie aus der Zeit vor der Aenderung (nur Benutzername, keine Kennung): gilt einmalig weiter und bekommt die Kennung
users.create("alt", "altpass12345", auth.PRESETS["user"])
raw_ = json.load(open(path, encoding="utf-8"))                                  # Konto "von vor dem Update": Datei ohne Kennung, Zaehler und Merkmal
for f_ in ("uid", "sess_epoch", "legacy_session_ok"): raw_["users"]["alt"].pop(f_, None)
json.dump(raw_, open(path, "w", encoding="utf-8"))
webapp.users = users = UserStore(path)
L = webapp.app.test_client()
with L.session_transaction() as s:
    s["user"] = "alt"; s.permanent = True
assert ok(L), "altes Cookie ohne Kennung muss einmal weiter gelten"
with L.session_transaction() as s:
    assert s.get("uid") == users.get("alt")["uid"] and s.get("ep") == 0, dict(s)
users.update_password("alt", "altneu123456")
assert not ok(L), "danach gilt die Kennung: nach der Passwortaenderung endet es"

# ---- 8) Konten ohne Kennung (aeltere users.json) bekommen sie beim Einlesen, und sie bleibt nach einem Neustart gleich
raw = json.load(open(path, encoding="utf-8"))
for u in raw["users"].values():
    u.pop("uid", None); u.pop("sess_epoch", None)
json.dump(raw, open(path, "w", encoding="utf-8"))
fresh = UserStore(path)
ids = {k: fresh.get(k)["uid"] for k in ("admin", "alt")}
assert all(ids.values()) and len(set(ids.values())) == 2 and fresh.get("admin")["sess_epoch"] == 0
again = UserStore(path)
assert {k: again.get(k)["uid"] for k in ("admin", "alt")} == ids, "Kennung muss nach dem Neustart gleich bleiben"
assert "uid" in json.load(open(path, encoding="utf-8"))["users"]["admin"], "wurde gespeichert"
print("SITZUNG OK", sys.argv[1].split("/")[-1])
