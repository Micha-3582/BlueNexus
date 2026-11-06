"""Kamera des Bambu-Lab-Druckers (1.41.0): verschluesselter RTSP-Strom (rtsps, Port 322, Benutzer bblp, Zugangscode als Passwort).
Prueft: URL-Aufbau (rtsps nur bei Druckerkamera), Anlegen ueber den Drucker, Fehlermeldung mit Hinweis, doppelt anlegen, nur Administratoren."""
import sys, os, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, bambu, shelly
from auth import UserStore

camera.CAMERAS_PATH = os.path.join(tmp, "cameras.json")
FF = shutil.which("ffmpeg"); assert FF
PY = sys.executable
MODE = {"fail": ""}
CALLS = []


def fake_snapshot_cmd(item, path=None):
    CALLS.append((camera.rtsp_url(item, camera.DEFAULT_QUALITY, path), path))
    if MODE["fail"]:
        return [PY, "-c", f"import sys; sys.stderr.write({MODE['fail']!r}); sys.exit(1)"]
    return [FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x48", "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]


camera.snapshot_cmd = fake_snapshot_cmd

# ---------------------------------------------------------------- URL-Aufbau
plain = {"kind": "rtsp", "host": "192.168.1.5", "user": "u", "password": "p", "port": 554, "path_main": "/live"}
assert camera.rtsp_url(plain) == "rtsp://u:p@192.168.1.5:554/live"
assert camera.rtsp_url({**plain, "tls": True, "port": 322, "user": "bblp", "password": "1234:5678", "path_main": "/streaming/live/1"}) == "rtsps://bblp:1234%3A5678@192.168.1.5:322/streaming/live/1"

# ---------------------------------------------------------------- Drucker anlegen (ohne Verbindung: Eintrag direkt ins Register)
shelly.DEVICES_PATH = os.path.join(tmp, "shelly_devices.json")
shelly._save([{"id": "bambu-01p00a1", "kind": "bambu", "ip": "192.168.2.77", "serial": "01P00A1", "password": "87654321", "name": "Michas X1C", "icon": "🖨️", "switchable": False,
               "model": "Bambu Lab", "show": False, "auto": False, "users": []}])
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "kameras": "read"})


def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c


A, I = login("admin", "adminpass1"), login("ina", "inapass123")

# ---------------------------------------------------------------- Fehler: Drucker liefert keine Kamera
MODE["fail"] = "Connection refused"
r = A.post("/api/bambu/bambu-01p00a1/camera"); assert r.status_code == 400, r.get_json()
err = r.get_json()["error"]; assert "LAN-Modus Liveview" in err and "X1C" in err, err
assert camera.load() == []
assert CALLS and CALLS[0][0] == "rtsps://bblp:87654321@192.168.2.77:322/streaming/live/1", CALLS

# ---------------------------------------------------------------- Anlegen
MODE["fail"] = ""
r = A.post("/api/bambu/bambu-01p00a1/camera"); assert r.status_code == 201, r.get_json()
cam = r.get_json()
assert cam["kind"] == "rtsp" and cam["name"] == "Michas X1C – Kamera" and cam["host"] == "192.168.2.77" and cam["port"] == 322 and cam["user"] == "bblp" and "password" not in cam, cam
item = camera.load()[0]
assert item["tls"] is True and item["password"] == "87654321" and item["path_main"] == "/streaming/live/1", item
assert camera.rtsp_url(item).startswith("rtsps://bblp:87654321@192.168.2.77:322/")
assert camera.ffmpeg_cmd(item)[camera.ffmpeg_cmd(item).index("-i") + 1].startswith("rtsps://")

# ---------------------------------------------------------------- doppelt, falsches Geraet, Rechte
r = A.post("/api/bambu/bambu-01p00a1/camera"); assert r.status_code == 400 and "schon eine Kamera" in r.get_json()["error"]
assert A.post("/api/bambu/gibt-es-nicht/camera").status_code == 400
assert I.post("/api/bambu/bambu-01p00a1/camera").status_code in (401, 403), "Lese-Konto darf keine Kamera anlegen"
print("ok")
