"""Klingelton probehoeren im Regel-Editor (1.63.5): POST /api/rules/chime-test laeutet die Chimes der gewaehlten Tuerklingel zur Probe.
Recht "Regeln: Schreiben" genuegt (wer die Regel anlegen darf, darf auch probehoeren), aber nur an Tuerklingeln, die das Konto sehen darf;
Ton und Kamera werden geprueft, Wiederholung hoechstens alle 3 Sekunden, Fehler der Kamera kommen als Meldung."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, auth
from auth import UserStore

camera.CAMERAS_PATH = os.path.join(tmp, "cameras.json")
RINGS = []
FAIL = [False]


def fake_ring_all(item, tone):
    RINGS.append((item["id"], tone))
    if FAIL[0]:
        raise camera.CameraError("Kein Chime verbunden")
    return 2


camera.chime_ring_all = fake_ring_all
base = {"kind": "reolink", "host": "192.168.2.50", "user": "u", "password": "p", "channel": 0, "model": "Reolink Video Doorbell WiFi", "users": None}
camera._save([{**base, "id": "door", "name": "Haustüre"},
              {**base, "id": "privat", "name": "Privat-Klingel", "users": ["admin"]},                       # nur fuer den Administrator sichtbar
              {**base, "id": "cam", "name": "Hof", "model": "RLC-810A"},                                     # keine Tuerklingel
              {**base, "id": "rtsp", "name": "Stream", "kind": "rtsp", "model": "Doorbell"}])
webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("regeln", "regelnpass123", {"dashboard": "read", "rules": "write", "kameras": "read"})
webapp.users.create("leser", "leserpass12345", {"dashboard": "read", "rules": "read", "kameras": "read"})
webapp.opslog.log = lambda *a, **k: None
app = webapp.app


def login(name, pw):
    c = app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


A, R, L = login("admin", "adminpass1"), login("regeln", "regelnpass123"), login("leser", "leserpass12345")
post = lambda c, body: c.post("/api/rules/chime-test", json=body)


def fresh():
    webapp._chime_test_last.clear()
    RINGS.clear()


# --- Konto mit "Regeln: Schreiben" darf probehoeren
fresh()
r = post(R, {"camera": "door", "tone": 6})
assert r.status_code == 200 and r.get_json() == {"ok": True, "chimes": 2, "tone": "Guten Tag"}, r.get_json()
assert RINGS == [("door", 6)]

# --- Ton als Text (aus dem Formular) und Grenzen
fresh()
assert post(R, {"camera": "door", "tone": "3"}).status_code == 200 and RINGS == [("door", 3)]
for bad in (None, "x", 10, -1, 99, "", {"a": 1}):
    fresh()
    assert post(R, {"camera": "door", "tone": bad}).status_code == 400, bad
    assert RINGS == []

# --- Nur Tuerklingeln, die das Konto sehen darf
for cid in ("privat", "cam", "rtsp", "gibtsnicht", "", None):
    fresh()
    r = post(R, {"camera": cid, "tone": 1})
    assert r.status_code == 404 and RINGS == [], (cid, r.status_code)
fresh()
assert post(A, {"camera": "privat", "tone": 1}).status_code == 200 and RINGS == [("privat", 1)]        # der Administrator sieht sie

# --- Rechte: Nur-Lesen und nicht angemeldet
fresh()
assert post(L, {"camera": "door", "tone": 1}).status_code == 403 and RINGS == []
assert app.test_client().post("/api/rules/chime-test", json={"camera": "door", "tone": 1}).status_code == 401

# --- Nicht zu oft: hoechstens alle 3 Sekunden je Tuerklingel
fresh()
assert post(R, {"camera": "door", "tone": 1}).status_code == 200
r = post(R, {"camera": "door", "tone": 2})
assert r.status_code == 429 and len(RINGS) == 1
assert post(A, {"camera": "privat", "tone": 2}).status_code == 200                  # andere Tuerklingel ist nicht betroffen
webapp._chime_test_last["door"] = time.time() - 4
assert post(R, {"camera": "door", "tone": 2}).status_code == 200 and len(RINGS) == 3

# --- Fehler der Kamera kommen als Meldung
fresh()
FAIL[0] = True
r = post(R, {"camera": "door", "tone": 1})
assert r.status_code == 503 and "Kein Chime verbunden" in r.get_json()["error"]
FAIL[0] = False

# --- Der Knopf steht im Regel-Editor (Regressionswaechter)
src = open(os.path.join(os.path.dirname(os.path.abspath(webapp.__file__)), "templates", "rules.html"), encoding="utf-8").read()
assert "a-chime-test" in src and "/api/rules/chime-test" in src and "▶ Probehören" in src
assert "onclick=\"chimeTest" not in src                                              # kein weiterer Inline-Handler (Schutzregel)

print("t_chime_test OK")
