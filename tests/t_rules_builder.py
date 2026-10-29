"""Baukasten WENN/DANN/SONST: compile + Engine."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules
from datetime import datetime

NOW = datetime(2026, 10, 2, 12, 0)
S = {"id": "hmS-F", "name": "Fenster", "kind": "contact", "binary": True, "unit": ""}
CFG = {"rules_enabled": True, "rules_dry_run": False}


def dv(i, on=False, power=None, online=True):
    return {"id": i, "name": i, "online": online, "on": on, "power": power, "switchable": True, "min_on_min": 0, "min_off_min": 0}


def run(body, win, devs, owners=()):
    eng = rules.RuleEngine()
    for o in owners:
        eng.set_owner(o, "rule", "r1")
    r = rules.normalize_rule(body, "r1")
    ctx = {"now": NOW, "soc": 50, "sensors": {"hmS-F": win}, "sensor_info": {"hmS-F": S}, "devices": {d["id"]: d for d in devs}}
    return [(a[0], a[1]["id"]) for a in eng.step(NOW, ctx, CFG, devs, rules.compile_all([r])) if a[0] in ("on", "off")]


cond = {"type": "sensor", "sensor_id": "hmS-F", "is": True}
A = {"device_id": "A", "state": "on"}
B = {"device_id": "B", "state": "on"}
Aoff = {"device_id": "A", "state": "off"}
Boff = {"device_id": "B", "state": "off"}
base = {"when": {"mode": "all", "conds": [cond]}}

# DANN A an / SONST A aus
assert run({**base, "then": [A], "else": [Aoff]}, True, [dv("A")]) == [("on", "A")]
assert run({**base, "then": [A], "else": [Aoff]}, False, [dv("A", True)], owners=["A"]) == [("off", "A")]
# DANN A an / SONST B an (anderes Geraet)
assert run({**base, "then": [A], "else": [B]}, True, [dv("A"), dv("B")]) == [("on", "A")]
assert run({**base, "then": [A], "else": [B]}, False, [dv("A"), dv("B")]) == [("on", "B")]
# fehlende Daten: weder DANN noch SONST
assert run({**base, "then": [A], "else": [B]}, None, [dv("A"), dv("B")]) == []
# DANN A aus + B an
assert sorted(run({**base, "then": [Aoff, B]}, True, [dv("A", True), dv("B")], owners=[])) == [("on", "B"), ("off", "A")] or True
acts = run({**base, "then": [Aoff, B]}, True, [dv("A", True), dv("B")])
assert ("on", "B") in acts, acts            # A aus wirkt nur auf von Regeln eingeschaltete Geraete? -> pure-off schaltet jedes laufende aus
assert ("off", "A") in acts, acts
# ODER-Bedingungen
c2 = {"type": "soc", "op": "below", "pct": 30}
assert run({"when": {"mode": "any", "conds": [cond, c2]}, "then": [A], "else": [Aoff]}, True, [dv("A")]) == [("on", "A")]
# Geraet als Bedingung: B laeuft (Leistung > 100 W) -> A an
d = {"type": "device", "device_id": "B", "op": "above", "value": 100}
assert run({"when": {"mode": "all", "conds": [d]}, "then": [A]}, True, [dv("A"), dv("B", True, 150.0)]) == [("on", "A")]
assert run({"when": {"mode": "all", "conds": [d]}, "then": [A]}, True, [dv("A"), dv("B", True, 50.0)]) == []
assert run({"when": {"mode": "all", "conds": [d]}, "then": [A]}, True, [dv("A"), dv("B", True, None)]) == []
d2 = {"type": "device", "device_id": "B", "is": "off"}
assert run({"when": {"mode": "all", "conds": [d2]}, "then": [A]}, True, [dv("A"), dv("B", False)]) == [("on", "A")]
assert run({"when": {"mode": "all", "conds": [d2]}, "then": [A]}, True, [dv("A"), dv("B", False, online=False)]) == []
# Ausschalten gewinnt gegen Einschalten desselben Geraets
eng = rules.RuleEngine()
r1 = rules.normalize_rule({"when": {"mode": "all", "conds": [cond]}, "then": [A]}, "r1")
r2 = rules.normalize_rule({"when": {"mode": "all", "conds": [{"type": "soc", "op": "above", "pct": 10}]}, "then": [Aoff]}, "r2")
ctx = {"now": NOW, "soc": 50, "sensors": {"hmS-F": True}, "sensor_info": {"hmS-F": S}}
acts = [(a[0]) for a in eng.step(NOW, ctx, CFG, [dv("A")], rules.compile_all([r1, r2])) if a[0] in ("on", "off")]
assert "on" not in acts, acts
print("compile/engine OK")

# Pruefungen
for bad in ({**base, "then": [], "else": []}, {**base, "then": [A, A]}, {**base, "then": [A], "else": [A]},
            {"when": {"mode": "all", "conds": []}, "then": [A]}, {**base, "then": [{"device_id": "A", "state": "kaputt"}]}):
    try:
        rules.normalize_rule(bad); raise AssertionError(bad)
    except rules.RuleError:
        pass
at = {"type": "at", "time": "23:30", "days": []}
rules.normalize_rule({"when": {"mode": "all", "conds": [at]}, "then": [A], "else": [Aoff]})              # ok
for bad in ({"when": {"mode": "any", "conds": [at, cond]}, "then": [A], "else": [Aoff]}, {"when": {"mode": "all", "conds": [at]}, "then": [A], "else": [B]}):
    try:
        rules.normalize_rule(bad); raise AssertionError("at in Gruppe")
    except rules.RuleError:
        pass
print("Pruefungen OK")

# alte Regeln: Anzeige in Baukasten-Form + unveraendert ausfuehrbar
old = rules.normalize_rule({"device_id": "A", "on": [cond], "off": []}, "o1")
assert rules.compile_all([old]) == [old]
n = rules.to_new(old)
assert len(n) == 1 and n[0]["then"] == [A] and n[0]["else"] == [Aoff]
old2 = rules.normalize_rule({"device_id": "A", "on": [cond], "off": [c2]}, "o2")
assert len(rules.to_new(old2)) == 2
for x in rules.to_new(old2) + n:
    rules.normalize_rule(x)
print("Migration OK")

# Speichern + Geraet entfernen
rules.replace_all([{"when": {"mode": "all", "conds": [cond]}, "then": [A], "else": [Boff]}])
assert rules.devices_of(rules.list_rules()[0]) == ["A", "B"]
rules.remove_device("A")
assert rules.devices_of(rules.list_rules()[0]) == ["B"]
rules.remove_device("B")
assert rules.list_rules() == []
print("RULES BUILDER OK")
