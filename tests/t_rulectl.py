import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules, autolog
from auth import UserStore
rules.RULES_PATH = os.path.join(tmp, "r_ctl.json")
webapp.users = UserStore(os.path.join(tmp, "u_rc.json")); webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None

# 1) Pruefen
assert rules.normalize_condition({"type": "rule", "id": "r1", "is": "off"}) == {"type": "rule", "id": "r1", "is": "off"}
assert rules.normalize_condition({"type": "rule", "id": "r1"})["is"] == "on"
try: rules.normalize_condition({"type": "rule", "id": ""}); raise SystemExit("Regel noetig")
except rules.RuleError: pass
a = rules._normalize_action({"type": "rule", "id": "r1", "state": "TOGGLE"}, flow=True); assert a == {"type": "rule", "id": "r1", "state": "toggle"}
for bad in ({"type": "rule", "id": "", "state": "on"}, {"type": "rule", "id": "r1", "state": "kaputt"}):
    try: rules._normalize_action(bad, flow=True); raise SystemExit("sollte scheitern")
    except rules.RuleError: pass
try: rules._normalize_action(a, flow=False); raise SystemExit("nur im Ablauf")
except rules.RuleError: pass
print("1) Pruefen OK")

# 2) Bedingung auswerten
from datetime import datetime
ctx = {"now": datetime(2026, 10, 10, 12, 0), "rules": {"r1": {"name": "Licht", "enabled": True}, "r2": {"name": "Nachts", "enabled": False}}}
assert rules.eval_condition({"type": "rule", "id": "r1", "is": "on"}, ctx)[0] is True
assert rules.eval_condition({"type": "rule", "id": "r2", "is": "on"}, ctx)[0] is False and rules.eval_condition({"type": "rule", "id": "r2", "is": "off"}, ctx)[0] is True
ok, txt = rules.eval_condition({"type": "rule", "id": "weg", "is": "on"}, ctx); assert ok is None and "nicht mehr vorhanden" in txt
assert "„Licht“ ist an" in rules.eval_condition({"type": "rule", "id": "r1", "is": "on"}, ctx)[1]
print("2) Bedingung OK")

# 3) Speicher: Regeln anlegen, set_enabled, Vermerke, Liste speichern
def flow(name, **kw):
    return {"name": name, "enabled": True, "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]},
            "then": [{"type": "wait", "seconds": 5}], "else": [], **kw}
r_a = rules.add_rule(flow("Nachtruhe")); r_b = rules.add_rule(flow("Bewegungslicht"))
assert rules.set_enabled(r_b["id"], "off", by="Nachtruhe") == (True, False)
assert rules.set_enabled(r_b["id"], "off", by="Nachtruhe") == (False, False)             # schon aus: keine Aenderung
assert rules.marks()[r_b["id"]]["by"] == "Nachtruhe" and rules.marks()[r_b["id"]]["state"] == "off"
assert [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is False
assert rules.set_enabled(r_b["id"], "toggle", by="X") == (True, True) and rules.set_enabled(r_b["id"], "on")[0] is False
try: rules.set_enabled("gibtsnicht", "on"); raise SystemExit("unbekannt")
except rules.RuleError: pass
# Liste speichern: nicht angefasst (keep_enabled) -> Serverstand bleibt, auch wenn die Seite einen alten Wert hat
rules.set_enabled(r_b["id"], "off", by="Nachtruhe")
items = [{**r_a, "keep_enabled": True}, {**r_b, "enabled": True, "keep_enabled": True}]      # Seite hat noch "an" (alt), hat aber nichts angefasst
rules.replace_all(items)
assert [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is False and r_b["id"] in rules.marks()
# von Hand umgeschaltet (angefasst): Wert gilt, Vermerk weg
rules.replace_all([{**r_a, "keep_enabled": True}, {**r_b, "enabled": True, "keep_enabled": False}])
assert [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is True and r_b["id"] not in rules.marks()
# Loeschen raeumt den Vermerk auf
rules.set_enabled(r_b["id"], "off", by="Nachtruhe"); assert r_b["id"] in rules.marks()
assert rules.delete_rule(r_b["id"]) and r_b["id"] not in rules.marks()
r_b = rules.add_rule(flow("Bewegungslicht"))
print("3) Speicher OK")

# 4) Schritt im Ablauf
log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
def run(step, dry=False):
    webapp.ctrl._apply_flow({"rule_id": r_a["id"], "rule": "Nachtruhe", "branch": "then", "step": step, "after_s": 0}, dry, {})
run({"type": "rule", "id": r_b["id"], "state": "off"}, dry=True)
assert "würde ausgeschaltet" in log[-1][2] and log[-1][3] and [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is True
run({"type": "rule", "id": r_b["id"], "state": "off"})
assert log[-1][0] == "rule" and "ausgeschaltet (jetzt aus)" in log[-1][2], log[-1]
assert [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is False and rules.marks()[r_b["id"]]["by"] == "Nachtruhe"
run({"type": "rule", "id": r_b["id"], "state": "off"}); assert "schon aus" in log[-1][2]
run({"type": "rule", "id": r_b["id"], "state": "on"}); assert "eingeschaltet" in log[-1][2] and [x for x in rules.list_rules() if x["id"] == r_b["id"]][0]["enabled"] is True
run({"type": "rule", "id": "weg", "state": "on"}); assert log[-1][0] == "fail"
print("4) Schritt OK")

# 5) API + Seite
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
rules.set_enabled(r_b["id"], "off", by="Nachtruhe")
j = c.get("/api/rules").get_json(); assert j["marks"][r_b["id"]]["by"] == "Nachtruhe", j.get("marks")
h = c.get("/rules").data.decode(); assert "'rule', 'Regel (an/aus)'" in h and "Regel ein-/ausschalten" in h and "keep_enabled" in h
print("RULECTL OK")

# 6) Ablauf-Regel mit der Bedingung "Regel ist aus": startet, sobald die andere Regel ausgeschaltet wird
import flows
fe = flows.FlowEngine(); fe._loaded = True
fl = {"id": "fx", "name": "Hinweis", "enabled": True, "mode": "flow", "when": {"mode": "all", "conds": [{"type": "rule", "id": "rb", "is": "off"}]}, "then": [{"type": "wait", "seconds": 1}], "else": []}
t0 = datetime(2026, 10, 10, 12, 0)
ev = fe.step(t0, {"rules": {"rb": {"name": "B", "enabled": True}}}, [fl]); assert not ev                                  # erste Messung: kein Start
ev = fe.step(t0, {"rules": {"rb": {"name": "B", "enabled": False}}}, [fl]); assert any(e[0] == "start" for e in ev), ev      # B aus -> Ablauf startet
print("6) Ablauf mit Regel-Bedingung OK")

# 7) Option "gleich anwenden" (run_now)
rn = rules.add_rule({**flow("Nachtruhe2"), "run_now": True}); assert rn["run_now"] is True
assert rules.add_rule(flow("Ohne"))["run_now"] is False
assert rules.update_rule(rn["id"], {"run_now": False})["run_now"] is False
def mkflow(rid, run_now, cond_true=True):
    return {"id": rid, "name": rid, "enabled": True, "mode": "flow", "run_now": run_now,
            "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00" if cond_true else "00:00", "to": "24:00" if cond_true else "00:01", "days": []}]},
            "then": [{"type": "wait", "seconds": 1}], "else": [{"type": "wait", "seconds": 2}]}
t1 = datetime(2026, 10, 10, 2, 0)
fe = flows.FlowEngine(); fe._loaded = True
ev = fe.step(t1, {}, [mkflow("a", False)]); assert not any(e[0] == "start" for e in ev), ev                  # ohne Option: erster Wert startet nichts
fe = flows.FlowEngine(); fe._loaded = True
ev = fe.step(t1, {}, [mkflow("b", True)]); assert any(e[0] == "start" and "schon erfüllt" in e[2] and "sofort angewendet" in e[2] for e in ev), ev      # Bedingung erfuellt -> DANN sofort
assert fe.runs and fe.runs[0]["branch"] == "then"
ev = fe.step(t1, {}, [mkflow("b", True)]); assert not any(e[0] == "start" for e in ev)                         # zweiter Durchlauf: nichts Neues
fe2 = flows.FlowEngine(); fe2._loaded = True; fe2.last = dict(fe.last)                                           # "Neustart": bekannter Wert -> kein erneuter Start
ev = fe2.step(t1, {}, [mkflow("b", True)]); assert not any(e[0] == "start" for e in ev)
fe3 = flows.FlowEngine(); fe3._loaded = True
ev = fe3.step(datetime(2026, 10, 10, 2, 0, 0), {}, [mkflow("c", True, cond_true=False)])                         # Bedingung nicht erfuellt -> SONST sofort
assert any(e[0] == "start" and "nicht erfüllt" in e[2] for e in ev) and fe3.runs[0]["branch"] == "else", ev
# ausschalten -> einschalten: startet wieder (Wert wurde vergessen)
off = {**mkflow("b", True), "enabled": False}
fe.step(t1, {}, [off]); assert "b" not in fe.last
ev = fe.step(t1, {}, [mkflow("b", True)]); assert any(e[0] == "start" for e in ev)
print("7) run_now OK")
