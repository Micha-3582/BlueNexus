"""Benutzerliste "Zuletzt aktiv": zaehlt nur echte Bedienung (Seite oeffnen, schalten/speichern), nicht Hintergrundabfragen, Dateien,
Fehlerantworten oder die Vorschau; gespeichert wird hoechstens alle 10 Minuten; die Liste liefert das Feld."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth
from auth import UserStore

webapp.users = UserStore(os.path.join(tmp, "users.json"))
users = webapp.users
users.create("admin", "adminpass1")
users.create("niklas", "niklaspass1", auth.PRESETS["smarthome"])
users.create("berta", "bertapass12", auth.PRESETS["smarthome"])


def client(name, pw):
    c = webapp.app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


def active(name):
    return users.get(name).get("last_active")


N = client("niklas", "niklaspass1")
assert users.get("niklas").get("last_login") and active("niklas") is None, "Anmelden allein ist noch keine Bedienung"

# 1) Hintergrundabfragen und Dateien zaehlen nicht
assert N.get("/api/status").status_code == 200 and active("niklas") is None
assert N.get("/api/automation/unread").status_code in (200, 403) and active("niklas") is None
N.get("/static/theme.css"); N.get("/sw.js"); N.get("/manifest.webmanifest")
assert active("niklas") is None, "Dateien duerfen nicht zaehlen"

# 2) eine Seite oeffnen zaehlt
t0 = time.time()
assert N.get("/").status_code == 200
a1 = active("niklas")
assert a1 and t0 - 1 <= a1 <= time.time() + 1, a1
assert active("berta") is None and active("admin") is None, "nur das bedienende Konto"

# 3) hoechstens alle 10 Minuten speichern
mt = os.path.getmtime(users.path)
time.sleep(0.05)
N.get("/"); N.get("/smarthome")
assert active("niklas") == a1 and os.path.getmtime(users.path) == mt, "innerhalb von 10 Minuten wird nichts neu gespeichert"
users._users["niklas"]["last_active"] = time.time() - 700; users._active_seen.clear(); users._write()
N.get("/")
assert time.time() - active("niklas") < 5, "nach 10 Minuten wird neu gespeichert"

# 4) Schalten/Speichern (POST) zaehlt; ein Aufruf mit Fehler nicht
A = client("admin", "adminpass1")
assert active("admin") is None
assert A.post("/api/config", json={"dry_run": True}).status_code == 200 and active("admin"), "POST zaehlt"
users._users["admin"]["last_active"] = time.time() - 700; users._active_seen.clear(); users._write()
before = active("admin")
assert A.post("/api/shelly/gibt-es-nicht/switch", json={"on": True}).status_code >= 400 and active("admin") == before, "fehlgeschlagene Bedienung zaehlt nicht"

# 5) Vorschau ("Als Benutzer ansehen"): zaehlt weder fuer das angesehene Konto noch fuer den Administrator
users._users["berta"].pop("last_active", None); users._active_seen.clear(); users._write()
with A.session_transaction() as s: s["view_as"] = "berta"
before_admin = active("admin")
assert A.get("/").status_code == 200
assert active("berta") is None and active("admin") == before_admin, "Vorschau darf nichts zaehlen"

# 6) die Benutzerliste liefert das Feld; touch() fuer unbekannte Konten ist harmlos
with A.session_transaction() as s: s.pop("view_as", None)
lst = {u["username"].lower(): u for u in A.get("/api/users").get_json()["users"]}
assert lst["niklas"]["last_active"] and lst["berta"]["last_active"] is None and "last_login" in lst["niklas"], lst["niklas"]
assert users.touch("gibtsnicht") is False

# 7) die Seite hat die Spalte
h = A.get("/admin").get_data(as_text=True)
assert "Zuletzt aktiv" in h and "last_active" in h
assert 'class="u-expires"' not in h and "u-exp" in h and "uiExpiry" in h, "Ablauf: Kalender-Symbol mit Fenster statt Datumsfeld in jeder Zeile"
print("LAST ACTIVE OK", sys.argv[1].split("/")[-1])
