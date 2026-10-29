"""Vom Admin vorgegebene Dashboard-Reihenfolge pro Benutzer: Vorrang eigene Wahl > Admin-Vorgabe > global."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth
from auth import UserStore, DASHBOARD_TILE_KEYS as K

webapp.users = UserStore(os.path.join(tmp, "users_order.json"))
webapp.users.create("admin", "adminpass1")
P = {"dashboard": "write", "account": "write", "settings_anzeige": "write"}
webapp.users.create("ina", "inapass123", P)
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")

def order(c):
    return c.get("/api/status").get_json()["ui"]["tile_order"]

# Standard: globale Reihenfolge (hier leer)
assert order(I) == []
lst = A.get("/api/users").get_json()
assert lst["global_order"] == K and [u for u in lst["users"] if u["username"] == "ina"][0]["dashboard_order"] is None

# Admin gibt eine Reihenfolge vor
mine = ["show_weather_card", "show_shelly_card", "show_virtual_card"]
want = mine + [k for k in K if k not in mine]
assert A.patch("/api/users/ina", json={"dashboard_order": want}).status_code == 200
assert order(I) == want
assert [u for u in A.get("/api/users").get_json()["users"] if u["username"] == "ina"][0]["dashboard_order"] == want
assert [x for x in order(A)] == []                                   # andere Konten unberuehrt

# unvollstaendige/fremde Schluessel werden vervollstaendigt bzw. verworfen
assert A.patch("/api/users/ina", json={"dashboard_order": ["show_weather_card", "gibtsnicht"]}).status_code == 200
o = order(I); assert o[0] == "show_weather_card" and sorted(o) == sorted(K) and "gibtsnicht" not in o

# Nicht-Admin darf die Vorgabe nicht aendern
assert I.patch("/api/users/ina", json={"dashboard_order": []}).status_code == 403

# "Meine Ansicht" des Kontos hat Vorrang vor der Vorgabe; GET liefert beides
assert A.patch("/api/users/ina", json={"dashboard_order": want}).status_code == 200
own = ["show_savings_card"] + [k for k in K if k != "show_savings_card"]
assert I.post("/api/my-tiles", json={"my_order": own}).status_code == 200
assert order(I) == own
j = I.get("/api/my-tiles").get_json(); assert j["my_order"] == own and j["admin_order"] == want
# eigene Wahl zuruecksetzen -> wieder die Vorgabe des Admins
assert I.post("/api/my-tiles", json={"my_order": K}).status_code == 200
assert order(I) == want

# Vorgabe entfernen -> wieder global
assert A.patch("/api/users/ina", json={"dashboard_order": None}).status_code == 200
assert order(I) == []

# beim Anlegen mitgeben
r = A.post("/api/users", json={"username": "neu", "password": "neupass1234", "permissions": P, "dashboard_order": want})
assert r.status_code == 200 and r.get_json()["user"]["dashboard_order"] == want
N = login("neu", "neupass1234"); assert order(N) == want
# --- Fall "Mathias": nur zwei Kacheln erlaubt, Admin stellt Wetter ueber die Schalter. Hat das Konto frueher "Meine Ansicht" gespeichert
# (ohne umzusortieren -> Standard-Reihenfolge), darf das die Vorgabe des Admins nicht verdraengen.
webapp.users.create("mathias", "mathias123", P, dashboard_tiles=["show_virtual_card", "show_weather_card"])
M = login("mathias", "mathias123")
two = ["show_weather_card", "show_virtual_card"]
assert A.patch("/api/users/mathias", json={"dashboard_order": two + [k for k in K if k not in two]}).status_code == 200
webapp.users.set_my_order("mathias", ["show_virtual_card", "show_weather_card"], explicit=False)          # Altlast: Standardreihenfolge der beiden, vervollstaendigt
o = order(M); assert o.index("show_weather_card") < o.index("show_virtual_card"), o
assert M.get("/api/my-tiles").get_json()["my_order"] is None                                  # "Meine Ansicht" zeigt keine veraltete eigene Reihenfolge
# bewusst eigene Reihenfolge gewinnt weiterhin
assert M.post("/api/my-tiles", json={"my_order": ["show_virtual_card", "show_weather_card"]}).status_code == 200
o = order(M); assert o.index("show_virtual_card") < o.index("show_weather_card"), "bewusst gewaehlt (auch wenn gleich der Standard) -> gewinnt gegen die Vorgabe"
webapp.users.set_dashboard_order("mathias", None)
assert M.post("/api/my-tiles", json={"my_order": ["show_weather_card", "show_virtual_card"]}).status_code == 200
o = order(M); assert o.index("show_weather_card") < o.index("show_virtual_card")
# --- Wem "Einstellungen: Dashboard" entzogen wird, bei dem wirkt die fruehere eigene Ansicht nicht mehr - es gilt die Vorgabe des Admins
webapp.users.create("mathias2", "mathias223", {"dashboard": "write", "account": "write"}, dashboard_tiles=["show_virtual_card", "show_weather_card", "show_live_values"])
M2 = login("mathias2", "mathias223")
adm = ["show_weather_card", "show_virtual_card"] + [k for k in K if k not in ("show_weather_card", "show_virtual_card")]
assert A.patch("/api/users/mathias2", json={"dashboard_order": adm}).status_code == 200
webapp.users.set_my_order("mathias2", ["show_virtual_card", "show_live_values", "show_weather_card"], explicit=True)        # frueher bewusst sortiert
webapp.users.set_my_tiles("mathias2", ["show_virtual_card"])                                                              # und Kacheln ausgeblendet
st = M2.get("/api/status").get_json()["ui"]
assert st["tile_order"] == adm, st["tile_order"]                                                                          # Recht fehlt -> Vorgabe des Admins
assert st["show_weather_card"] is True and st["show_live_values"] is True                                                 # eigenes Ausblenden wirkt auch nicht mehr
j = M2.get("/api/my-tiles").get_json(); assert j["my_order"] is None and j["my_tiles"] is None
# Recht zurueckgeben -> die eigene Ansicht wirkt wieder
P2 = {"dashboard": "write", "account": "write", "settings_anzeige": "read"}
assert A.patch("/api/users/mathias2", json={"permissions": {**{a: "none" for a in auth.AREA_IDS}, **P2}}).status_code == 200
st = M2.get("/api/status").get_json()["ui"]
assert st["tile_order"][:3] == ["show_virtual_card", "show_live_values", "show_weather_card"] and st["show_weather_card"] is False
print("TILE ORDER OK")
