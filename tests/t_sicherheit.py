"""Korrekturen aus der Sicherheitsprüfung vom 29.10.2026 (1.27.3):
S-03 Kopfzeilen für die Besucher-Adresse nur von einem Proxy auf diesem Rechner, S-04 Geräteübersicht nur für Administratoren,
S-06 Update/Fernzugriff/Testmodus ändern nur Administratoren, S-07 Alexa ohne offene CORS-Kopfzeile, S-08 Kamera-Adresse auch beim Ändern geprüft,
dazu eine Liste: was unter "Benutzerverwaltung" hängt, ist gewollt (neue Einträge brauchen eine bewusste Entscheidung)."""
import sys, os, re, json, socket, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import alexa, camera
from auth import UserStore

alexa.ALEXA_PATH = os.path.join(tmp, "alexa.json")
camera.CAMERAS_PATH = os.path.join(tmp, "cams.json")
webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass123", {"dashboard": "read", "user_management": "read"})
webapp.users.create("sys", "syspass1234", {"dashboard": "read", "settings_system": "write"})


def login(u, p, **env):
    c = webapp.app.test_client(); c.environ_base.update(env)
    assert c.post("/login", data={"username": u, "password": p}).status_code == 302
    return c


A, L, S = login("admin", "adminpass1"), login("lese", "lesepass123"), login("sys", "syspass1234")

# ---- S-04: Geraeteuebersicht nur fuer Administratoren (auch nicht mit "Benutzerverwaltung: Lesen")
assert A.get("/api/inventory").status_code == 200
assert L.get("/api/inventory").status_code == 403 and "devices" not in (L.get("/api/inventory").get_json() or {})
assert 'id="inv-card"' in A.get("/admin").get_data(as_text=True) and 'id="inv-card"' not in L.get("/admin").get_data(as_text=True)
assert L.get("/api/users").status_code == 200                                       # die Benutzerliste ansehen bleibt wie gedacht moeglich

# ---- S-06: Update, Fernzugriff und Testmodus aendern nur Administratoren, ansehen bleibt
for method, url, body in (("post", "/api/update", {}), ("post", "/api/system/testmode", {"on": True}), ("post", "/api/tunnel/token", {"token": "x" * 40}),
                          ("delete", "/api/tunnel/token", None), ("post", "/api/tunnel/enable", {"enabled": True}), ("post", "/api/tunnel/install", {}),
                          ("post", "/api/tunnel/check", {}), ("post", "/api/tunnel/update", {})):
    r = getattr(S, method)(url, json=body) if body is not None else getattr(S, method)(url)
    assert r.status_code == 403, (method, url, r.status_code)
assert S.get("/api/tunnel").status_code == 200                                      # Status ansehen darf, wer System lesen darf
assert A.delete("/api/tunnel/token").status_code == 200                              # Administrator darf weiterhin

# ---- S-03: Kopfzeilen der Besucher-Adresse
def ip(remote, **headers):
    with webapp.app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": remote}):
        return webapp.client_ip()
assert ip("127.0.0.1") == "127.0.0.1" and ip("127.0.0.1", **{"CF-Connecting-IP": "203.0.113.7"}) == "203.0.113.7"            # Tunnel (cloudflared) auf diesem Rechner
assert ip("127.0.0.1", **{"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}) == "9.9.9.9"                                                  # der letzte Eintrag stammt von unserem Proxy
assert ip("::1", **{"CF-Connecting-IP": "203.0.113.7"}) == "203.0.113.7"
assert ip("192.168.50.77", **{"CF-Connecting-IP": "203.0.113.7"}) == "192.168.50.77"                                            # direkter Zugriff: Kopfzeile wird ignoriert
assert ip("192.168.50.77", **{"X-Forwarded-For": "8.8.8.8"}) == "192.168.50.77"
def fail_login(n, remote, header_ip=None):
    webapp._attempts.clear()
    c = webapp.app.test_client(); c.environ_base["REMOTE_ADDR"] = remote
    codes = []
    for i in range(n):
        h = {"CF-Connecting-IP": header_ip(i)} if header_ip else {}
        codes.append(c.post("/login", data={"username": "admin", "password": "falsch%d" % i}, headers=h).status_code)
    return codes
assert 429 in fail_login(14, "192.168.50.77", lambda i: "198.51.100.%d" % i), "direkter Zugriff mit wechselnder Kopfzeile muss gebremst werden"
assert 429 not in fail_login(14, "127.0.0.1", lambda i: "198.51.100.%d" % i), "ueber den Tunnel hat jeder Besucher seine eigene Bremse"
assert 429 in fail_login(14, "127.0.0.1", lambda i: "198.51.100.9"), "ein Besucher ueber den Tunnel wird gebremst"
webapp._attempts.clear()

# ---- S-07: Alexa-Bridge sendet keine offene CORS-Kopfzeile
def freeport(udp=False):
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM); s_.bind(("127.0.0.1", 0)); p_ = s_.getsockname()[1]; s_.close(); return p_
b = webapp.alexa_bridge; b.ssdp_port, b.multicast = freeport(True), False
free = freeport()
assert A.post("/api/alexa/settings", json={"port": free}).status_code == 200
A.post("/api/modules", json={"alexa": True}); assert b.running, b.error
resp = urllib.request.urlopen(f"http://127.0.0.1:{free}/description.xml", timeout=3)
assert resp.status == 200 and "URLBase" in resp.read().decode() and resp.headers.get("Access-Control-Allow-Origin") is None
A.post("/api/modules", json={"alexa": False})

# ---- S-08: Kamera-Adresse wird auch beim Aendern geprueft
camera._save([{"id": "cam-1", "kind": "reolink", "name": "Hof", "host": "192.168.50.60", "user": "a", "password": "b", "port": None, "channel": 0,
               "https": False, "show": True, "users": [], "model": "X"}])
for bad in ("a@b", "x/y", "h?x", "h#x", "a b", "http://192.168.50.60"):
    try:
        camera.update("cam-1", host=bad); raise SystemExit("Adresse %r haette abgelehnt werden muessen" % bad)
    except camera.CameraError:
        pass
assert camera.load()[0]["host"] == "192.168.50.60", "abgelehnte Adresse darf nichts veraendern"
assert camera.update("cam-1", host="192.168.50.61", name="Garten") and camera.load()[0]["host"] == "192.168.50.61"
r = A.patch("/api/cameras/cam-1", json={"host": "evil@host"}); assert r.status_code == 400, r.status_code

# ---- Endpunkte unter "Benutzerverwaltung": nur diese sind gewollt (ein neuer Eintrag muss hier bewusst ergaenzt werden)
src = open(os.path.join(os.path.dirname(webapp.__file__), "webapp.py"), encoding="utf-8-sig").read()
m = re.search(r"ENDPOINT_AREA = \{(.*?)\n\}", src, re.S)
um = sorted(k for k, v in re.findall(r'"([a-z0-9_]+)": "([a-z_]+)"', m.group(1)) if v == "user_management")
assert um == ["api_backup_export", "api_backup_import", "api_user_copy", "api_user_visible", "api_users", "api_users_item"], um
print("SICHERHEIT OK", sys.argv[1].split("/")[-1])
