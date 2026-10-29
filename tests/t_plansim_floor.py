"""Die Ladeplan-Simulation (_run_plansim) muss denselben gepufferten Floor benutzen wie die Live-Steuerung
(_smart_decision), nicht mehr den ungenutzten night_safety_soc-Default (30%) - siehe webapp._buffered_floor().
Max, 29.09.2026: Simulation zeigte eine bei genau 30% schnurgerade SOC-Linie, obwohl der echte Minimalwert
(soc_floor_pct=15%) + Sicherheitspuffer (5%) nur 20% ergeben."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from logic import Params, decide, PersistentState
from datetime import datetime, timedelta

ctrl = webapp.ctrl

# ---- webapp.planner.run abfangen, um den tatsaechlich uebergebenen floor_soc zu sehen (wie t_smart_buffer.py)
captured = {}
_orig_run = webapp.planner.run


def spy_run(now, soc, params, slots, solar, cons, existing, floor_soc=None):
    captured["floor_soc"] = floor_soc
    return _orig_run(now, soc, params, slots, solar, cons, existing, floor_soc=floor_soc)


webapp.planner.run = spy_run

now0 = datetime(2026, 9, 29, 20, 0)          # abends, keine Sonne mehr -> Floor wird im Verlauf der Nacht relevant
vrm_data = {"hours": [{"day": "today", "hour": h, "wh": 0.0} for h in range(24)]
            + [{"day": "tomorrow", "hour": h, "wh": 500.0} for h in range(24)]}
prices = [{"startsAt": (now0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%S+02:00"), "total": 0.30}
          for i in range(96)]
cfg.update({"tariff_mode": "tibber", "smart_planner_enabled": True, "battery_usable_kwh": 20.0,
            "pv_reserve_kwh": 2.0, "max_charge_soc": 95.0, "daily_usage_kwh": 24.0, "charge_power_w": 3000})
params = Params.from_config(cfg)
params.soc_floor_pct = 15.0
params.smart_planner_safety_buffer_pct = 5.0

state = PersistentState()
d = decide(soc=40.0, price_entries=prices, solar_today_raw=0.0, solar_tom_raw=20.0, state=state, now=now0,
           manual_override=False, force_reason=None, params=params)

res = ctrl._run_plansim(now0, 40.0, prices, d, vrm_data, params, manual=False)
assert res["available"], res
floor_used = res["result"]["assumptions"]["floor_soc"]
assert floor_used == 20.0, f"Simulation haette mit 15%+5%=20% rechnen sollen, rechnete aber mit {floor_used}"
assert captured["floor_soc"] == 20.0, captured
print("Ladeplan-Simulation nutzt jetzt den gepufferten Floor (20%) statt night_safety_soc (30%) OK:", floor_used)

# ---- Gegenprobe: ohne den Fix (Puffer 0, gleicher Minimalwert wie soc_floor_pct) muesste die Simulation exakt
# mit 15% rechnen, NICHT mit 30% (night_safety_soc) - stellt sicher, dass wirklich der neue Pfad greift
params2 = Params.from_config(cfg)
params2.soc_floor_pct = 15.0
params2.smart_planner_safety_buffer_pct = 0.0
res2 = ctrl._run_plansim(now0, 40.0, prices, d, vrm_data, params2, manual=False)
assert res2["result"]["assumptions"]["floor_soc"] == 15.0, res2["result"]["assumptions"]
print("Puffer 0% -> Simulation rechnet exakt mit dem echten Minimalwert (15%), nicht mit night_safety_soc (30%) OK")

print("PLANSIM FLOOR OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
