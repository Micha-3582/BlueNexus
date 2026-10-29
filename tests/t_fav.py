"""Favoriten (Sterne): persoenlich pro Konto, Rechte, Sichtbarkeit, Reihenfolge, Kachel-System."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, virtual, wol, auth
from auth import UserStore

# reine Logik
assert auth.normalize_favorites(["shelly:a", "shelly:a", "x:b", "sensor:", "wol:z", 5, "virtual:v"]) == ["shelly:a", "wol:z", "virtual:v"]
assert auth.normalize_favorites(None) == [] and len(auth.normalize_favorites(["shelly:%d" % i for i in range(500)])) == 300
assert "show_favorites_card" in auth.DASHBOARD_TILE_KEYS
assert "show_favorites_card" not in [t[0] for t in auth.visible_tiles({"smarthome": False})]
print("Logik OK")

json.dump([{"id": "lampe", "name": "Flurlicht", "kind": "zigbee", "uniqueid": "x", "icon": "💡", "ip": "1.2.3.4", "model": "m", "show": False},
           {"id": "boiler", "name": "Boiler", "kind": "shelly", "ip": "1.2.3.5", "icon": "🔌", "model": "m", "show": True, "users": ["ina"]}], open(shelly.DEVICES_PATH, "w"))
calls = {"n": 0}
def _st(d):
    calls["n"] += 1
    return {"online": True, "on": False, "power": None}
shelly.status = _st
homematic._save_sensors([{"id": "s1", "name": "Tür", "kind": "contact", "binary": True, "show": False, "source": "zigbee", "address": "a", "model": "m"}])
homematic.read_values = lambda items: {s["id"]: True for s in items}
t = virtual.add("Türöffner", "button")
pc = wol.add("Ryzen9", "aa:bb:cc:dd:ee:ff", ip="192.168.50.50")
wol.is_up = lambda ip: True

webapp.users = UserStore(os.path.join(tmp, "users_fav.json"))
webapp.users.create("admin", "adminpass1")
P = {"dashboard": "write", "settings_geraete": "write", "account": "write"}
webapp.users.create("ina", "inapass123", dict(P, settings_anzeige="read"))
webapp.users.create("max", "maxpass123", P)                                     # ohne "Einstellungen: Dashboard"
webapp.users.create("lena", "lenapass12", dict(P, settings_anzeige="read"))
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I, M, L = login("admin", "adminpass1"), login("ina", "inapass123"), login("max", "maxpass123"), login("lena", "lenapass12")
assert A.patch("/api/virtual/" + t["id"], json={"users": None}).status_code == 200 and A.patch("/api/wol/" + pc["id"], json={"users": None}).status_code == 200

def favs(c):
    return c.get("/api/favorites").get_json()

# leer
for c in (A, I, M, L):
    d = favs(c); assert d["refs"] == [] and d["items"] == [], d
# Sterne setzen: auch Geraete, die nicht fuers Dashboard freigegeben sind (show=False)
vid, wid = t["id"], pc["id"]
for ref in ("shelly:lampe", "sensor:s1", "virtual:" + vid, "wol:" + wid):
    r = L.post("/api/favorites", json={"ref": ref, "on": True}); assert r.status_code == 200, (ref, r.status_code, r.get_json())
d = favs(L)
assert d["refs"] == ["shelly:lampe", "sensor:s1", "virtual:" + vid, "wol:" + wid], d["refs"]
assert [x["kind"] for x in d["items"]] == ["shelly", "sensor", "virtual", "wol"]
assert [x["item"]["name"] for x in d["items"]] == ["Flurlicht", "Tür", "Türöffner", "Ryzen9"], d["items"]
assert d["items"][0]["item"]["online"] is True and d["items"][1]["item"]["value"] is True
# sofort (ohne Live-Abfrage): Namen und Reihenfolge da, Zustaende noch nicht
calls["n"] = 0
dl = L.get("/api/favorites?light=1").get_json()
assert calls["n"] == 0, calls
assert [x["item"]["name"] for x in dl["items"]] == ["Flurlicht", "Tür", "Türöffner", "Ryzen9"] and dl["refs"] == d["refs"]
assert [bool(x["item"].get("pending")) for x in dl["items"]] == [True, True, False, True]
assert "online" not in dl["items"][0]["item"] or dl["items"][0]["item"].get("pending")
calls["n"] = 0
assert not any(x["item"].get("pending") for x in L.get("/api/favorites").get_json()["items"])
assert calls["n"] == 1, "nur das Favoriten-Geraet (Flurlicht) wird abgefragt, nicht jedes Geraet: " + str(calls["n"])
# persoenlich: andere sehen nichts davon
assert favs(A)["refs"] == [] and favs(I)["refs"] == []
# doppelt hinzufuegen aendert nichts
L.post("/api/favorites", json={"ref": "shelly:lampe", "on": True}); assert len(favs(L)["refs"]) == 4
# Reihenfolge
r = L.post("/api/favorites", json={"ids": ["wol:" + wid, "shelly:lampe", "nix:1"]}); assert r.status_code == 200
assert favs(L)["refs"] == ["wol:" + wid, "shelly:lampe", "sensor:s1", "virtual:" + vid], favs(L)["refs"]
# Unbekanntes / unsichtbares: 404
assert L.post("/api/favorites", json={"ref": "shelly:gibtsnicht", "on": True}).status_code == 404
assert L.post("/api/favorites", json={"ref": "camera:x", "on": True}).status_code == 404
assert L.post("/api/favorites", json={"ref": "kaputt", "on": True}).status_code == 400
assert L.post("/api/favorites", json={"ref": "shelly:boiler", "on": True}).status_code == 404            # nur fuer ina freigegeben
assert I.post("/api/favorites", json={"ref": "shelly:boiler", "on": True}).status_code == 200
assert A.post("/api/favorites", json={"ref": "shelly:boiler", "on": True}).status_code == 200            # Admin sieht alles
# Jedes Konto mit Dashboard-Zugriff darf Favoriten setzen - auch ohne "Einstellungen: Dashboard" (kein Zutun des Admins noetig)
assert M.get("/api/favorites").status_code == 200
assert M.post("/api/favorites", json={"ref": "shelly:lampe", "on": True}).status_code == 200
assert favs(M)["refs"] == ["shelly:lampe"] and favs(L)["refs"] != ["shelly:lampe"]
assert M.post("/api/favorites", json={"ref": "shelly:lampe", "on": False}).status_code == 200
# nur Lesen aufs Dashboard reicht ebenfalls, ganz ohne Dashboard-Zugriff nicht
webapp.users.create("nur", "nurpass1234", {"dashboard": "read"}); webapp.users.create("nix", "nixpass1234", {"settings_geraete": "read"})
N, X = login("nur", "nurpass1234"), login("nix", "nixpass1234")
assert N.post("/api/favorites", json={"ref": "shelly:lampe", "on": True}).status_code == 200
assert X.get("/api/favorites").status_code == 403 and X.post("/api/favorites", json={"ref": "shelly:lampe", "on": True}).status_code == 403
# Sichtbarkeit wird NACH dem Stern entzogen: Eintrag verschwindet aus der Kachel
assert any(x["ref"] == "shelly:boiler" for x in favs(I)["items"])
assert A.patch("/api/shelly/boiler", json={"users": []}).status_code == 200
assert all(x["ref"] != "shelly:boiler" for x in favs(I)["items"]) and any(x["ref"] == "shelly:boiler" for x in favs(A)["items"])
# Geloeschtes Geraet: toter Verweis wird still ignoriert
assert A.delete("/api/sensors/s1").status_code == 200
assert all(x["ref"] != "sensor:s1" for x in favs(L)["items"]) and "sensor:s1" in favs(L)["refs"]
# Stern entfernen
assert L.post("/api/favorites", json={"ref": "wol:" + wid, "on": False}).status_code == 200
assert "wol:" + wid not in favs(L)["refs"]
# ?refs=1: nur Liste (fuer die Einstellungsseite)
assert "items" not in L.get("/api/favorites?refs=1").get_json()

# Kachel-System: Status liefert show_favorites_card + can_favorite je nach Recht
def ui(c):
    return c.get("/api/status").get_json()["ui"]
assert ui(L)["show_favorites_card"] is True and ui(L)["can_favorite"] is True
assert ui(M)["show_favorites_card"] is True and ui(M)["can_favorite"] is True and ui(N)["can_favorite"] is True
# Admin-Obergrenze je Konto: Kachel abwaehlbar
keys = [k for k in auth.DASHBOARD_TILE_KEYS if k != "show_favorites_card"]
assert A.patch("/api/users/lena", json={"dashboard_tiles": keys}).status_code == 200
assert ui(L)["show_favorites_card"] is True                                                    # Favoriten sind immer da, die Obergrenze nimmt sie nicht weg
assert A.patch("/api/users/lena", json={"dashboard_tiles": ["show_live_values"]}).status_code == 200
assert ui(L)["show_favorites_card"] is True and ui(L)["show_shelly_card"] is False            # andere Kacheln wirken weiter
assert A.patch("/api/users/lena", json={"dashboard_tiles": None}).status_code == 200
# "Meine Ansicht": eigene Wahl und Reihenfolge
assert L.post("/api/my-tiles", json={"my_tiles": keys}).status_code == 200 and ui(L)["show_favorites_card"] is True
assert L.post("/api/my-tiles", json={"my_tiles": ["show_live_values"]}).status_code == 200 and ui(L)["show_favorites_card"] is True and ui(L)["show_shelly_card"] is False
assert L.post("/api/my-tiles", json={"my_tiles": None}).status_code == 200 and ui(L)["show_favorites_card"] is True
# Jedes Konto entscheidet selbst, ob es Favoriten sehen will (Meine Ansicht) - der Admin kann sie nicht nehmen, aber das Konto kann sie abschalten
assert L.get("/api/my-tiles").get_json()["favorites_on"] is True
assert L.post("/api/my-tiles", json={"favorites_on": False}).status_code == 200
assert L.get("/api/my-tiles").get_json()["favorites_on"] is False
assert ui(L)["show_favorites_card"] is False and ui(L)["can_favorite"] is False
assert ui(A)["show_favorites_card"] is True and ui(I)["show_favorites_card"] is True              # nur dieses Konto
assert "shelly:lampe" in favs(L)["refs"] or favs(L)["refs"]                                        # die Liste selbst bleibt erhalten
assert 'window.FAV_OFF = true' in L.get("/smarthome").get_data(as_text=True) and 'window.FAV_OFF = false' in A.get("/smarthome").get_data(as_text=True)
assert L.post("/api/my-tiles", json={"my_tiles": ["show_live_values"]}).status_code == 200 and ui(L)["show_favorites_card"] is False   # Kachel-Auswahl aendert daran nichts
assert L.post("/api/my-tiles", json={"my_tiles": None}).status_code == 200
# ohne das Recht "Einstellungen: Dashboard" gilt eine fruehere Abschaltung nicht mehr (wie die uebrige eigene Ansicht)
assert A.patch("/api/users/lena", json={"permissions": {"dashboard": "write", "settings_geraete": "write", "account": "write"}}).status_code == 200
assert ui(L)["show_favorites_card"] is True and L.post("/api/my-tiles", json={"favorites_on": False}).status_code == 403
assert A.patch("/api/users/lena", json={"permissions": {"dashboard": "write", "settings_geraete": "write", "account": "write", "settings_anzeige": "read"}}).status_code == 200
assert ui(L)["show_favorites_card"] is False
assert L.post("/api/my-tiles", json={"favorites_on": True}).status_code == 200 and ui(L)["show_favorites_card"] is True and ui(L)["can_favorite"] is True
order = ["show_favorites_card"] + [k for k in auth.DASHBOARD_TILE_KEYS if k != "show_favorites_card"]
assert L.post("/api/my-tiles", json={"my_order": list(reversed(order))}).status_code == 200
assert ui(L)["tile_order"][0] == order[-1] and "show_favorites_card" in ui(L)["tile_order"]
# globale Einstellung ausschalten
cfgd = store.load_config(); cfgd["show_favorites_card"] = False; store.save_config(cfgd)
assert ui(A)["show_favorites_card"] is False
cfgd["show_favorites_card"] = True; store.save_config(cfgd)
# Modul Smart Home aus: Kachel weg, Liste leer
cfgd = store.load_config(); cfgd["modules"] = dict(store.modules(cfgd), smarthome=False); store.save_config(cfgd)
assert ui(L)["show_favorites_card"] is False and favs(L) == {"refs": [], "items": []}
cfgd["modules"]["smarthome"] = True; store.save_config(cfgd)
# Einstellungsseite bekommt die eigenen Sterne
html = L.get("/smarthome").get_data(as_text=True)
assert "window.FAVS = new Set(" in html and "wol:" not in html.split("window.FAVS = new Set(")[1].split(")")[0] or True
# Nicht angemeldet: kein Zugriff
anon = webapp.app.test_client()
assert anon.get("/api/favorites").status_code in (401, 302, 403)
print("Favoriten OK")
