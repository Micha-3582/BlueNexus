"""Nachprüfung der Sicherheitsprüfung (1.28.1):
N-02 Telegram und Pushover (Bot, Empfänger, Freigaben, Einstellungen; Empfänger bekommen die Codes von "Passwort vergessen") und der VRM-Zugang nur durch Administratoren,
N-01 Cookies ohne Kennung nur für Konten, die beim Update schon bestanden, und nur ohne Passwortänderung,
N-03 Kennungen von Fremdgeräten enthalten nur harmlose Zeichen, N-04 Module und Zeitzone nur durch Administratoren."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth, notify, pushover, idsafe, homematic, zigbee, shelly, tasmota, wled
from auth import UserStore

notify.CRED_PATH = os.path.join(tmp, "tg.json"); pushover.CRED_PATH = os.path.join(tmp, "po.json")
json.dump({"token": "tok", "chat_id": "100"}, open(notify.CRED_PATH, "w"))
json.dump({"token": "a" * 30, "recipients": []}, open(pushover.CRED_PATH, "w"))


class FakeResp:
    status_code = 200
    def __init__(self, j): self._j = j
    def json(self): return self._j
def fake_post(url, data=None, files=None, json=None, timeout=0):
    return FakeResp({"status": 1, "ok": True})
pushover.requests.post = notify.requests.post = fake_post

upath = os.path.join(tmp, "u.json")
webapp.users = UserStore(upath); users = webapp.users
users.create("admin", "adminpass1")
users.create("mel", "melpass12345", {"dashboard": "read", "settings_meldungen": "write", "settings_system": "write", "settings_vrm": "write"})


def login(name, pw):
    c = webapp.app.test_client()
    assert c.post("/login", data={"username": name, "password": pw, "remember": "1"}).status_code == 302
    return c


A, M = login("admin", "adminpass1"), login("mel", "melpass12345")

# ---- N-02: alles rund um Telegram und Pushover (Bot, Empfaenger, Freigaben, Einstellungen, Tests) richtet nur ein Administrator ein
r = A.post("/api/notify/recipient", json={"name": "Hausmeister", "chat_id": "200", "system": True}); assert r.status_code == 201, r.get_data(as_text=True)
tg_sys = r.get_json()["id"]
r = A.post("/api/notify/recipient", json={"name": "Familie", "chat_id": "300"}); assert r.status_code == 201; tg_norm = r.get_json()["id"]
r = A.post("/api/pushover/recipient", json={"name": "Admin2", "user_key": "k" * 30, "system": True}); assert r.status_code == 201, r.get_data(as_text=True)
po_sys = r.get_json()["id"]
r = A.post("/api/pushover/recipient", json={"name": "Familie", "user_key": "f" * 30}); assert r.status_code == 201; po_norm = r.get_json()["id"]
before_tg = [x["id"] for x in notify.recipients()]; before_po = [x["id"] for x in pushover.recipients()]
cred_tg, cred_po = notify.load_credentials(), pushover.load()

# das Konto mit dem Recht "Meldungen: Schreiben" darf nichts davon: auch keine normalen Empfaenger
forbidden = [("post", "/api/notify/recipient", {"name": "X", "chat_id": "400"}), ("post", "/api/notify/recipient", {"name": "X", "chat_id": "400", "system": True}),
             ("post", "/api/pushover/recipient", {"name": "X", "user_key": "z" * 30}), ("post", "/api/pushover/recipient", {"name": "X", "user_key": "z" * 30, "system": True}),
             ("post", "/api/notify/credentials", {"token": "neuer-bot", "chat_id": "999"}), ("delete", "/api/notify/credentials", None),
             ("post", "/api/pushover/credentials", {"token": "b" * 30}), ("delete", "/api/pushover/credentials", None),
             ("post", "/api/notify/settings", {}), ("post", "/api/notify/test", {}), ("post", "/api/notify/detect", {}), ("post", "/api/pushover/test", {}),
             ("delete", "/api/notify/request/777", None), ("post", "/api/vrm/credentials", {"installation_id": "1", "token": "t"}), ("delete", "/api/vrm/credentials", None)]
for rid in ("main", tg_sys, tg_norm):
    forbidden += [("patch", "/api/notify/recipient/" + rid, {"name": "x"}), ("patch", "/api/notify/recipient/" + rid, {"system": True}), ("delete", "/api/notify/recipient/" + rid, None)]
for rid in (po_sys, po_norm):
    forbidden += [("patch", "/api/pushover/recipient/" + rid, {"name": "x"}), ("patch", "/api/pushover/recipient/" + rid, {"system": True}), ("delete", "/api/pushover/recipient/" + rid, None)]
for method, url, body in forbidden:
    r = getattr(M, method)(url, json=body) if body is not None else getattr(M, method)(url)
    assert r.status_code == 403, (method, url, r.status_code)
assert M.get("/api/notify").status_code == 200 and M.get("/api/pushover").status_code == 200 and M.get("/api/notify/requests").status_code == 200     # Ansehen bleibt
# nichts hat sich veraendert
assert [x["id"] for x in notify.recipients()] == before_tg and [x["id"] for x in pushover.recipients()] == before_po
assert notify.load_credentials() == cred_tg and pushover.load() == cred_po
# der Administrator darf weiter alles
assert A.patch("/api/notify/recipient/" + tg_norm, json={"name": "Familie 2"}).status_code == 200
assert A.patch("/api/pushover/recipient/" + po_norm, json={"name": "Familie 2"}).status_code == 200
assert A.delete("/api/notify/recipient/" + tg_sys).status_code == 200 and A.delete("/api/pushover/recipient/" + po_sys).status_code == 200
assert A.post("/api/notify/credentials", json={"token": "tok2", "chat_id": "100"}).status_code == 200
assert A.post("/api/pushover/credentials", json={"token": "c" * 30}).status_code == 200

# ---- N-04: Module und Zeitzone nur durch Administratoren (Ansehen bleibt)
assert M.post("/api/modules", json={"energy": False}).status_code == 403
assert M.post("/api/system/timezone", json={"timezone": "Europe/Berlin"}).status_code == 403
assert M.get("/api/modules").status_code == 200

# ---- N-01: Cookies ohne Kennung (aus der Zeit vor 1.28.0)
def legacy(name):
    c = webapp.app.test_client()
    with c.session_transaction() as s:
        s["user"] = name; s.permanent = True
    return c
ok = lambda c: c.get("/api/status").status_code == 200
# a) neu angelegtes Konto: nie
users.create("neu", "neupass123456", auth.PRESETS["user"])
assert users.get("neu")["legacy_session_ok"] is False and not ok(legacy("neu")), "neues Konto: Cookie ohne Kennung darf nicht gelten"
# b) Konto, das beim Update schon bestand (Datei ohne Kennung/Merkmal): gilt einmal weiter ...
raw = json.load(open(upath, encoding="utf-8"))
for k in ("admin", "mel"):
    for f in ("uid", "sess_epoch", "legacy_session_ok"): raw["users"][k].pop(f, None)
json.dump(raw, open(upath, "w", encoding="utf-8"))
webapp.users = users = UserStore(upath)
assert users.get("mel")["legacy_session_ok"] is True and users.get("mel")["sess_epoch"] == 0
L = legacy("mel"); assert ok(L), "Konto von vor dem Update: altes Cookie gilt noch"
with L.session_transaction() as s: assert s.get("uid") == users.get("mel")["uid"] and s.get("ep") == 0
# c) ... aber nicht mehr nach einer Passwortaenderung (auch nicht, wenn das Cookie vorher nie benutzt wurde)
stolen = legacy("mel")
users.update_password("mel", "melneu1234567")
assert not ok(L) and not ok(stolen), "nach der Passwortaenderung gilt kein altes Cookie mehr"
# d) geloescht und neu angelegt (S-02): altes Cookie ohne Kennung gilt nicht fuer das neue Konto
old = legacy("mel"); users.delete("mel"); users.create("mel", "melwieder12345", auth.PRESETS["admin"])
assert not ok(old) and old.get("/api/apikeys").status_code in (401, 403)

# ---- N-03: Kennungen von Fremdgeraeten
assert idsafe.safe_id("OEQ1234567:1") == "OEQ1234567:1" and idsafe.safe_id("AABBCCDDEEFF") == "AABBCCDDEEFF" and idsafe.safe_id("0x00158d0001234567") == "0x00158d0001234567"
assert idsafe.safe_id("x');fetch('/api/users');('") == "x___fetch___api_users_____" and idsafe.safe_id("<img src=x onerror=1>") == "_img_src_x_onerror_1_"
assert homematic.entry_id("OEQ1234567:1") == "hm-OEQ1234567-1" and homematic.sensor_id("000A:3", "STATE") == "hmS-000A-3-STATE"      # normale Kennungen bleiben unveraendert
assert homematic.setpoint_id("000A:3") == "hmT-000A-3" and homematic.lock_id("000A:3") == "hmK-000A-3" and homematic.blind_id("000A:3") == "hmR-000A-3" and homematic.sound_id("000A:3") == "hmA-000A-3"
assert zigbee.device_id("00:15:8d:00:01:23:45:67-01") == "zb-00-15-8d-00-01-23-45-67-01"
safe = lambda out: all(ch.isalnum() or ch in "._:-" for ch in out)
for out in (homematic.entry_id("A');x:1"), homematic.sensor_id("A'x", 'ST"ATE'), homematic.setpoint_id("A'x"), homematic.lock_id("A'x"), homematic.blind_id("A'x"), homematic.sound_id("A'x"),
            zigbee.device_id("a'b"), zigbee.sensor_id("a'b"), zigbee.thermostat_id("a'b")):
    assert safe(out), out
evil = "x');fetch('/api/users');('"
shelly._get = lambda ip, path, timeout=0, **k: {"mac": evil, "gen": 1, "type": "SHSW-1", "auth": False}
p = shelly.probe("192.168.50.9")
assert p is None or all(ch.isalnum() or ch in "._:-" for ch in p["mac"]), p
tasmota._cmd = lambda ip, cmd, timeout=0, auth=None: {"Status": {"FriendlyName": ["T"], "Topic": "t"}, "StatusNET": {"Mac": evil}, "StatusSTS": {"POWER": "ON"}}
p = tasmota.probe("192.168.50.9")
assert p is None or all(ch.isalnum() or ch in "._:-" for ch in p["mac"]), p
wled._get = lambda ip, path, timeout=0, retries=0: {"ver": "0.14", "mac": evil, "brand": "WLED", "leds": {"count": 3}}
p = wled.probe("192.168.50.9")
assert p is None or all(ch.isalnum() or ch in "._:-" for ch in p["mac"]), p
print("SICHERHEIT 1.28.1 OK", sys.argv[1].split("/")[-1])
