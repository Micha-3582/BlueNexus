"""Smart-Home-Seite (1.63.6): GET /api/shelly?soft=1 wartet hoechstens 2,5 s auf langsame/ausgeschaltete Geraete - wer noch nie gefragt wurde, kommt ohne Zustand
(Anzeige "wird abgefragt ..."); die Abfrage laeuft im Hintergrund weiter. Ohne soft (Dashboard, Regeln) bleibt alles wie bisher. Die Seite fragt nie zweimal gleichzeitig."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly

base = {"kind": "shelly", "gen": 1, "show": True, "switchable": True, "icon": "💡"}
shelly._save([{**base, "id": "fix", "name": "Schnell", "ip": "192.168.77.1"}, {**base, "id": "slow", "name": "Langsam", "ip": "192.168.77.2"}])
CALLS = []


def fake_status(d):
    CALLS.append(d["id"])
    if d["id"] == "slow":
        time.sleep(1.5)
    st = {"online": True, "on": True, "power": 5.0}
    shelly._st_cache[d["id"]] = (time.time(), dict(st))
    return st


shelly.status = fake_status
# kurze Wartezeit fuer den Test: die Seite wartet 2,5 s, das Geraet braucht hier laenger
import types
orig = shelly.list_with_status


def quick(*a, **k):
    if k.get("deadline"):
        k["deadline"] = 0.3
    return orig(*a, **k)


shelly.list_with_status = quick
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None
app = webapp.app
c = app.test_client()
assert c.post("/login", data={"username": "admin", "password": "adminpass1"}).status_code == 302

# --- soft: das langsame, noch nie gefragte Geraet kommt ohne Zustand, das schnelle mit
t0 = time.time()
r = c.get("/api/shelly?soft=1").get_json()
assert time.time() - t0 < 1.2, "soft darf nicht auf das langsame Geraet warten"
by = {d["id"]: d for d in r}
assert by["fix"].get("online") is True and "online" not in by["slow"], by
# --- Hintergrund-Abfrage laeuft zu Ende, naechste Anzeige hat den Stand
time.sleep(1.6)
by = {d["id"]: d for d in c.get("/api/shelly?soft=1").get_json()}
assert by["slow"].get("online") is True, by["slow"]
# --- ohne soft wird gewartet wie bisher (Dashboard)
shelly._st_cache.clear()
t0 = time.time()
r = c.get("/api/shelly").get_json()
assert {d["id"]: d.get("online") for d in r} == {"fix": True, "slow": True}

# --- Quelltext-Waechter: Seite fragt nie zweimal gleichzeitig, nutzt soft, Karten erst nach den Reitern sichtbar
src = open(os.path.join(os.path.dirname(os.path.abspath(webapp.__file__)), "templates", "admin.html"), encoding="utf-8").read()
assert "fetch('/api/shelly?soft=1')" in src and "shellyBusy" in src and "tabs-pending" in src

print("t_shelly_soft OK")
