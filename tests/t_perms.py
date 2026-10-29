import sys, os, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
root = sys.argv[1]
import ps_common
webapp, store, cfg, tmp = ps_common.setup(root)
import auth
from auth import UserStore, UserError, PRESETS, normalize_permissions

webapp.users = UserStore(os.path.join(tmp, "users.json"))
users = webapp.users

admin = users.create("admin", "adminpass1")                       # ohne Argument -> Volladmin (create_account-Fall)
assert admin["permissions"]["user_management"] == "write"
anna = users.create("anna", "userpass1", permissions=PRESETS["user"])
gast = users.create("gast", "demopass1", permissions=PRESETS["demo"])
# frei zusammengestellte Rechte: darf Tarif SEHEN, VRM SCHREIBEN, sonst nichts
custom_perms = normalize_permissions({"settings_tarif": "read", "settings_vrm": "write"})
custom = users.create("custom", "custompass1", permissions=custom_perms)

cfg["tibber_token"] = "GEHEIM-TOKEN-123"
app = webapp.app
app.testing = True
client = app.test_client()


def login(name, pw):
    return client.post("/login", data={"username": name, "password": pw}, follow_redirects=False)


# ---- Admin (Volladmin): sieht alles inkl. Token, darf alles
login("admin", "adminpass1")
r = client.get("/api/config")
assert r.status_code == 200
j = r.get_json()
assert j["tibber_token"] == "GEHEIM-TOKEN-123", j.get("tibber_token")
r = client.get("/api/users")
assert r.status_code == 200 and len(r.get_json()["users"]) == 4
r = client.get("/admin")
assert r.status_code == 200
client.post("/logout")

# ---- anna (Preset "user"): Dashboard schreiben, alles andere nichts - /admin bleibt trotzdem
# erreichbar (jeder darf hin, wegen "Konto & Zugang" + "Meine Ansicht"), nur ohne Einstellungs-Karten
login("anna", "userpass1")
r = client.get("/admin")
assert r.status_code == 200, "jeder darf /admin oeffnen (Konto & Zugang / Meine Ansicht sind immer da)"
h = r.get_data(as_text=True)
assert 'id="acc-username"' in h and 'id="my-tile-toggles"' in h                        # immer da (Konto & Meine Ansicht)
r = client.get("/api/status")
assert r.status_code == 200
r = client.post("/api/shelly/unbekannt/switch", json={"on": True})
assert r.status_code != 403
r = client.get("/api/config")
assert r.status_code == 200          # api_config selbst blockt nicht global
j = r.get_json()
assert j["tibber_token"] == "" and j["tibber_token_set"] is True, j    # Token nie sichtbar ohne settings_tarif=write
r = client.post("/api/config", json={"tibber_token": "BOESE-UEBERSCHRIEBEN", "app_display_name": "Hack"})
assert r.status_code == 200                                            # wird nicht abgelehnt, aber leise ignoriert
client.post("/logout")
assert cfg["tibber_token"] == "GEHEIM-TOKEN-123", "Token haette NICHT ueberschrieben werden duerfen!"
assert cfg.get("app_display_name") != "Hack", "app_display_name (settings_anzeige) haette anna nicht aendern duerfen"

# ---- gast (Preset "demo"): sieht alle Einstellungen (lesend), aber Token bleibt verborgen, nichts schaltbar
login("gast", "demopass1")
r = client.get("/admin")
assert r.status_code == 200, "demo-Preset hat read auf alle settings_* - muss /admin sehen duerfen"
r = client.get("/api/config")
j = r.get_json()
assert j["tibber_token"] == "" and "app_display_name" in j and j["app_display_name"] != "Hack"   # Rest sichtbar, nur Token verborgen
r = client.post("/api/shelly/unbekannt/switch", json={"on": True})
assert r.status_code == 403
r = client.post("/api/config", json={"app_display_name": "Hack2"})
assert r.status_code == 200
client.post("/logout")
assert cfg.get("app_display_name") != "Hack2", "demo (nur read auf settings_anzeige) haette nichts aendern duerfen"

# ---- custom: settings_tarif=read (Token verborgen), settings_vrm=write (Ansehen ja; VRM-Zugangsdaten ersetzen seit 1.28.1 nur Administratoren)
login("custom", "custompass1")
r = client.get("/api/config")
assert r.get_json()["tibber_token"] == ""
r = client.get("/admin")
assert r.status_code == 200
r = client.post("/api/vrm/credentials", json={"installation_id": "123", "token": "vrm-tok"})
assert r.status_code == 403, r.get_json()          # Zugaenge ersetzen nur Administratoren, auch mit Schreibrecht im Bereich
assert client.get("/api/vrm").status_code == 200     # Ansehen bleibt moeglich
r = client.post("/api/notify/credentials", json={"token": "x", "chat_id": "1"})
assert r.status_code == 403          # kein Zugriff auf settings_meldungen
r = client.get("/api/users")
assert r.status_code == 403          # keine Benutzerverwaltung
client.post("/logout")

# ---- Hauptkonto (erstes Konto) ist immer Administrator und nie loeschbar; Admin ist ein eigenes Kennzeichen
users.set_permissions("admin", PRESETS["demo"])                       # Rechte-Tabelle aendert bei Administratoren nichts
assert users.get("admin")["permissions"]["user_management"] == "write" and users.get("admin")["owner"] is True
for fn in (lambda: users.set_admin("admin", False), lambda: users.delete("admin")):
    try: fn(); assert False
    except UserError: pass
users.set_admin("anna", True); assert users.get("anna")["permissions"]["user_management"] == "write" and not users.get("anna").get("owner")
users.set_admin("anna", False); assert users.get("anna")["permissions"]["user_management"] == "none"
users.set_permissions("anna", {**PRESETS["admin"]}); assert users.get("anna")["permissions"]["user_management"] == "read"     # Schreiben in der Tabelle macht nicht zum Admin
users.set_admin("anna", True)

# ---- Ablauf nur fuer Nicht-Administratoren
try:
    users.set_expires("anna", "2099-01-01"); assert False   # anna ist jetzt Administrator
except UserError: pass
users.set_expires("custom", "2099-01-01")
assert users.get("custom")["expires"] == "2099-01-01"
users.set_expires("custom", None)

print("PERMS OK", root.split("/")[-1])

# ---- Templates: Navigation und Sperren richten sich nach den einzelnen Bereichen
client2 = webapp.app.test_client()
client2.post("/login", data={"username": "gast", "password": "demopass1"})
h = client2.get("/rules").get_data(as_text=True)
assert "Testbereich" in h and "ro-locked" not in h, "demo (rules=read) soll frei basteln, nur nicht speichern koennen"
h = client2.get("/automation").get_data(as_text=True)
assert "Testbereich" in h and "ro-locked" not in h
h = client2.get("/").get_data(as_text=True)
assert 'href="/admin"' in h                        # demo hat ueberall settings read -> Link da
assert "(nur Ansicht)" in h                          # dashboard=read -> Titel-Hinweis
client2.post("/logout")

client2.post("/login", data={"username": "custom", "password": "custompass1"})
r = client2.get("/")
assert r.status_code == 403, "custom hat dashboard=none - darf die Startseite nicht sehen"
h = client2.get("/admin").get_data(as_text=True)                        # hat settings_tarif/vrm -> darf rein
import re as _re
nav = _re.search(r"<nav>.*?</nav>", h, _re.S).group(0)
assert 'href="/rules"' not in nav and 'href="/automation"' not in nav and 'href="/"' not in nav, nav
assert 'href="/admin"' in nav
client2.post("/logout")

print("TEMPLATES OK", root.split("/")[-1])

# ---- Speichern-Leiste verschwindet, wenn nirgends Schreibrecht auf Einstellungen besteht
h = client2.get("/admin").get_data(as_text=True) if False else None   # (client2 ist noch als custom eingeloggt gewesen -> neu)
c3 = webapp.app.test_client()
c3.post("/login", data={"username": "gast", "password": "demopass1"})
h = c3.get("/admin").get_data(as_text=True)
assert 'id="btn-save"' not in h, "demo hat nirgends Schreibrecht - Speichern-Leiste haette fehlen muessen"
assert '"account": "none"' in h, "demo (account=none) - die Karte wird clientseitig ausgeblendet, das Recht muss aber none sein"
r = c3.post("/api/account", json={"current": "demopass1", "username": "neuername"})
assert r.status_code == 403, r.status_code
c3.post("/logout")

# anna (Preset "user") darf ihr eigenes Konto aendern (account=write) und hat Dashboard-Schreibrecht -> Speichern-Leiste da
c3.post("/login", data={"username": "anna", "password": "userpass1"})
h = c3.get("/admin").get_data(as_text=True)
assert '"account": "write"' in h
r = c3.post("/api/account", json={"current": "userpass1", "new": "userpass1neu", "new2": "userpass1neu"})
assert r.status_code == 200, r.get_json()
users.update_password("anna", "userpass1")   # fuer die spaeteren Logins wieder das alte Passwort setzen
c3.post("/logout")

# ---- IP-Adressen: Cerbo-IP nur mit settings_anlage=write im Klartext
cfg["cerbo_host"] = "192.168.50.241"
c3.post("/login", data={"username": "gast", "password": "demopass1"})   # demo: settings_anlage=read
j = c3.get("/api/config").get_json()
assert j["cerbo_host"] == "" and j["cerbo_host_set"] is True, j
c3.post("/logout")
c3.post("/login", data={"username": "anna", "password": "userpass1"})   # anna wurde oben zum Volladmin gemacht
j = c3.get("/api/config").get_json()
assert j["cerbo_host"] == "192.168.50.241"
c3.post("/logout")

print("SAVEBAR/ACCOUNT/IP OK", root.split("/")[-1])

# ---- Geraete-IP nur mit settings_geraete=write im Klartext (auch im Dashboard/Automatik)
import shelly as _shelly
_orig_list = _shelly.list_with_status
_shelly.list_with_status = lambda only_shown=False, ids=None, live=True, max_age=None: [{"id": "dev1", "name": "Pumpe", "ip": "192.168.50.55", "auto": False}]
c3.post("/login", data={"username": "gast", "password": "demopass1"})   # demo: settings_geraete=read
j = c3.get("/api/shelly").get_json()
assert j[0]["ip"] == "•.•.•.•" and j[0]["ip_hidden"] is True, j
c3.post("/logout")
c3.post("/login", data={"username": "anna", "password": "userpass1"})   # anna wurde oben zum Volladmin gemacht
j = c3.get("/api/shelly").get_json()
assert j[0]["ip"] == "192.168.50.55"
c3.post("/logout")
_shelly.list_with_status = _orig_list

# ---- Regeln/Automatik: mit "read" frei basteln koennen, aber Speichern bleibt serverseitig gesperrt
c3.post("/login", data={"username": "gast", "password": "demopass1"})   # demo: rules=read, automation=read
h = c3.get("/rules").get_data(as_text=True)
assert "Testbereich" in h and "ro-locked" not in h, "Regel-Baukasten soll frei bedienbar (nicht CSS-gesperrt) sein"
h = c3.get("/automation").get_data(as_text=True)
assert "Testbereich" in h and "ro-locked" not in h
r = c3.post("/api/automation", json={"config": {}, "rules": []})
assert r.status_code == 403, r.status_code       # Speichern bleibt serverseitig verboten, egal was die UI anzeigt
c3.post("/logout")

print("IP/SANDBOX OK", root.split("/")[-1])

# ---- Dashboard-Kacheln lassen sich pro Benutzer zusaetzlich einschraenken
from auth import PRESETS as _P
users.create("kiosk", "kioskpass1", permissions=_P["user"], dashboard_tiles=["show_live_values", "show_energy_chart"])
c4 = webapp.app.test_client()
c4.post("/login", data={"username": "kiosk", "password": "kioskpass1"})
ui = c4.get("/api/status").get_json()["ui"]
assert ui["show_live_values"] is True and ui["show_energy_chart"] is True
assert ui["show_week_overview"] is False and ui["show_tibber_card"] is False, ui
c4.post("/logout")
# admin (anna) sieht ungefiltert alles, was global an ist
c4.post("/login", data={"username": "anna", "password": "userpass1"})
ui = c4.get("/api/status").get_json()["ui"]
assert ui["show_week_overview"] is True
c4.post("/logout")
# leere Liste normalisiert sich zu None (keine Einschraenkung), "alle angehakt" ebenso
assert users.get("kiosk")["dashboard_tiles"] == ["show_live_values", "show_energy_chart"]
users.set_dashboard_tiles("kiosk", None)
assert users.get("kiosk")["dashboard_tiles"] is None
from auth import DASHBOARD_TILE_KEYS
users.set_dashboard_tiles("kiosk", list(DASHBOARD_TILE_KEYS))   # alles angehakt -> keine Einschraenkung
assert users.get("kiosk")["dashboard_tiles"] is None

print("TILES OK", root.split("/")[-1])

# ---- Kennungen (Chat-ID/Access-ID/Installations-ID) nur mit Schreibrecht im Klartext
import notify as _notify, tuya as _tuya, vrm as _vrm
_notify.credentials_public = lambda: {"configured": True, "has_token": True, "chat_id": "330322606"}
_notify.settings_public = lambda cfg: {}
_tuya.credentials_public = lambda: {"configured": True, "region": "eu", "api_key": "jquqy38hqfn9ayuc3a4j", "networks": "192.168.50.0/24", "regions": {"eu": "Europa"}}
_vrm.credentials_public = lambda: {"configured": True, "installation_id": "844297"}

c5 = webapp.app.test_client()
c5.post("/login", data={"username": "gast", "password": "demopass1"})   # demo: read auf alle settings
j = c5.get("/api/notify").get_json()
assert j["chat_id"] == "" and j["chat_id_set"] is True, j
j = c5.get("/api/tuya").get_json()
assert j["api_key"] == "" and j["api_key_set"] is True and j["networks"] == "" and j["networks_set"] is True, j
j = c5.get("/api/vrm").get_json()
assert j["installation_id"] == "" and j["installation_id_set"] is True, j
c5.post("/logout")

c5.post("/login", data={"username": "anna", "password": "userpass1"})   # anna ist Volladmin (siehe oben)
j = c5.get("/api/notify").get_json()
assert j["chat_id"] == "330322606"
j = c5.get("/api/tuya").get_json()
assert j["api_key"] == "jquqy38hqfn9ayuc3a4j"
j = c5.get("/api/vrm").get_json()
assert j["installation_id"] == "844297"
c5.post("/logout")

print("IDS MASKED OK", root.split("/")[-1])

# ---- Abmelden funktioniert fuer JEDES Konto, auch mit ganz wenigen Rechten
c6 = webapp.app.test_client()
c6.post("/login", data={"username": "gast", "password": "demopass1"})
r = c6.post("/logout")
assert r.status_code in (302, 303), r.status_code
r2 = c6.get("/api/status")
assert r2.status_code == 401, "nach /logout sollte die Session weg sein"
print("LOGOUT OK", root.split("/")[-1])

# ---- "Meine Ansicht": jedes Konto (auch read-only) darf sich selbst einschraenken, aber nie
# ueber die Admin-Obergrenze (dashboard_tiles) hinaus wieder freischalten
from auth import PRESETS as _P2
users.create("ina", "inapass123", permissions={**_P2["user"], "settings_anzeige": "read"}, dashboard_tiles=["show_live_values", "show_energy_chart", "show_week_overview"])
c7 = webapp.app.test_client()
c7.post("/login", data={"username": "ina", "password": "inapass123"})
j = c7.get("/api/my-tiles").get_json()
assert j["admin_tiles"] == ["show_live_values", "show_energy_chart", "show_week_overview"]
assert j["my_tiles"] is None
r = c7.post("/api/my-tiles", json={"my_tiles": ["show_live_values"]})
assert r.status_code == 200, r.get_json()
ui = c7.get("/api/status").get_json()["ui"]
assert ui["show_live_values"] is True and ui["show_energy_chart"] is False, ui   # von ihr selbst ausgeblendet
# Versuch, sich selbst mehr freizuschalten als der Admin erlaubt (z.B. show_tibber_card) - bleibt wirkungslos,
# weil api_status beide Einschraenkungen (Admin UND eigene) unabhaengig anwendet.
r = c7.post("/api/my-tiles", json={"my_tiles": ["show_live_values", "show_tibber_card"]})
assert r.status_code == 200
ui = c7.get("/api/status").get_json()["ui"]
assert ui["show_tibber_card"] is False, "Admin-Obergrenze haette nicht umgangen werden duerfen"
c7.post("/logout")

# Konto ohne "Einstellungen: Dashboard" (Kein) darf "Meine Ansicht" NICHT aendern (die Seite blendet den Bereich aus), laden/ansehen geht weiter
users.create("mathias", "mathiaspass1", permissions=_P2["user"])
c8 = webapp.app.test_client(); c8.post("/login", data={"username": "mathias", "password": "mathiaspass1"})
assert c8.get("/api/my-tiles").status_code == 200
r = c8.post("/api/my-tiles", json={"my_tiles": ["show_live_values"]}); assert r.status_code == 403, r.status_code
c8.post("/logout")

# demo (nur dashboard=read) darf sich trotzdem seine eigene Ansicht einstellen - braucht kein Schreibrecht
c7.post("/login", data={"username": "gast", "password": "demopass1"})
r = c7.post("/api/my-tiles", json={"my_tiles": ["show_live_values"]})
assert r.status_code == 200, r.get_json()
c7.post("/logout")

# eigene Reihenfolge ("Meine Ansicht") - wirkt sich auf api/status aus, unabhaengig von der globalen
c7.post("/login", data={"username": "ina", "password": "inapass123"})
custom_order = ["show_week_overview", "show_energy_chart", "show_live_values"] + [
    k for k in auth.DASHBOARD_TILE_KEYS if k not in ("show_week_overview", "show_energy_chart", "show_live_values")]
r = c7.post("/api/my-tiles", json={"my_order": custom_order})
assert r.status_code == 200, r.get_json()
ui = c7.get("/api/status").get_json()["ui"]
assert ui["tile_order"][:3] == ["show_week_overview", "show_energy_chart", "show_live_values"], ui["tile_order"]
j = c7.get("/api/my-tiles").get_json()
assert j["my_order"][:3] == ["show_week_overview", "show_energy_chart", "show_live_values"]
c7.post("/logout")

# jeder darf /admin oeffnen (Konto & Zugang + Meine Ansicht sind immer da), egal wie wenig Rechte
c7.post("/login", data={"username": "ina", "password": "inapass123"})
h = c7.get("/admin").get_data(as_text=True)
assert r.status_code != 500
assert 'id="my-tile-toggles"' in h and 'id="acc-username"' in h
c7.post("/logout")

print("MY VIEW OK", root.split("/")[-1])
