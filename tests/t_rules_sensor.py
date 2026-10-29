"""Sensor-Bedingung im echten RuleEngine.step(): WENN Sensor TRUE / FALSE / unter-ueber -> Geraet schalten."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules
from datetime import datetime

NOW = datetime(2026, 10, 2, 12, 0)
FENSTER = {"id": "hmS-F", "name": "Fenster Bad", "kind": "contact", "binary": True, "unit": ""}
TEMP = {"id": "hmS-T", "name": "Wohnzimmer Temperatur", "kind": "temperature", "binary": False, "unit": "°C"}
DEV = {"id": "hm-X", "name": "Lüfter", "online": True, "on": False, "switchable": True, "min_on_min": 0, "min_off_min": 0}
CFG = {"rules_enabled": True, "rules_dry_run": False}


def run(rule_on, rule_off, sensors, dev_on=False, owned=False):
    """Ein frischer Engine-Durchlauf; liefert die Liste der Schaltaktionen."""
    eng = rules.RuleEngine()
    if owned:
        eng.set_owner("hm-X", "rule", "r1")        # Regel hat das Geraet selbst eingeschaltet -> darf es auch ausschalten
    rule = rules.normalize_rule({"device_id": "hm-X", "on": rule_on, "off": rule_off}, "r1")
    ctx = {"now": NOW, "soc": 50, "sensors": sensors, "sensor_info": {FENSTER["id"]: FENSTER, TEMP["id"]: TEMP}}
    dev = dict(DEV, on=dev_on)
    return [(a[0], a[2]) for a in eng.step(NOW, ctx, CFG, [dev], [rule]) if a[0] in ("on", "off")]   # "adopt" = nur Logbuch


# WENN Fenster TRUE (offen) -> einschalten
acts = run([{"type": "sensor", "sensor_id": "hmS-F", "is": True}], [], {"hmS-F": True})
assert [a[0] for a in acts] == ["on"], acts
assert "TRUE" in acts[0][1], acts
print("Fenster TRUE (offen) -> Geraet geht an:", acts[0][1])

# Fenster zu (False) -> bleibt aus
assert run([{"type": "sensor", "sensor_id": "hmS-F", "is": True}], [], {"hmS-F": False}) == []
print("Fenster zu, Bedingung TRUE -> nichts passiert OK")

# WENN Fenster FALSE (zu) -> einschalten
acts = run([{"type": "sensor", "sensor_id": "hmS-F", "is": False}], [], {"hmS-F": False})
assert [a[0] for a in acts] == ["on"] and "FALSE" in acts[0][1], acts
print("Fenster FALSE (zu) -> Geraet geht an:", acts[0][1])

# Sensor ohne Wert (offline): weder TRUE noch FALSE schaltet
assert run([{"type": "sensor", "sensor_id": "hmS-F", "is": True}], [], {"hmS-F": None}) == []
assert run([{"type": "sensor", "sensor_id": "hmS-F", "is": False}], [], {"hmS-F": None}) == []
print("Sensor ohne Wert -> TRUE und FALSE schalten beide NICHT OK")

# Ausschalten, sobald Sensor TRUE (z. B. Fenster geht auf): laufendes Geraet wird abgeschaltet
acts = run([{"type": "time", "from": "00:00", "to": "24:00", "days": []}], [{"type": "sensor", "sensor_id": "hmS-F", "is": True}],
           {"hmS-F": True}, dev_on=True)
assert [a[0] for a in acts] == ["off"], acts
print("Ausschalten bei Sensor TRUE (Fenster auf):", acts[0][1])

# Messwert: Heizluefter an, wenn unter 19 C; aus, sobald ueber 21 C
assert [a[0] for a in run([{"type": "sensor", "sensor_id": "hmS-T", "op": "below", "value": 19}], [], {"hmS-T": 18.2})] == ["on"]
assert run([{"type": "sensor", "sensor_id": "hmS-T", "op": "below", "value": 19}], [], {"hmS-T": 19.5}) == []
acts = run([{"type": "sensor", "sensor_id": "hmS-T", "op": "below", "value": 19}], [{"type": "sensor", "sensor_id": "hmS-T", "op": "above", "value": 21}],
           {"hmS-T": 21.3}, dev_on=True, owned=True)
assert [a[0] for a in acts] == ["off"], acts
print("Messwert: unter 19 -> an, ueber 21 -> aus OK")

print("RULES SENSOR OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
