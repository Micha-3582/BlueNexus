"""Prueft das Commitment der Intelligenten Planung (webapp._smart_decision / state.smart_commit_slot):
einmal INNERHALB einer Viertelstunde "jetzt laden" beschlossen, bleibt es dabei bis zum Slot-Ende, auch
wenn ein spaeterer Tick in DERSELBEN Viertelstunde (z.B. weil der reale SOC inzwischen ueber die
Ladegrenze gestiegen ist) auf "wartet" umschwenken wuerde. Reproduziert gezielt den von Max am
28.09.2026 beobachteten Effekt (Kurzfenster von 1-3 Minuten statt durchgehend 15 Minuten).

Testet _smart_decision() DIREKT (nicht ueber den vollen Tick-Stack) und ersetzt planner.run() durch ein
einfaches, deterministisches Fake (SOC < 90% -> laden, sonst nicht) - so wird gezielt NUR der
Commitment-Wrapper geprueft, unabhaengig vom komplexen DP-Optimierer in planner.py (der bei
gleich-teuren Slots aus gutem Grund eigene Zeitpunkt-Praeferenzen hat, siehe t_smart.py fuer dessen
eigene Tests)."""
import sys, os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from logic import Params, PersistentState

ctrl = webapp.ctrl
cfg.update({"tariff_mode": "tibber", "smart_planner_enabled": True,
            "battery_usable_kwh": 20.0, "pv_reserve_kwh": 2.0, "max_charge_soc": 98.0,
            "daily_usage_kwh": 24.0, "charge_power_w": 3000})
params = Params.from_config(cfg)

now0 = datetime(2026, 9, 28, 12, 0)
vrm_data = {"hours": [{"day": "today", "hour": h, "wh": 0.0} for h in range(24)]}
prices = [{"startsAt": (now0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%S+02:00"), "total": 0.30}
          for i in range(96)]


def fake_run(now, soc, params, slots, solar, cons, existing, floor_soc=None):
    """Deterministisches Fake: laedt, wenn SOC < 90%, sonst nicht - immer GENAU im ersten Slot."""
    charge = 1 if soc < 90.0 else 0
    return {"times": [s.start.isoformat(timespec="minutes") for s in slots],
            "prices": [s.price for s in slots],
            "sim": {"charge_kwh": [charge] + [0] * (len(slots) - 1)}}


webapp.planner.run = fake_run

state = PersistentState()

# ---- Tick 1 (12:00, Slot-Anfang): SOC 60% -> Fake liefert "laden"
r1 = ctrl._smart_decision(now0, 60.0, prices, vrm_data, params, state)
assert r1 is not None and r1[0] is True, r1
assert state.smart_commit_slot == now0.isoformat(timespec="minutes"), state.smart_commit_slot
print("Tick 12:00 SOC 60% -> laedt, committed:", state.smart_commit_slot)

# ---- Tick 2 (12:05, GLEICHE Viertelstunde): SOC jetzt 91% -> Fake wuerde JETZT "nicht laden" liefern.
# OHNE Commitment wuerde hier auf "wartet" umgeschaltet (das ist der beobachtete Kurzfenster-Bug).
# MIT Commitment muss weiter geladen werden, bis der Slot (12:15) vorbei ist.
now2 = now0 + timedelta(minutes=5)
r2 = ctrl._smart_decision(now2, 91.0, prices, vrm_data, params, state)
assert r2 is not None and r2[0] is True, f"Commitment griff nicht: {r2}"
print("Tick 12:05 SOC 91% (im selben Slot, Fake sagt eigentlich 'nicht laden') -> haelt Commitment:", r2[2])

# ---- Tick 3 (12:10, GLEICHE Viertelstunde): SOC 92% -> Commitment muss weiterhin halten
now3 = now0 + timedelta(minutes=10)
r3 = ctrl._smart_decision(now3, 92.0, prices, vrm_data, params, state)
assert r3 is not None and r3[0] is True, f"Commitment verlor sich vorzeitig: {r3}"
print("Tick 12:10 SOC 92% (im selben Slot) -> haelt Commitment:", r3[2])

# ---- Tick 4 (12:15, NEUE Viertelstunde): SOC weiterhin 92% -> Fake liefert "nicht laden", und diesmal
# OHNE Commitment aus dem alten Slot (der ist vorbei) - muss jetzt sauber stoppen.
now4 = now0 + timedelta(minutes=15)
r4 = ctrl._smart_decision(now4, 92.0, prices, vrm_data, params, state)
assert r4 is not None and r4[0] is False, f"Commitment haette NICHT in den naechsten Slot uebernommen werden duerfen: {r4}"
assert state.smart_commit_slot == "", state.smart_commit_slot
print("Tick 12:15 SOC 92% (neuer Slot) -> laedt nicht mehr, Commitment zurueckgesetzt:", r4[2])

# ---- Tick 5 (12:30, neuer Slot): SOC wieder 60% -> laedt neu, committed fuer 12:30-12:45
now5 = now0 + timedelta(minutes=30)
r5 = ctrl._smart_decision(now5, 60.0, prices, vrm_data, params, state)
assert r5 is not None and r5[0] is True, r5
assert state.smart_commit_slot == now5.isoformat(timespec="minutes")
print("Tick 12:30 SOC 60% -> laedt neu, committed:", state.smart_commit_slot)

# ---- Tick 6 (12:35, GLEICHE Viertelstunde wie Tick 5): Grenzfall exakt an der Schwelle (SOC 89.9999%,
# also aus Sicht des Fakes noch "laden") - Commitment darf hier natuerlich auch einfach gleichbleiben
now6 = now0 + timedelta(minutes=35)
r6 = ctrl._smart_decision(now6, 89.9, prices, vrm_data, params, state)
assert r6[0] is True and state.smart_commit_slot == now5.isoformat(timespec="minutes")
print("Tick 12:35 SOC 89.9% (im selben Slot) -> laedt weiterhin, Commitment unveraendert:", r6[2])

print("SMART COMMIT OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
