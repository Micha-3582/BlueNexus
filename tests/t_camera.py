"""Kameras (Reolink): Hinzufuegen mit Verbindungstest, Token-Anmeldung, Standbild, MJPEG-Live (ffmpeg), Rechte, Sichtbarkeit, Admin-only."""
import sys, os, json, threading, subprocess, shutil, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, auth
from auth import UserStore

camera.CAMERAS_PATH = os.path.join(tmp, "cameras.json")
FF = shutil.which("ffmpeg"); assert FF, "ffmpeg fuer den Test noetig"
JPEG = subprocess.run([FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x48", "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"], capture_output=True).stdout
assert JPEG[:2] == b"\xff\xd8"

MODE = {"token_only": False, "no_login": False, "devinfo_502": False}
CALLS = []


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, obj):
        b = json.dumps(obj).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def _auth_ok(self, q):
        if q.get("token", [""])[0] == "TOK123":
            return True
        return (not MODE["token_only"]) and q.get("user", [""])[0] == "admin" and q.get("password", [""])[0] == "geheim"

    def do_POST(self):
        u = urlparse(self.path); q = parse_qs(u.query); n = int(self.headers.get("Content-Length") or 0); body = json.loads(self.rfile.read(n) or b"[]")
        cmd = q.get("cmd", [""])[0]; CALLS.append(cmd)
        if cmd == "Login":
            if MODE["no_login"]:
                return self._json([{"cmd": "Login", "code": 1, "error": {"rspCode": -502, "detail": "Illegal param"}}])
            ud = body[0]["param"]["User"]
            if ud["userName"] == "admin" and ud["password"] == "geheim":
                return self._json([{"cmd": "Login", "code": 0, "value": {"Token": {"name": "TOK123", "leaseTime": 3600}}}])
            return self._json([{"cmd": "Login", "code": 1, "error": {"rspCode": -6, "detail": "login failed"}}])
        if not self._auth_ok(q):
            return self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -6, "detail": "login failed"}}])
        if cmd == "GetDevInfo" and MODE["devinfo_502"]:
            return self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -502, "detail": "Illegal param"}}])
        if cmd == "GetDevInfo":
            return self._json([{"cmd": cmd, "code": 0, "value": {"DevInfo": {"name": "Hofkamera", "model": "RLC-810A", "firmVer": "v3"}}}])
        self._json([{"cmd": cmd, "code": 1, "error": {"rspCode": -9}}])

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query); CALLS.append("GET:" + q.get("cmd", [""])[0])
        if q.get("cmd", [""])[0] == "Snap" and self._auth_ok(q):
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self.send_header("Content-Length", str(len(JPEG))); self.end_headers(); self.wfile.write(JPEG); return
        self._json([{"cmd": "Snap", "code": 1, "error": {"rspCode": -6}}])


srv = ThreadingHTTPServer(("127.0.0.1", 0), H); PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

webapp.users = UserStore(os.path.join(tmp, "users_cam.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "kameras": "read", "settings_geraete": "write"})
webapp.users.create("max", "maxpass123", {"dashboard": "write"})
webapp.users.create("demo", "demopass123", auth.PRESETS["demo"])
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I, M, D = login("admin", "adminpass1"), login("ina", "inapass123"), login("max", "maxpass123"), login("demo", "demopass123")

# --- Rechte-Bereich
assert "kameras" in auth.AREA_IDS and auth.PRESETS["demo"]["kameras"] == "none" and auth.PRESETS["admin"]["kameras"] == "write" and auth.PRESETS["user"]["kameras"] == "none"
assert any(g[0] == "kameras" for g in auth.AREA_GROUPS)
assert A.get("/kameras").status_code == 200 and I.get("/kameras").status_code == 200
assert M.get("/kameras").status_code == 302 and D.get("/kameras").status_code == 302                        # ohne Recht -> umgeleitet
assert M.get("/api/cameras").status_code == 403
print("Rechte OK")

# --- Hinzufuegen: Pruefung der Verbindung
assert A.post("/api/cameras", json={}).status_code == 400
assert A.post("/api/cameras", json={"host": "http://1.2.3.4/x"}).status_code == 400
r = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "falsch"}); assert r.status_code == 400 and "Anmeldung" in r.get_json()["error"], r.get_json()
r = A.post("/api/cameras", json={"host": "127.0.0.1", "port": 1, "user": "admin", "password": "geheim"}); assert r.status_code == 400 and "nicht erreichbar" in r.get_json()["error"], r.get_json()
for c in (I, M, D):
    assert c.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim"}).status_code in (403, 302)
r = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": ""}); assert r.status_code == 201, r.get_json()
cam = r.get_json(); cid = cam["id"]
assert cam["name"] == "Hofkamera" and cam["model"] == "RLC-810A" and cam["users"] == [] and "password" not in cam and cam["password_set"] is True
raw = camera.load()[0]; assert raw["password"] == "geheim" and raw["users"] == []
# Kamera ohne Token-Anmeldung (Login liefert -502): es geht mit Benutzer/Passwort in der Adresse weiter
MODE["no_login"] = True; camera._tokens.clear()
r = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "OhneLogin"}); assert r.status_code == 201, r.get_json()
assert A.delete("/api/cameras/" + r.get_json()["id"]).status_code == 200
MODE["no_login"] = False
# Kamera meldet beim Abfragen -502: Meldung nennt Code und Detail der Kamera
MODE["devinfo_502"] = True; camera._tokens.clear()
r = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "x"}); assert r.status_code == 400 and "-502" in r.get_json()["error"] and "Illegal param" in r.get_json()["error"], r.get_json()
MODE["devinfo_502"] = False; camera._tokens.clear()
print("Hinzufuegen OK")

# --- Liste: Zugangsdaten nie nach aussen; IP/Benutzer nur Admin; neue Kamera nur fuer Admin sichtbar
lst = A.get("/api/cameras").get_json(); assert len(lst["cameras"]) == 1 and lst["cameras"][0]["host"] == "127.0.0.1" and '"password"' not in json.dumps(lst) and lst["live"] is True
assert I.get("/api/cameras").get_json()["cameras"] == []                                    # neu: nur Admin
assert I.get(f"/api/cameras/{cid}/snapshot").status_code == 404 and I.get(f"/api/cameras/{cid}/stream").status_code == 404
assert A.patch(f"/api/cameras/{cid}", json={"users": ["ina"]}).status_code == 200
li = I.get("/api/cameras").get_json()["cameras"]; assert len(li) == 1 and "host" not in li[0] and "user" not in li[0] and "users" not in li[0] and "geheim" not in json.dumps(li)
assert I.patch(f"/api/cameras/{cid}", json={"name": "x"}).status_code == 403 and I.delete(f"/api/cameras/{cid}").status_code == 403
print("Liste/Sichtbarkeit OK")

# --- Standbild (Cache, Token-Anmeldung)
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data == JPEG and "no-store" in r.headers["Cache-Control"]
n = CALLS.count("GET:Snap"); I.get(f"/api/cameras/{cid}/snapshot"); assert CALLS.count("GET:Snap") == n                          # zwischengespeichert
MODE["token_only"] = True; camera._snap_cache.clear(); camera._tokens.clear()
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 200 and r.data == JPEG and "Login" in CALLS                  # Kamera lehnt Benutzer/Passwort ab -> Token
MODE["token_only"] = False
# Kamera offline -> 503 mit Meldung, kein Absturz
c0 = camera.load(); c0[0]["port"] = 1; camera._save(c0); camera._snap_cache.clear(); camera._tokens.clear()
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 503 and "nicht erreichbar" in r.get_json()["error"]
c0[0]["port"] = PORT; camera._save(c0); camera._snap_cache.clear()
print("Standbild OK")

# --- Live (ffmpeg -> MJPEG): hier mit Testbild statt RTSP
camera.ffmpeg_cmd = lambda item, quality=None: [FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1", "-f", "mpjpeg", "pipe:1"]
r = I.get(f"/api/cameras/{cid}/stream", buffered=True)
assert r.status_code == 200 and r.mimetype == "multipart/x-mixed-replace" and "boundary=ffmpeg" in r.headers["Content-Type"], r.headers
assert b"--ffmpeg" in r.data and b"\xff\xd8" in r.data and b"Content-type: image/jpeg" in r.data.replace(b"Content-Type", b"Content-type") and len(re.findall(rb"--ffmpeg", r.data)) >= 5, len(r.data)
assert camera._slots._value == camera.MAX_STREAMS                                         # Platz wieder frei
# Qualitaet: klar = Hauptstrom, fluessig = Teilstrom, Unbekanntes -> klar
it = camera.get(cid)
assert camera.rtsp_url(it, "klar").endswith("/Preview_01_main") and camera.rtsp_url(it, "fluessig").endswith("/Preview_01_sub") and camera.rtsp_url(it).endswith("/Preview_01_main")
assert camera.norm_quality("quatsch") == "klar" and camera.norm_quality("fluessig") == "fluessig"
real_cmd = camera.ffmpeg_cmd
import importlib; cmd_real = importlib.import_module("camera").__dict__["ffmpeg_cmd"]
seen = []
camera.ffmpeg_cmd = lambda item, quality=None: (seen.append(quality), [FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1", "-f", "mpjpeg", "pipe:1"])[1]
I.get(f"/api/cameras/{cid}/stream?q=fluessig", buffered=True); I.get(f"/api/cameras/{cid}/stream", buffered=True); I.get(f"/api/cameras/{cid}/stream?q=x", buffered=True)
assert seen == ["fluessig", "klar", "klar"], seen
print("Live OK")

# Platzlimit + sauberes Aufraeumen (auch ohne je zu lesen)
camera._slots = threading.BoundedSemaphore(2)
camera.ffmpeg_cmd = lambda item, quality=None: [FF, "-loglevel", "error", "-re", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "30", "-f", "mpjpeg", "pipe:1"]
s1 = camera.stream(camera.get(cid)); s2 = camera.stream(camera.get(cid))
r = I.get(f"/api/cameras/{cid}/stream"); assert r.status_code == 429, r.status_code
procs = [s1.proc, s2.proc]; s1.close(); s2.close(); s1.close()                                       # mehrfaches close ist harmlos
assert all(p.poll() is not None for p in procs) and camera._slots._value == 2
# ohne ffmpeg: 501 mit Hinweis
real = camera.ffmpeg_path; camera.ffmpeg_path = lambda: None
r = I.get(f"/api/cameras/{cid}/stream"); assert r.status_code == 501 and "ffmpeg" in r.get_json()["error"]
assert A.get("/api/cameras").get_json()["live"] is False
camera.ffmpeg_path = real
print("Limit/ohne ffmpeg OK")

# --- Start-Ueberwachung: kein Bild -> neu versuchen; haengende Kamera -> Fehler statt endlos zu warten; freundliches Beenden meldet die Kamera ab
PY = sys.executable
camera._slots = threading.BoundedSemaphore(3); camera.START_WAIT_S = 1.5; camera.START_TRIES = 2
calls = []
def flaky(item, quality=None):
    calls.append(1)
    if len(calls) == 1:
        return [PY, "-c", "import sys; sys.exit(1)"]                                   # 1. Versuch: ffmpeg endet ohne Bild (Kamera lehnt Sitzung ab)
    return [FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-t", "1", "-f", "mpjpeg", "pipe:1"]
camera.ffmpeg_cmd = flaky
r = I.get(f"/api/cameras/{cid}/stream", buffered=True); assert r.status_code == 200 and b"\xff\xd8" in r.data and len(calls) == 2, (r.status_code, len(calls))
assert camera._slots._value == 3
camera.ffmpeg_cmd = lambda item, quality=None: [PY, "-c", "import time; time.sleep(30)"]                  # Kamera liefert nie ein Bild
t0 = time.time(); r = I.get(f"/api/cameras/{cid}/stream"); dt = time.time() - t0
assert r.status_code == 503 and "kein Live-Bild" in r.get_json()["error"] and 2.5 < dt < 12, (r.status_code, dt)
assert camera._slots._value == 3                                                                            # Platz frei, Prozesse beendet
marker = os.path.join(tmp, "bye.txt")
camera.ffmpeg_cmd = lambda item, quality=None: [PY, "-c", f"import sys; sys.stdout.buffer.write(b'x'*100); sys.stdout.flush(); sys.stdin.buffer.read(1); open({marker!r}, 'w').write('q')"]
st = camera.stream(camera.get(cid)); assert camera._slots._value == 2
st.close()
for _ in range(30):
    if os.path.exists(marker): break
    time.sleep(0.1)
assert os.path.exists(marker) and open(marker).read() == "q"                                                # ffmpeg hat 'q' bekommen (freundlich, nicht per kill)
assert camera._slots._value == 3
print("Start-Ueberwachung OK")

# --- Aendern/Entfernen nur Admin; Zugang aendern
assert A.patch(f"/api/cameras/{cid}", json={"name": "Hof"}).status_code == 200 and A.patch(f"/api/cameras/{cid}", json={"port": "abc"}).status_code == 400
assert A.patch(f"/api/cameras/{cid}", json={"password": "neu123"}).status_code == 200 and camera.load()[0]["password"] == "neu123"
assert A.patch(f"/api/cameras/{cid}", json={"password": ""}).status_code == 200 and camera.load()[0]["password"] == "neu123"          # leer = unveraendert
assert [x["name"] for x in A.get("/api/cameras").get_json()["cameras"]] == ["Hof"]
assert A.patch(f"/api/cameras/gibts-nicht", json={"name": "x"}).status_code == 404
# Benutzer geloescht/umbenannt -> Liste zieht mit
with webapp.app.test_request_context():
    webapp._vis_users_changed("ina", "inas")
assert A.get("/api/cameras").get_json()["cameras"][0]["users"] == ["inas"]
assert A.delete(f"/api/cameras/{cid}").status_code == 200 and A.get("/api/cameras").get_json()["cameras"] == []
print("Admin OK")

# --- Eigene Reihenfolge (Lange druecken & verschieben): pro Konto, auch mit nur Leserecht; Neues kommt hinten dazu
cA = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "Eins"}).get_json()["id"]
cB = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "Zwei"}).get_json()["id"]
cC = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "Drei"}).get_json()["id"]
for i in (cA, cB, cC): assert A.patch(f"/api/cameras/{i}", json={"users": ["inas"]}).status_code == 200
webapp.users.rename("inas", "ina") if False else None
for i in (cA, cB, cC): assert A.patch(f"/api/cameras/{i}", json={"users": ["ina"]}).status_code == 200
def names_of(c): return [x["name"] for x in c.get("/api/cameras").get_json()["cameras"]]
assert names_of(I) == ["Eins", "Zwei", "Drei"] and names_of(A) == ["Eins", "Zwei", "Drei"]
assert I.post("/api/cameras/my-order", json={"ids": [cC, cA, "gibts-nicht", cC]}).status_code == 200                # Fremdes/Doppeltes stoert nicht
assert names_of(I) == ["Drei", "Eins", "Zwei"] and names_of(A) == ["Eins", "Zwei", "Drei"]                         # nur fuer ina; der Admin hat seine eigene
assert A.post("/api/cameras/my-order", json={"ids": [cB]}).status_code == 200 and names_of(A) == ["Zwei", "Eins", "Drei"] and names_of(I) == ["Drei", "Eins", "Zwei"]
cD = A.post("/api/cameras", json={"host": "127.0.0.1", "port": PORT, "user": "admin", "password": "geheim", "name": "Vier"}).get_json()["id"]
A.patch(f"/api/cameras/{cD}", json={"users": ["ina"]}); assert names_of(I) == ["Drei", "Eins", "Zwei", "Vier"]       # Neue Kamera hinten
assert I.post("/api/cameras/my-order", json={"ids": "x"}).status_code == 400 and I.post("/api/cameras/my-order", json={}).status_code == 400
assert M.post("/api/cameras/my-order", json={"ids": [cA]}).status_code == 403 and D.post("/api/cameras/my-order", json={"ids": [cA]}).status_code == 403   # ohne Recht Kameras
print("Reihenfolge OK")

# --- Seite rendert (Jinja) und Menue
h = A.get("/kameras").get_data(as_text=True)
assert 'id="camgrid"' in h and "Kamera hinzufügen" in h and '>Kameras</a>' in h
assert '>Kameras</a>' not in M.get("/").get_data(as_text=True) and '>Kameras</a>' in I.get("/").get_data(as_text=True)
print("CAMERA OK")
