"""RTSP-Kameras (z. B. Wansview): Pfad-Suche beim Hinzufuegen, Fehlerarten, Standbild per ffmpeg, URL-Aufbau, Live-Qualitaet, Bearbeiten."""
import sys, os, json, shutil, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, auth
from auth import UserStore

camera.CAMERAS_PATH = os.path.join(tmp, "cameras.json")
FF = shutil.which("ffmpeg"); assert FF
PY = sys.executable

def ok_cmd():
    return [FF, "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=64x48", "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]
def fail_cmd(text):
    return [PY, "-c", f"import sys; sys.stderr.write({text!r}); sys.exit(1)"]

MODE = {"good_path": "/live/ch0", "fail": "404 Not Found"}
CALLS = []
def fake_snapshot_cmd(item, path=None):
    p = path if path is not None else (item.get("path_main") or "")
    CALLS.append(p)
    if MODE["fail"] == "ok" and p == MODE["good_path"]:
        return ok_cmd()
    return fail_cmd(MODE["fail"] if MODE["fail"] != "ok" else "404 Not Found")
camera.snapshot_cmd = fake_snapshot_cmd

webapp.users = UserStore(os.path.join(tmp, "users_rtsp.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "kameras": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")
def add(**k):
    body = {"kind": "rtsp", "host": "192.168.50.80", "user": "admin", "password": "p@ss:wort/1", **k}
    return A.post("/api/cameras", json=body)

# --- Fehlerarten
MODE["fail"] = "rtsp://x: 401 Unauthorized"; r = add(); assert r.status_code == 400 and "Anmeldung" in r.get_json()["error"], r.get_json()
MODE["fail"] = "Connection refused"; r = add(); assert r.status_code == 400 and "nicht erreichbar" in r.get_json()["error"] and "RTSP" in r.get_json()["error"], r.get_json()
n = len(CALLS); MODE["fail"] = "404 Not Found"; r = add(); assert r.status_code == 400 and "Kein bekannter RTSP-Pfad" in r.get_json()["error"]; assert len(CALLS) - n == len(camera.CANDIDATE_PATHS)   # alle Kandidaten probiert
r = add(path_main="/falsch"); assert r.status_code == 400 and "Pfad stimmt nicht" in r.get_json()["error"], r.get_json()
r = add(path_main="/mit leerzeichen"); assert r.status_code == 400 and "Leerzeichen" in r.get_json()["error"]
assert camera.load() == []
print("Fehlerarten OK")

# --- Pfad-Suche: findet /live/ch0 selbst
MODE["fail"] = "ok"; MODE["good_path"] = "/live/ch0"; CALLS.clear()
r = add(name="Wohnzimmer"); assert r.status_code == 201, r.get_json()
cam = r.get_json(); cid = cam["id"]
assert cam["kind"] == "rtsp" and cam["model"] == "RTSP" and cam["path_main"] == "/live/ch0" and cam["name"] == "Wohnzimmer" and "password" not in cam and cam["users"] == []
assert CALLS == ["/live/ch0"]                                             # erster Kandidat passt -> keine weiteren Versuche
MODE["good_path"] = "/stream1"; CALLS.clear()
r = add(); assert r.status_code == 201 and r.get_json()["path_main"] == "/stream1" and r.get_json()["name"] == "Kamera 192.168.50.80", r.get_json()
cid2 = r.get_json()["id"]; assert CALLS.index("/stream1") >= 2 and CALLS[-1] == "/stream1"
MODE["good_path"] = "/mein/pfad"; r = add(path_main="mein/pfad"); assert r.status_code == 201 and r.get_json()["path_main"] == "/mein/pfad"   # eigener Pfad (ohne fuehrenden /)
cid3 = r.get_json()["id"]
print("Pfad-Suche OK")

# --- URLs (Sonderzeichen im Passwort), Qualitaet
it = camera.get(cid)
assert camera.rtsp_url(it, "klar") == "rtsp://admin:p%40ss%3Awort%2F1@192.168.50.80:554/live/ch0" and camera.rtsp_url(it, "fluessig") == camera.rtsp_url(it, "klar")   # ohne Teilstrom: gleicher Pfad
assert A.patch(f"/api/cameras/{cid}", json={"path_sub": "live/ch1", "port": 8554}).status_code == 200
it = camera.get(cid); assert it["path_sub"] == "/live/ch1" and it["port"] == 8554
assert camera.rtsp_url(it, "fluessig").endswith(":8554/live/ch1") and camera.rtsp_url(it, "klar").endswith(":8554/live/ch0")
assert A.patch(f"/api/cameras/{cid}", json={"path_main": "/live/ch9"}).status_code == 200 and camera.get(cid)["path_main"] == "/live/ch9"
assert A.patch(f"/api/cameras/{cid}", json={"path_sub": ""}).status_code == 200 and camera.get(cid)["path_sub"] == ""       # Teilpfad wieder leer
assert A.patch(f"/api/cameras/{cid}", json={"path_main": "/mit leer"}).status_code == 400
A.patch(f"/api/cameras/{cid}", json={"path_main": "/live/ch0", "port": ""})
# Reolink-Eintraege bleiben unberuehrt
assert camera.rtsp_url({"kind": "reolink", "host": "h", "user": "u", "password": "p", "channel": 0}, "klar").endswith("/Preview_01_main")
lst = A.get("/api/cameras").get_json()["cameras"]; assert [c for c in lst if c["id"] == cid][0]["path_main"] == "/live/ch0"
print("URLs OK")

# --- Standbild: ein Bild per ffmpeg, kurz zwischengespeichert, Rechte wie bei allen Kameras
A.patch(f"/api/cameras/{cid}", json={"users": ["ina"]})
MODE["good_path"] = "/live/ch0"; camera._snap_cache.clear(); CALLS.clear()
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 200 and r.mimetype == "image/jpeg" and r.data[:2] == b"\xff\xd8"
n = len(CALLS); I.get(f"/api/cameras/{cid}/snapshot"); assert len(CALLS) == n                                        # zwischengespeichert
# Kamera nicht erreichbar / falsches Passwort -> verstaendliche Meldung
camera._snap_cache.clear(); MODE["fail"] = "Connection refused"
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 503 and "nicht erreichbar" in r.get_json()["error"]
camera._snap_cache.clear(); MODE["fail"] = "401 Unauthorized"
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 503 and "Anmeldung" in r.get_json()["error"]
MODE["fail"] = "ok"
# ohne ffmpeg
real = camera.ffmpeg_path; camera.ffmpeg_path = lambda: None; camera._snap_cache.clear()
r = I.get(f"/api/cameras/{cid}/snapshot"); assert r.status_code == 503 and "ffmpeg" in r.get_json()["error"]
camera.ffmpeg_path = real
print("Standbild OK")

# --- Live nutzt die Pfade (Befehl ohne echte Kamera pruefen)
cmds = []
camera.ffmpeg_cmd_real = camera.ffmpeg_cmd
c = camera.ffmpeg_cmd(camera.get(cid), "klar"); assert any(x.endswith("/live/ch0") and x.startswith("rtsp://admin:") for x in c) and "-rtsp_transport" in c
print("RTSP OK")
