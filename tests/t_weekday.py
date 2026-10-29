"""Bedingung 'Wochentag': normalisieren, auswerten (ganzer Kalendertag), Kombination mit Nacht/Tag, Speichern ueber die API."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules
from datetime import datetime
C = rules.normalize_condition

assert C({"type": "weekday", "days": [4, 0, "2", 0]}) == {"type": "weekday", "days": [0, 2, 4]}
for bad in ([], None, ["x"], [9]):
    try:
        C({"type": "weekday", "days": bad}); raise SystemExit("sollte scheitern %r" % (bad,))
    except rules.RuleError as e:
        assert "Wochentag" in str(e)

SUN = {"sunrise": 7 * 60 + 38, "sunset": 19 * 60 + 8}
mofr = C({"type": "weekday", "days": [0, 1, 2, 3, 4]})
def ev(c, day, h=12, m=0):                                   # 2026-10-05 ist ein Montag
    return rules.eval_condition(c, {"now": datetime(2026, 10, 5 + day, h, m), "sun": SUN})
res = [ev(mofr, d)[0] for d in range(7)]
assert res == [True, True, True, True, True, False, False], res
assert ev(mofr, 0, 0, 0)[0] is True and ev(mofr, 4, 23, 59)[0] is True and ev(mofr, 5, 0, 0)[0] is False        # ganzer Kalendertag
assert ev(mofr, 0)[1] == "nur Mo, Di, Mi, Do, Fr"
print("Auswertung OK")

# Regel: Tag (+60/+60) UND Mo-Fr -> Rollladen auf / SONST zu (wie im Handbuch) - speichern ueber die API
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_wd.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
rules.RULES_PATH = os.path.join(tmp, "r_wd.json")
rule = {"name": "Rollo Mo-Fr", "mode": "flow", "enabled": True,
        "when": {"mode": "all", "conds": [{"type": "sunwin", "phase": "day", "start": 60, "end": 60}, {"type": "weekday", "days": [0, 1, 2, 3, 4]}]},
        "then": [{"type": "switch", "device_id": "x"}], "else": []}
r = c.post("/api/automation", json={"rules": [{**rule, "then": [{"type": "wait", "seconds": 5}]}]})
assert r.status_code == 200, r.get_json()
saved = rules.list_rules()[0]
assert [x["type"] for x in saved["when"]["conds"]] == ["sunwin", "weekday"] and saved["when"]["conds"][1]["days"] == [0, 1, 2, 3, 4]
r = c.post("/api/automation", json={"rules": [{**rule, "then": [{"type": "wait", "seconds": 5}], "when": {"mode": "all", "conds": [{"type": "weekday", "days": []}]}}]})
assert r.status_code == 400 and "Wochentag" in r.get_json()["error"], r.get_json()
print("WEEKDAY OK")
