"""Sicherheitspuffer der Intelligenten Planung (params.smart_planner_safety_buffer_pct): die Planung rechnet
nachts mit soc_floor_pct + Puffer als Untergrenze, OHNE dass sich der echte Cerbo-Minimalwert aendert
(Max, 29.09.2026: "min soc 15% eingestellt, Software soll trotzdem mit 20% rechnen").

Testet ueber webapp.planner.run() direkt (deterministisch, ohne den DP-Optimierer selbst neu zu testen -
der ist schon in t_smart.py/t_planner.py abgedeckt), indem der tatsaechlich uebergebene floor_soc-Wert
abgefangen wird."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from logic import Params, PersistentState
from datetime import datetime, timedelta

ctrl = webapp.ctrl
captured = {}
_orig_run = webapp.planner.run


def spy_run(now, soc, params, slots, solar, cons, existing, floor_soc=None):
    captured["floor_soc"] = floor_soc
    return _orig_run(now, soc, params, slots, solar, cons, existing, floor_soc=floor_soc)


webapp.planner.run = spy_run

now0 = datetime(2026, 9, 29, 5, 0)
vrm_data = {"hours": [{"day": "today", "hour": h, "wh": 500.0} for h in range(24)]}
prices = [{"startsAt": (now0 + timedelta(minutes=15 * i)).astimezone().isoformat(timespec="seconds"), "total": 0.30}
          for i in range(48)]

# ---- Cerbo-Minimalwert 15%, Puffer 0% (Standard vor der Umstellung) -> Planung rechnet mit genau 15%
cfg.update({"tariff_mode": "tibber", "smart_planner_enabled": True, "battery_usable_kwh": 20.0,
            "pv_reserve_kwh": 2.0, "max_charge_soc": 95.0, "daily_usage_kwh": 24.0, "charge_power_w": 3000})
params = Params.from_config(cfg)
params.soc_floor_pct = 15.0
params.smart_planner_safety_buffer_pct = 0.0
state = PersistentState()
ctrl._smart_decision(now0, 40.0, prices, vrm_data, params, state)
assert captured["floor_soc"] == 15.0, captured
print("Puffer 0% -> Planung rechnet mit dem echten Minimalwert (15%) OK")

# ---- Gleicher Cerbo-Minimalwert (15%), jetzt mit 5%-Puffer -> Planung rechnet mit 20%
params2 = Params.from_config(cfg)
params2.soc_floor_pct = 15.0
params2.smart_planner_safety_buffer_pct = 5.0
ctrl._smart_decision(now0, 40.0, prices, vrm_data, params2, PersistentState())
assert captured["floor_soc"] == 20.0, captured
print("Puffer 5% -> Planung rechnet mit 20% (15% + 5%), echter Minimalwert unveraendert OK")

# ---- Sicherheitsnetz: gepufferter Floor darf nie das Ladelimit erreichen/ueberschreiten (sonst waere
# rechnerisch gar kein Ladefenster mehr moeglich) - hier absichtlich ein viel zu hoher Puffer
params3 = Params.from_config(cfg)
params3.soc_floor_pct = 90.0
params3.smart_planner_safety_buffer_pct = 20.0   # 90 + 20 = 110%, unsinnig
params3.max_charge_soc = 95.0
ctrl._smart_decision(now0, 92.0, prices, vrm_data, params3, PersistentState())
assert captured["floor_soc"] < params3.max_charge_soc, captured
print("Extremer Puffer wird auf sinnvollen Bereich gedeckelt (< Ladelimit) OK")

# ---- Der ECHTE soc_floor_pct (fuer die harte Ladesperre/Standard-Logik anderswo) bleibt in allen Faellen
# unveraendert bei 15% - nur die Planung selbst bekommt den erhoehten Wert uebergeben
assert params2.soc_floor_pct == 15.0, "der echte Cerbo-Minimalwert darf durch den Puffer nicht veraendert werden!"
print("Echter soc_floor_pct bleibt unveraendert (nur die Planung selbst rechnet vorsichtiger) OK")

print("SMART BUFFER OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
