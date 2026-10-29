"""Neues Menue: Dashboard | Smart Home | Einstellungen; /smarthome mit Reitern, Automatik/Regeln mit Unter-Menue, Rechte."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore

webapp.users = UserStore(os.path.join(tmp, "users_menu.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("nurdash", "dashpass123", {"dashboard": "write"})
webapp.users.create("nurregeln", "regelnpass1", {"dashboard": "read", "rules": "write"})
webapp.users.create("geraete", "geraetepass1", {"dashboard": "read", "settings_geraete": "write"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A = login("admin", "adminpass1")

def nav(html):
    m = re.search(r"<header>.*?</header>", html, re.S).group(0)
    return re.findall(r'<a href="([^"]+)"( class="active")?[^>]*>(?:<span[^>]*>)?([^<]+)', m)

# Admin: drei Menuepunkte, aktiv je nach Seite
for path, active in (("/", "Dashboard"), ("/smarthome", "Smart Home"), ("/automation", "Einstellungen"), ("/rules", "Smart Home"), ("/admin", "Einstellungen")):
    r = A.get(path); assert r.status_code == 200, (path, r.status_code)
    n = nav(r.get_data(as_text=True))
    assert [x[2] for x in n] == ["Dashboard", "Smart Home", "Kameras", "Einstellungen"], n
    assert [x[2] for x in n if x[1]] == [active], (path, n)
print("Hauptmenue OK")

# Unter-Menue
h = A.get("/smarthome").get_data(as_text=True)
sub = re.search(r'<nav class="shnav".*?</nav>', h, re.S).group(0)
labels = re.findall(r'title="([^"]+)"', sub)
assert labels == ["Aktoren", "Sensoren", "Thermostate", "Sicherheit", "Regeln", "Geräte suchen", "Wake-on-LAN", "Sonstiges"], labels
assert "window.PAGE_MODE = \"smarthome\"" in h
t = A.get("/rules").get_data(as_text=True)
s2 = re.search(r'<nav class="shnav".*?</nav>', t, re.S).group(0)
assert re.findall(r'class="active" title="([^"]+)"', s2) == ["Regeln"]
t = A.get("/automation").get_data(as_text=True)
assert 'class="shnav"' not in t
s3 = re.search(r'<nav class="setnav".*?</nav>', t, re.S).group(0)
assert [__import__('html').unescape(x) for x in re.findall(r'<a href="[^"]+"[^>]*>([^<]+)</a>', s3)] == ["Anlage", "Tarif & Laden", "VRM", "Automatik", "Wetter", "Meldungen", "Dashboard", "System", "Konto & Benutzer"], s3
assert re.findall(r'class="active">([^<]+)</a>', s3) == ["Automatik"]
adm = A.get("/admin").get_data(as_text=True)
assert "href: '/automation'" in adm
print("Unter-Menue OK")

# Einstellungen: PAGE_MODE admin, kein Smart-Home-Reiter mehr
a = A.get("/admin").get_data(as_text=True)
assert 'window.PAGE_MODE = "admin"' in a and 'class="tabbar" id="tabbar"' in a and 'class="shnav"' not in a
assert "id: 'geraete'" not in a
# alle Karten haben einen gueltigen Reiter
tabs = set(re.findall(r'data-tab="([a-z*_]+)"', a))
assert {"aktoren", "sensoren", "thermostate", "sicherheit", "suchen", "wol", "sonstiges"} <= tabs, tabs
assert "geraete" not in tabs, tabs
for need in ("shelly-devs", "virtual-list", "hm-sensors", "hm-setpoints", "hm-locks", "wol-list", "shelly-found", "shelly-msg", "hm-push", "hm-push-port", "fam-hint"):
    assert f'id="{need}"' in a, need
print("Karten OK")

# Rechte
def navlabels(c, path):
    r = c.get(path); return r.status_code, ([x[2] for x in nav(r.get_data(as_text=True))] if r.status_code == 200 else None)
D = login("nurdash", "dashpass123")
assert navlabels(D, "/")[1] == ["Dashboard"]                         # keine Einstellungen -> kein Menuepunkt
assert D.get("/smarthome").status_code == 302
R = login("nurregeln", "regelnpass1")
st, nv = navlabels(R, "/rules"); assert st == 200 and nv == ["Dashboard", "Smart Home"]
href = [x[0] for x in nav(R.get("/rules").get_data(as_text=True)) if x[2] == "Smart Home"][0]; assert href == "/rules", href
sub = re.search(r'<nav class="shnav".*?</nav>', R.get("/rules").get_data(as_text=True), re.S).group(0)
assert re.findall(r'title="([^"]+)"', sub) == ["Regeln"], sub
assert R.get("/smarthome").status_code == 302
webapp.users.create("nurauto", "autopass123", {"dashboard": "read", "automation": "write"})
AU = login("nurauto", "autopass123")
assert navlabels(AU, "/automation")[1] == ["Dashboard", "Einstellungen"]
assert [x[0] for x in nav(AU.get("/automation").get_data(as_text=True)) if x[2] == "Einstellungen"] == ["/automation"]       # nur Automatik -> Link fuehrt dorthin
assert [x[2] for x in nav(AU.get("/automation").get_data(as_text=True)) if x[1]] == ["Einstellungen"]
s4 = re.search(r'<nav class="setnav".*?</nav>', AU.get("/automation").get_data(as_text=True), re.S).group(0)
assert [__import__('html').unescape(x) for x in re.findall(r'<a href="[^"]+"[^>]*>([^<]+)</a>', s4)] == ["Automatik"], s4
G = login("geraete", "geraetepass1")
st, nv = navlabels(G, "/smarthome"); assert st == 200
href = [x[0] for x in nav(G.get("/smarthome").get_data(as_text=True)) if x[2] == "Smart Home"][0]; assert href == "/smarthome"
sub = re.search(r'<nav class="shnav".*?</nav>', G.get("/smarthome").get_data(as_text=True), re.S).group(0)
assert re.findall(r'title="([^"]+)"', sub) == ["Aktoren", "Sensoren", "Thermostate", "Sicherheit", "Geräte suchen", "Wake-on-LAN", "Sonstiges"]
assert G.get("/rules").status_code == 302
print("Rechte OK")
print("MENUE OK")
