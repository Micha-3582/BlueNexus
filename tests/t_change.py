"""Bedingung "Sensor: Wert aendert sich um ..." (1.42.0) und Platzhalter [WERT], [ZAHL], [ALT], [SENSOR], [UHR], [REGEL] in Nachrichten.
Prueft: Pruefen/Normalisieren, Zeitpunkt der Ausloesung (Startwert, Schrittweite, Richtung, Gegenrichtung setzt den Bezug neu), zwei Aenderungen
hintereinander, Werte im Ablauf, Ersetzen im Text, nur Ablauf-Regeln, Neustart behaelt den Bezugswert."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules, flows
from datetime import datetime

flows.STATE_PATH = os.path.join(tmp, "flows_state_change.json")

# ---------------------------------------------------------------- Pruefen
c = rules.normalize_condition({"type": "change", "sensor_id": "s1", "step": "1,5", "dir": "up"})
assert c == {"type": "change", "sensor_id": "s1", "step": 1.5, "dir": "up"}, c
assert rules.normalize_condition({"type": "change", "sensor_id": "s1", "step": 1})["dir"] == "any"
for bad in ({"type": "change", "step": 1}, {"type": "change", "sensor_id": "s1", "step": 0}, {"type": "change", "sensor_id": "s1", "step": 1, "dir": "quer"}):
    try:
        rules.normalize_condition(bad); raise AssertionError("muss abgelehnt werden: %r" % bad)
    except rules.RuleError:
        pass
body = {"name": "x", "mode": "state", "when": {"mode": "all", "conds": [c]}, "then": [{"device_id": "d1", "state": "on"}], "else": []}
try:
    rules.normalize_rule(body); raise AssertionError("nur Ablauf-Regeln")
except rules.RuleError as e:
    assert "Ablauf" in str(e)
c1 = rules.normalize_condition({"type": "change", "sensor_id": "s1", "step": 1, "dir": "up"})
flow_body = {"name": "Druckfortschritt", "mode": "flow", "when": {"mode": "all", "conds": [c1]}, "then": [{"type": "notify", "text": "[SENSOR]: [WERT] (vorher [ALT])"}], "else": []}
assert rules.normalize_rule(flow_body)["mode"] == "flow"

# ---------------------------------------------------------------- Auswertung
assert rules.change_check(None, 5.0, 1) == (False, 5.0)                       # Startwert merken
assert rules.change_check(5.0, 5.4, 1) == (False, 5.0)                        # zu wenig
assert rules.change_check(5.0, 6.0, 1) == (True, 6.0)
assert rules.change_check(5.0, 3.5, 1.5) == (True, 3.5)                       # beide Richtungen
assert rules.change_check(5.0, 3.0, 1, "up") == (False, 3.0)                  # Gegenrichtung: Bezug neu, keine Ausloesung
assert rules.change_check(5.0, 6.0, 1, "down") == (False, 6.0)
assert rules.change_check(0.1 + 0.2, 1.3, 1.0) == (True, 1.3)                 # Gleitkomma-Toleranz
assert rules.fmt_num(43) == "43" and rules.fmt_num(21.5) == "21,5" and rules.fmt_num(219.456) == "219,46" and rules.fmt_num(None) == "–"

# ---------------------------------------------------------------- Ablauf
SENS = {"s1": {"id": "s1", "name": "Druckfortschritt", "unit": "%", "kind": "progress"}}
rule = rules.normalize_rule(flow_body, "r1"); rule["enabled"] = True
eng = flows.FlowEngine()


def run(val, rules_=None):
    ctx = {"sensors": {"s1": val}, "sensor_info": SENS}
    ev = eng.step(datetime(2026, 11, 6, 14, 35), ctx, rules_ or [rule])
    return ev, eng.advance()


ev, acts = run(10.0)
assert not acts, "erster Durchlauf merkt nur den Startwert"
ev, acts = run(10.4); assert not acts
ev, acts = run(11.0)
assert len(acts) == 1 and acts[0]["step"]["type"] == "notify", acts
assert acts[0]["vars"] == {"wert": "11 %", "zahl": "11", "alt": "10 %", "sensor": "Druckfortschritt"}, acts[0]["vars"]
text = rules.fill_vars(acts[0]["step"]["text"], acts[0]["vars"], "Druckfortschritt", datetime(2026, 11, 6, 14, 35))
assert text == "Druckfortschritt: 11 % (vorher 10 %)", text
assert rules.fill_vars("[UHR] [REGEL] [WERT]", {}, "R", datetime(2026, 11, 6, 14, 35)) == "14:35 R –"
ev, acts = run(11.0); assert not acts                                         # gleicher Wert: nichts
ev, acts = run(12.0); assert len(acts) == 1 and acts[0]["vars"]["wert"] == "12 %", acts      # naechste Aenderung (die Bedingung war im Durchlauf davor schon wieder falsch)
ev, acts = run(13.0); assert len(acts) == 1 and acts[0]["vars"]["alt"] == "12 %", acts       # und noch eine
ev, acts = run(15.0); assert len(acts) == 1 and acts[0]["vars"]["alt"] == "13 %", acts        # zwei Aenderungen direkt hintereinander: jede loest aus

# Bezugswert bleibt nach einem Neustart erhalten
eng2 = flows.FlowEngine()
ev = eng2.step(datetime(2026, 11, 6, 14, 36), {"sensors": {"s1": 15.0}, "sensor_info": SENS}, [rule]); assert not eng2.advance()
ev = eng2.step(datetime(2026, 11, 6, 14, 37), {"sensors": {"s1": 16.0}, "sensor_info": SENS}, [rule]); a = eng2.advance()
assert len(a) == 1 and a[0]["vars"]["alt"] == "15 %", a

# Sensor weg / ohne Wert: nichts, Regel bleibt "keine Daten"
ev = eng2.step(datetime(2026, 11, 6, 14, 38), {"sensors": {}, "sensor_info": SENS}, [rule]); assert not eng2.advance()
assert "keine Daten" in eng2.status["r1"]["text"] or eng2.status["r1"]["state"] == "off", eng2.status

# Regel-Kontext liefert den Wert auch dann, wenn der Sensor NUR in einer "Wert aendert sich"-Bedingung vorkommt (Fehler in 1.42.0: "nicht mehr vorhanden")
import homematic
from datetime import datetime as _dt
homematic.load_sensors = lambda: [{"id": "s1", "name": "Druckfortschritt", "unit": "%", "kind": "progress"}]
homematic.read_values = lambda sens, latch=False: {x["id"]: 42.0 for x in sens}
rules.add_rule(flow_body)
rc = webapp.ctrl._rules_ctx(cfg, None, _dt(2026, 11, 6, 15, 0))
assert rc.get("sensors") == {"s1": 42.0} and "s1" in rc["sensor_info"], rc.get("sensors")
assert rules.used_by("sensor", "s1") == ["Druckfortschritt"], rules.used_by("sensor", "s1")           # Loeschschutz zaehlt die Bedingung mit
print("ok")
