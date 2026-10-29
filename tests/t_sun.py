"""Sonnenaufgang/-untergang als Regel-Bedingung + Telegram-Standbild als Ablauf-Schritt."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules, flows, sun, notify, camera, autolog
from datetime import datetime, date

# --- Rechner: Alpen (51.59 / 6.5), Server-Zeitzone Mitteleuropa vorausgesetzt (Testrechner auch)
t = sun.times(date(2026, 6, 21), 51.59, 6.5)
assert 5 * 60 + 5 <= t["sunrise"] <= 5 * 60 + 30 and 21 * 60 + 45 <= t["sunset"] <= 22 * 60 + 5, t            # Sommer: ~05:16 / ~21:55
t = sun.times(date(2026, 12, 21), 51.59, 6.5)
assert 8 * 60 + 25 <= t["sunrise"] <= 8 * 60 + 50 and 16 * 60 + 15 <= t["sunset"] <= 16 * 60 + 40, t            # Winter: ~08:37 / ~16:26
assert sun.times(date(2026, 6, 21), 89.0, 0.0) is None                                                       # Polartag
assert sun.for_config({}, date(2026, 6, 21)) is None and sun.for_config({"weather_lat": 51.6, "weather_lon": 6.5}, date(2026, 6, 21))
print("Sonnenzeiten OK")

# --- Bedingung speichern/pruefen
C = rules.normalize_condition
assert C({"type": "sun", "event": "sunset"}) == {"type": "sun", "event": "sunset", "offset": 0, "days": []}
assert C({"type": "sun", "event": "sunrise", "offset": "-30", "days": [0, 1]})["offset"] == -30
for bad in ({"type": "sun", "event": "mittag"}, {"type": "sun", "event": "sunset", "offset": 1000}):
    try:
        C(bad); raise SystemExit("sollte scheitern")
    except rules.RuleError:
        pass

SUN = {"sunrise": 7 * 60 + 38, "sunset": 19 * 60 + 8}
D = datetime(2026, 10, 4, 19, 10)
ev = lambda c, now=D, **k: rules.eval_condition(C(c), {"now": now, "sun": SUN, **k}, **({"fired_today": k.pop("fired", False)} if False else {}))
ok = lambda c, now=D, fired=False, sunv=SUN: rules.eval_condition(C(c), {"now": now, "sun": sunv}, 0.0, fired)[0]
assert ok({"type": "sun", "event": "sunset"}) is True                                       # 2 Min nach Untergang
assert ok({"type": "sun", "event": "sunset"}, D.replace(hour=19, minute=7)) is False        # noch davor
assert ok({"type": "sun", "event": "sunset"}, D.replace(hour=19, minute=45)) is False       # mehr als 30 Min danach
assert ok({"type": "sun", "event": "sunset", "offset": 30}, D.replace(hour=19, minute=40)) is True
assert ok({"type": "sun", "event": "sunset", "offset": -30}, D.replace(hour=18, minute=45)) is True
assert ok({"type": "sun", "event": "sunrise"}, D.replace(hour=7, minute=40)) is True
assert ok({"type": "sun", "event": "sunset"}, fired=True) is False                          # nur einmal pro Tag
assert ok({"type": "sun", "event": "sunset", "days": [0]}) is False and ok({"type": "sun", "event": "sunset", "days": [6]}) is True      # 4.10.2026 = Sonntag
v, txt = rules.eval_condition(C({"type": "sun", "event": "sunset"}), {"now": D, "sun": None})
assert v is None and "Standort" in txt, txt
print("Bedingung auswerten OK")

# --- Zustandsregel: "bei Sonnenaufgang -> Beleuchtung aus" (reiner Ausschalt-Timer) und "bei Sonnenuntergang -> ein"
rules.RULES_PATH = os.path.join(tmp, "rules2.json"); rules.STATE_PATH = os.path.join(tmp, "rules2_state.json")
aus = rules.normalize_rule({"name": "Licht aus", "when": {"mode": "all", "conds": [{"type": "sun", "event": "sunrise"}]}, "then": [{"device_id": "licht", "state": "off"}], "else": []}, "r-aus")
an = rules.normalize_rule({"name": "Licht an", "when": {"mode": "all", "conds": [{"type": "sun", "event": "sunset"}]}, "then": [{"device_id": "licht", "state": "on"}], "else": []}, "r-an")
eng = rules.RuleEngine(); eng._loaded = True
compiled = rules.compile_all([aus, an])
dev = lambda on: [{"id": "licht", "name": "Licht", "online": True, "on": on, "switchable": True}]
cfg0 = {}
act = eng.step(datetime(2026, 10, 4, 7, 40), {"sun": SUN}, cfg0, dev(True), compiled)
assert [a[0] for a in act] == ["off"] and "Sonnenaufgang" in act[0][2], act                    # Sonnenaufgang: aus, auch wenn von Hand an
act = eng.step(datetime(2026, 10, 4, 7, 41), {"sun": SUN}, cfg0, dev(True), compiled)
assert act == [], act                                                                          # einmal pro Tag: wer es danach wieder einschaltet, wird nicht gleich wieder ausgeschaltet
eng2 = rules.RuleEngine(); eng2._loaded = True
act = eng2.step(datetime(2026, 10, 4, 19, 12), {"sun": SUN}, cfg0, dev(False), compiled)
assert [a[0] for a in act] == ["on"] and "Sonnenuntergang" in act[0][2], act
act = eng2.step(datetime(2026, 10, 4, 12, 0), {"sun": SUN}, cfg0, dev(False), compiled)
assert act == [], act                                                                          # mittags nichts
act = eng2.step(datetime(2026, 10, 4, 19, 13), {"sun": None}, cfg0, dev(False), compiled)
assert act == [], act                                                                          # ohne Standort: nichts
print("Zustandsregeln OK")

# --- Ablauf-Regel mit Standbild
cam = {"id": "cam-1", "kind": "reolink", "name": "Hof", "host": "x", "user": "", "password": "", "users": []}
camera.CAMERAS_PATH = os.path.join(tmp, "cameras.json"); camera._save([cam])
body = {"name": "Foto bei Klingel", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "sun", "event": "sunset"}]},
        "then": [{"type": "photo", "id": "cam-1", "text": "  Dämmerung  "}], "else": []}
r = rules.normalize_rule(body, "f1")
assert r["then"][0] == {"type": "photo", "id": "cam-1", "text": "Dämmerung"} and rules.devices_of(r) == []
for bad in ({"type": "photo", "id": ""}, ):
    try:
        rules.normalize_rule({**body, "then": [bad]}); raise SystemExit("sollte scheitern")
    except rules.RuleError:
        pass
try:
    rules.normalize_rule({**body, "mode": None, "then": [{"type": "photo", "id": "cam-1"}]}); raise SystemExit("nur im Ablauf")
except rules.RuleError as e:
    assert "Standbild" in str(e)

sent, log = [], []
notify.CRED_PATH = os.path.join(tmp, "tg.json"); json.dump({"token": "T", "chat_id": "1"}, open(notify.CRED_PATH, "w"))
notify.send_photo = lambda jpeg, caption="", token=None, chat_id=None: sent.append((jpeg, caption))
camera.snapshot = lambda item, max_age=None: b"\xff\xd8JPEG-" + item["id"].encode()
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
webapp.opslog.log = lambda *a, **k: None
ctrl = webapp.ctrl
def run(step, dry=False):
    ctrl._apply_flow({"rule_id": "f1", "rule": "Test", "branch": "then", "step": step, "after_s": 0}, dry, {"app_display_name": "Anlage"})
    time.sleep(0.3)
run({"type": "photo", "id": "cam-1", "text": "Bewegung im Hof"})
assert sent == [(b"\xff\xd8JPEG-cam-1", "[Anlage] Bewegung im Hof")], sent
assert log[-1][0] == "notify" and "Hof" in log[-1][2] and "gesendet" in log[-1][2], log[-1]
run({"type": "photo", "id": "cam-1", "text": ""})
assert sent[-1][1] == "[Anlage] 📷 Hof", sent[-1]                                              # ohne Text: Kameraname
n = len(sent); run({"type": "photo", "id": "cam-1", "text": "x"}, dry=True)
assert len(sent) == n and log[-1][3] and "würde" in log[-1][2], log[-1]                         # Trockenlauf: nichts gesendet
run({"type": "photo", "id": "cam-weg"}); assert log[-1][0] == "fail" and len(sent) == n
os.remove(notify.CRED_PATH); run({"type": "photo", "id": "cam-1"}); assert "NICHT" in log[-1][2] and len(sent) == n   # Telegram nicht eingerichtet
print("Standbild-Schritt OK")

# --- Speichern ueber die Seite: unbekannte Kamera abgelehnt; Kamera loeschen entfernt den Schritt
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "users.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
rb = {"rules": [{**body, "then": [{"type": "photo", "id": "cam-x", "text": ""}]}]}
r_ = c.post("/api/automation", json=rb); assert r_.status_code == 400 and "Kamera" in r_.get_json()["error"], r_.get_json()
r_ = c.post("/api/automation", json={"rules": [body]}); assert r_.status_code == 200, r_.get_json()
j = c.get("/api/rules").get_json()
assert j["sun"]["configured"] is False and j["rules"][0]["when"]["conds"][0]["type"] == "sun"
cfg["weather_lat"], cfg["weather_lon"] = 51.59, 6.5
j = c.get("/api/rules").get_json(); assert j["sun"]["configured"] and j["sun"]["sunrise"] and j["sun"]["sunset"], j["sun"]
assert webapp.ctrl._rules_ctx(cfg, None, datetime(2026, 10, 4, 12, 0))["sun"]["sunset"] > 1000
assert c.delete("/api/cameras/cam-1").status_code == 409                                     # Regel verwendet die Kamera
rules.replace_all([{**r_, "enabled": False} for r_ in rules.list_rules()])
assert c.delete("/api/cameras/cam-1").status_code == 200
assert rules.list_rules() == [], rules.list_rules()                                            # einziger Schritt weg -> Regel weg (wie bei Schloss/WOL)
print("Seite/Kamera loeschen OK")

# --- Oberflaeche rendert
page = c.get("/rules").get_data(as_text=True)
assert "Sonnenaufgang / Sonnenuntergang" in page and "Kamera-Standbild senden" in page and "sunDir" in page
print("Seite OK")
