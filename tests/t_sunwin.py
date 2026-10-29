"""Nacht/Tag-Bedingung (eine Regel: abends an, morgens aus) + Telegram-Prefix abschaltbar."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules, notify
from datetime import datetime
C = rules.normalize_condition

SUN = {"sunrise": 7 * 60 + 38, "sunset": 19 * 60 + 8}
ev = lambda c, h, m=0, sun=SUN: rules.eval_condition(C(c), {"now": datetime(2026, 10, 4, h, m), "sun": sun})
night = {"type": "sunwin", "phase": "night"}
assert C(night) == {"type": "sunwin", "phase": "night", "start": 0, "end": 0}
for bad in ({"type": "sunwin", "phase": "abend"}, {"type": "sunwin", "phase": "night", "start": 5000}):
    try:
        C(bad); raise SystemExit("sollte scheitern")
    except rules.RuleError:
        pass
assert ev(night, 23)[0] is True and ev(night, 3)[0] is True and ev(night, 12)[0] is False        # Nacht ueber Mitternacht
assert ev(night, 19, 7)[0] is False and ev(night, 19, 8)[0] is True and ev(night, 7, 37)[0] is True and ev(night, 7, 38)[0] is False
off30 = {**night, "start": 30}
assert ev(off30, 19, 30)[0] is False and ev(off30, 19, 38)[0] is True                              # 30 Min nach Untergang
day = {"type": "sunwin", "phase": "day", "end": -30}
assert ev(day, 12)[0] is True and ev(day, 18, 40)[0] is False and ev(day, 6)[0] is False
v, txt = ev(night, 23, sun=None); assert v is None and "Standort" in txt
assert "Nacht" in ev(night, 23)[1] and "Sonnenuntergang" in ev(night, 23)[1]

# Eine Regel: DANN an, SONST aus -> Licht folgt der Nacht
rules.RULES_PATH = os.path.join(tmp, "r.json"); rules.STATE_PATH = os.path.join(tmp, "rs.json")
r = rules.normalize_rule({"name": "Poolhaus", "when": {"mode": "all", "conds": [{**night, "start": 30}]},
                          "then": [{"device_id": "led", "state": "on"}], "else": [{"device_id": "led", "state": "off"}]}, "p1")
eng = rules.RuleEngine(); eng._loaded = True
comp = rules.compile_all([r])
dev = lambda on: [{"id": "led", "name": "LED", "online": True, "on": on, "switchable": True}]
step = lambda h, m, on: [a[0] for a in eng.step(datetime(2026, 10, 4, h, m), {"sun": SUN}, {}, dev(on), comp)]
assert step(12, 0, False) == []
assert step(19, 20, False) == []                          # noch nicht (Untergang + 30 Min = 19:38)
assert step(19, 40, False) == ["on"]
eng.set_owner("led", "rule", "p1")
assert step(23, 0, True) == []
assert step(7, 40, True) == ["off"]                       # Sonnenaufgang vorbei: aus

# Telegram-Prefix
c0 = {"app_display_name": "Hanss Victron Steuerung"}
assert notify._prefix(c0) == "[Hanss Victron Steuerung] " and notify._prefix({**c0, "notify_prefix": True}) == "[Hanss Victron Steuerung] "
assert notify._prefix({**c0, "notify_prefix": False}) == ""
assert notify.settings_public({})["prefix"] is True and notify.settings_public({"notify_prefix": False})["prefix"] is False
assert notify.validate_settings({"prefix": False}) == {"notify_prefix": False}
sent = []
notify.CRED_PATH = os.path.join(tmp, "tg.json"); json.dump({"token": "T", "chat_id": "1"}, open(notify.CRED_PATH, "w"))
notify.send = lambda text, token=None, chat_id=None, to=None: sent.append(text)
notify.message("Hallo", {**c0, "notify_prefix": False}); time.sleep(0.3)
notify.message("Hallo", c0); time.sleep(0.3)
assert sent == ["Hallo", "[Hanss Victron Steuerung] Hallo"], sent
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
assert c.post("/api/notify/settings", json={"prefix": False}).status_code == 200 and cfg["notify_prefix"] is False
assert c.get("/api/notify").get_json()["prefix"] is False
page = c.get("/rules").get_data(as_text=True); assert "Nacht / Tag (Sonnenstand)" in page
assert 'id="nt-prefix"' in c.get("/automation").get_data(as_text=True) or 'id="nt-prefix"' in c.get("/admin").get_data(as_text=True)
print("SUNWIN + PREFIX OK")
