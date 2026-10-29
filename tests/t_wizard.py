"""Erstinstallation: frische App ohne Konto/Konfiguration -> Konto anlegen -> Module waehlen -> Einrichtungsassistent -> Dashboard."""
import sys, os, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
import camera, homematic

# ganz frischer Zustand: keine Konfiguration, keine Konten. Die Test-Hilfe ersetzt load_config/is_configured durch Attrappen -
# fuer diesen Test kommen die ECHTEN Funktionen aus einer sauberen Kopie von store.py zurueck (mit eigener Datei im Testordner).
import importlib.util
spec = importlib.util.spec_from_file_location("store_clean", os.path.join(sys.argv[1], "app", "store.py"))
clean = importlib.util.module_from_spec(spec); spec.loader.exec_module(clean)
clean.CONFIG_PATH = os.path.join(tmp, "config_fresh.json")
if os.path.exists(clean.CONFIG_PATH):
    os.remove(clean.CONFIG_PATH)
store.load_config, store.save_config, store.is_configured = clean.load_config, clean.save_config, clean.is_configured
webapp.users = UserStore(os.path.join(tmp, "users_fresh.json"))
webapp.opslog.log = lambda *a, **k: None
app = webapp.app
print("empty", webapp.users.is_empty(), "chosen", store.modules_chosen(), "configured", store.is_configured(), store.load_config().get("cerbo_host")); assert webapp.users.is_empty() and not store.modules_chosen() and not store.is_configured()
c = app.test_client()

# 1) Jede Seite fuehrt zuerst zur Kontoerstellung
r = c.get("/"); assert r.status_code == 302 and r.headers["Location"].endswith("/create-account"), r.headers.get("Location")
r = c.get("/setup"); assert r.status_code == 302 and "create-account" in r.headers["Location"]
r = c.get("/api/config"); assert r.status_code == 401 and r.get_json()["setup_required"] is True
assert c.get("/login").status_code == 302 and c.get("/login").headers["Location"].endswith("/create-account") and c.get("/create-account").status_code == 200
print("1) Umleitung zur Kontoerstellung OK")

# 2) Konto anlegen: Fehlerfaelle, dann Erfolg
def mk(u, p, p2=None):
    return c.post("/create-account", data={"firstname": "Max", "username": u, "password": p, "password2": p if p2 is None else p2})
assert mk("Admin", "langespasswort", "anderes").status_code == 400
assert "stimmen nicht" in mk("Admin", "langespasswort", "anderes").get_data(as_text=True)
assert mk("Admin", "kurz").status_code == 400 and "mindestens" in mk("Admin", "kurz").get_data(as_text=True)
assert mk("<b>x</b>", "langespasswort").status_code == 400
assert mk("", "langespasswort").status_code == 400
assert webapp.users.is_empty(), "bei Fehlern darf kein Konto entstehen"
r = mk("Max", "meinpasswort12")
assert r.status_code == 200 and "Wiederherstellungsschlüssel" in r.get_data(as_text=True) and 'href="/setup/modules"' in r.get_data(as_text=True), r.status_code      # erst der Schluessel, dann weiter zur Modulwahl
assert not webapp.users.is_empty()
assert c.get("/create-account").status_code == 302, "nach dem ersten Konto gesperrt"
assert app.test_client().post("/create-account", data={"firstname": "X", "username": "zweiter", "password": "langespasswort", "password2": "langespasswort"}).status_code == 302
assert len(webapp.users._users) == 1, "kein zweites Konto ueber die oeffentliche Seite"
print("2) Konto anlegen OK")

# 3) Modul-Auswahl
r = c.get("/setup/modules"); assert r.status_code == 200 and "Energie" in r.get_data(as_text=True) and "Smart Home" in r.get_data(as_text=True)
r = c.post("/setup/modules", data={}); assert r.status_code == 400 and "mindestens ein Modul" in r.get_data(as_text=True)
r = c.post("/setup/modules", data={"energy": "1", "smarthome": "1"})
assert r.status_code == 302 and r.headers["Location"].endswith("/setup"), r.headers.get("Location")
print("3) Module OK")

# 4) Einrichtungsassistent: Seite, Verbindungstest, Speichern, Dashboard
r = c.get("/setup"); html = r.get_data(as_text=True)
assert r.status_code == 200 and html.count('class="wiz-step') >= 7 and "Victron GX-Gerät" in html and 'id="btn-test"' in html
assert c.get("/", follow_redirects=False).headers["Location"].endswith("/setup"), "unvollstaendig: Dashboard fuehrt zum Assistenten"
r = c.post("/api/test-connection", json={"cerbo_host": "192.168.50.50", "cerbo_port": 502, "tariff_mode": "fixed", "fixed_price_ct": 32})
d = r.get_json(); assert d["cerbo"]["ok"] is True and d["tibber"]["ok"] is True, d
d = c.post("/api/test-connection", json={"cerbo_host": "192.168.50.50", "tariff_mode": "fixed", "fixed_price_ct": 0}).get_json(); assert d["tibber"]["ok"] is False
r = c.post("/api/config", json={"cerbo_host": "192.168.50.50", "cerbo_port": 502, "tariff_mode": "fixed", "fixed_price_ct": 0}); assert r.get_json()["configured"] is False
r = c.post("/api/config", json={"cerbo_host": "192.168.50.50", "cerbo_port": 502, "tariff_mode": "fixed", "fixed_price_ct": 32.5, "app_display_name": "Haus Meier"})
assert r.get_json()["configured"] is True and store.is_configured()
r = c.get("/"); assert r.status_code == 200 and "Haus Meier" in r.get_data(as_text=True)
print("4) Assistent OK")

# 5) alle Hauptseiten nach der Einrichtung erreichbar (keine Fehler 500)
for path in ("/", "/admin", "/smarthome", "/rules", "/automation", "/verlauf", "/kameras", "/report", "/solar-log", "/watchdog"):
    r = c.get(path); assert r.status_code in (200, 302), (path, r.status_code)
    if r.status_code == 302:
        assert not r.headers["Location"].endswith("/setup"), path
print("5) Seiten OK")

# 6) nur Smart Home / nur Kameras / nichts waehlbar
for mods, want_loc, label in (({"smarthome": "1"}, "/", "nur Smart Home"), ({"cameras": "1"}, "/", "nur Kameras"), ({"energy": "1", "cameras": "1"}, "/", "Energie + Kameras")):
    cfg0 = store.load_config(); cfg0.pop("device_families", None); cfg0.pop("modules", None); store.save_config(cfg0)
    r = c.post("/setup/modules", data=mods); assert r.status_code == 302 and r.headers["Location"].endswith(want_loc), (label, r.headers.get("Location"))
    assert c.get("/").status_code in (200, 302)
    for path in ("/admin", "/smarthome", "/rules", "/kameras"):
        assert c.get(path).status_code in (200, 302, 403), (label, path)
print("6) Modulvarianten OK")

# 7) frische Installation nur Smart Home: Seiten ohne Energie-Daten
cfg0 = store.load_config(); cfg0.pop("device_families", None); store.save_config(cfg0)
c.post("/setup/modules", data={"smarthome": "1"})
for path in ("/", "/smarthome", "/rules", "/admin"):
    r = c.get(path); assert r.status_code == 200, (path, r.status_code)
print("WIZARD OK")
