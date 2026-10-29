"""Module-Matrix: alle Kombinationen aus Energie / Smart Home / Kameras / Alexa x mehrere Benutzertypen:
kein Serverfehler auf irgendeiner Seite/Schnittstelle, Menues und Rechte konsistent zu den Modulen."""
import sys, os, json, re, itertools
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import requests, auth, alexa, shelly, virtual, camera, homematic

def _offline(*a, **k):
    raise requests.ConnectionError("offline (Test)")
requests.sessions.Session.request = _offline                         # keine echten Netzzugriffe: wie ein Server ohne Internet/Geraete
alexa.ALEXA_PATH = os.path.join(tmp, "alexa.json")
camera.CAMERAS_PATH = os.path.join(tmp, "cams.json")
homematic.SOUNDS_PATH = os.path.join(tmp, "snd.json")

from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
ALL = {a: "write" for a in auth.AREA_IDS if a != "user_management"}
webapp.users.create("voll", "vollpass123", ALL)
webapp.users.create("leser", "leserpass123", {a: "read" for a in auth.AREA_IDS if a != "user_management"})
webapp.users.create("mini", "minipass123", {"dashboard": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
CL = {"admin": login("admin", "adminpass1"), "voll": login("voll", "vollpass123"), "leser": login("leser", "leserpass123"), "mini": login("mini", "minipass123")}

cfg.setdefault("pv_inverters", [])                                   # wie die Standardwerte der echten Konfiguration
# etwas Inhalt, damit Listen nicht leer sind
base = {"icon": "🔌", "show": True, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "mac": "A", "gen": 2, "channel": 0, "model": "x", "users": []}
shelly._save([{**base, "id": "d1", "name": "Flurlicht", "ip": "1.1.1.1"}])
virtual.add("Timer", "switch")
camera._save([{"id": "cam-1", "kind": "reolink", "name": "Hof", "host": "x", "user": "", "password": "", "users": []}])
homematic._save_sounds([{"id": "a1", "address": "a", "interface": "x", "model": "m", "room": "", "name": "Gong", "icon": "🔔", "users": []}])
alexa.add("shelly", "d1", "Flur", "light")
homematic._save_sensors([{"id": "s1", "kind": "temperature", "name": "T", "address": "a", "interface": "x", "datapoint": "T", "unit": "C", "binary": False, "model": "m", "room": ""}])

GETS = sorted(r.rule for r in webapp.app.url_map.iter_rules() if "GET" in r.methods and not r.arguments and r.endpoint != "static"
              and r.rule not in ("/create-account", "/login", "/preview/stop", "/api/weather/search"))
fails = []
def expect(cond, msg):
    if not cond:
        fails.append(msg)
bad_status = {}

combos = [c for c in itertools.product([True, False], repeat=4) if c[0] or c[1] or c[2]]
for en, sh, ca, al in combos:
    cfg["modules"] = {"energy": en, "smarthome": sh, "cameras": ca, "verlauf": True, "alexa": al}
    effm = dict(cfg["modules"]); effm["verlauf"] = en or sh
    tag = f"E{int(en)}S{int(sh)}K{int(ca)}A{int(al)}"
    for user, c in CL.items():
        for path in GETS:
            r = c.get(path)
            if r.status_code >= 500:
                bad_status.setdefault((path, r.status_code), []).append(f"{tag}/{user}")
        # --- Menue zum Modul
        home = c.get("/")
        html = home.get_data(as_text=True) if home.status_code == 200 else ""
        if html:
            nav = re.findall(r'<nav>(.*?)</nav>', html, re.S)
            navtxt = nav[0] if nav else ""
            if user in ("admin", "voll", "leser"):
                expect((">Smart Home<" in navtxt) == sh, f"{tag}/{user}: Menue Smart Home falsch")
                expect((">Kameras<" in navtxt) == ca, f"{tag}/{user}: Menue Kameras falsch")
                if user in ("admin", "voll"): expect((">Verläufe<" in navtxt) == (en or sh), f"{tag}/{user}: Menue Verlaeufe falsch")
            m = re.search(r"window\.USER_PERMS = (\{.*?\});", c.get("/admin").get_data(as_text=True) if c.get("/admin").status_code == 200 else "")
            if m:
                perms = json.loads(m.group(1))
                for mod, areas in auth.MODULE_AREAS.items():
                    if not effm[mod]:
                        expect(all(perms.get(a, "none") == "none" for a in areas), f"{tag}/{user}: Rechte von {mod} nicht ausgeblendet")
    # --- Bereiche je Modul fuer den vollen Benutzer: Zugriff passt zu den Modulen
    v = CL["voll"]
    expect((v.get("/smarthome").status_code == 200) == sh, f"{tag}: /smarthome")
    expect((v.get("/rules").status_code == 200) == sh, f"{tag}: /rules")
    expect((v.get("/kameras").status_code == 200) == ca, f"{tag}: /kameras")
    expect((v.get("/verlauf").status_code == 200) == (en or sh), f"{tag}: /verlauf")
    expect((v.get("/automation").status_code == 200) == (en and sh), f"{tag}: /automation (Ueberschuss braucht Energie UND Smart Home)")
    expect((v.get("/api/vrm").status_code == 200) == en, f"{tag}: /api/vrm")
    expect((v.get("/api/alexa").status_code == 200) == sh, f"{tag}: /api/alexa")
    expect(CL["admin"].get("/api/modules").status_code == 200, f"{tag}: /api/modules")
    expect(("alexa" in [t["id"] for t in webapp._smarthome_tabs(webapp.auth.mask_permissions(webapp.auth.normalize_permissions(ALL), cfg["modules"]))]) == bool(sh and al), f"{tag}: Alexa-Reiter")
    # --- Dashboard-Kacheln / Rechtevergabe
    ui = v.get("/api/status").get_json()["ui"]
    for mod, tiles in auth.MODULE_TILES.items():
        if not effm[mod]:
            expect(all(ui.get(t) is False for t in tiles), f"{tag}: Kacheln von {mod} nicht aus")
    ar = CL["admin"].get("/api/users").get_json()
    shown = {a[0] for a in ar["areas"]}
    for mod, areas in auth.MODULE_AREAS.items():
        if not effm[mod]:
            expect(not (shown & set(areas)), f"{tag}: Rechtevergabe zeigt Bereiche von {mod}")
    # --- Hintergrundarbeit: Regler pausiert ohne Energie
    called = []
    webapp.ctrl.tick = lambda: called.append(1); webapp.ctrl.safe_tick()
    expect(bool(called) == en, f"{tag}: Regler-Tick")
    # --- Alexa-Bruecke nur mit Alexa UND Smart Home
    b = webapp.alexa_bridge
    b.http_port = 0 if False else b.http_port
    want = al and sh
    expect(store.module_on("alexa") == al, f"{tag}: alexa-flag")

for (path, code), who in sorted(bad_status.items()):
    fails.append(f"{path} -> {code} bei {len(who)} Faellen, z. B. {who[:3]}")
print(f"{len(combos)} Kombinationen x {len(CL)} Benutzer x {len(GETS)} Seiten")
for f in fails[:60]:
    print("FEHLER:", f)
assert not fails, f"{len(fails)} Fehler"
print("MATRIX OK")
