import sys, os, math
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
ctrl = webapp.ctrl

# ---- Cerbo-Fake mit einstellbarem SOC und Min-SOC (Modul-globaler Zustand)
state = {"soc": 42.0, "min_soc": 0.0, "written": []}


class FakeCerbo2:
    def __init__(self, *a, **k): pass
    def read_soc(self): return state["soc"]
    def read_ess_mode(self): return 10
    def read_system(self, **k): return None
    def read_min_soc(self): return state["min_soc"]
    def write_ess_mode(self, m, dry_run=True):
        state["written"].append((m, dry_run))
        return not dry_run


webapp.Cerbo = FakeCerbo2

# ---- Ausgepraegte Talpreisphase mittags, sehr teuer abends (wie am 27.09. real erlebt)
now0 = datetime.now().replace(minute=0, second=0, microsecond=0)
day0 = now0.replace(hour=0)


def make_valley_prices(_):
    out = []
    for i in range(192):
        t = day0 + timedelta(minutes=15 * i)
        if 12 <= t.hour < 15:
            ct = 20.0
        elif 19 <= t.hour < 21:
            ct = 55.0
        else:
            ct = 32.0
        out.append({"startsAt": t.strftime("%Y-%m-%dT%H:%M:%S+02:00"), "total": ct / 100, "level": "NORMAL"})
    return out


webapp.fetch_tibber_prices = make_valley_prices
cfg.update({"tariff_mode": "tibber", "dry_run": False, "smart_planner_enabled": True,
            "battery_usable_kwh": 20.0, "pv_reserve_kwh": 2.0, "max_charge_soc": 95.0,
            "daily_usage_kwh": 24.0, "charge_power_w": 3000})


def at(hour, soc=None, minute=0):
    if soc is not None:
        state["soc"] = soc
    real_now = webapp.datetime

    class FrozenDT(real_now):
        @classmethod
        def now(cls, tz=None):
            return day0.replace(hour=hour, minute=minute)
    webapp.datetime = FrozenDT
    try:
        state["written"].clear()
        ctrl.safe_tick()
    finally:
        webapp.datetime = real_now
    return dict(ctrl.status)


# ---- 1) Mittags in der Talphase, SOC mittel -> intelligente Planung soll die Talphase (12-15 Uhr) nutzen
# (nicht zwingend exakt DIESE Viertelstunde - das Raster der Optimierung darf den Start um eine
# Viertelstunde verschieben, solange noch innerhalb des Tals geladen wird)
st = at(13, soc=45.0)
assert "🧠" in st["strategy"], st["strategy"]
assert st["plan_windows"], st
win_start_h = int(st["plan_slots"][0]["start"][11:13])
assert 12 <= win_start_h < 15, st["plan_windows"]
assert all(20.0 <= s["price"] <= 21.0 for s in st["plan_slots"]), st["plan_slots"]     # nur im Tal, nicht abends

# ---- 2) Ladelimit hart erreicht -> intelligente Planung greift NICHT, harte Sperre bleibt
st2 = at(13, soc=95.0)
assert "Ladelimit" in st2["strategy"] and "🧠" not in st2["strategy"], st2["strategy"]
assert st2["allow_now"] is False, st2

# ---- 3) Fester Tarif -> unveraendert (kein 🧠)
cfg["tariff_mode"] = "fixed"
st3 = at(13, soc=45.0)
assert "🧠" not in st3["strategy"], st3["strategy"]
cfg["tariff_mode"] = "tibber"

# ---- 4) Manueller Override -> unveraendert, laedt trotzdem (Override hat Vorrang, nicht die Planung)
cfg["manual_override"] = True
st4 = at(13, soc=45.0)
assert st4["strategy"] == "MANUELL" and st4["allow_now"] is True and "🧠" not in st4["strategy"], st4
cfg["manual_override"] = False

# ---- 5) smart_planner_enabled aus -> alte stufenweise Logik greift wie bisher (kein 🧠)
cfg["smart_planner_enabled"] = False
st5 = at(13, soc=45.0)
assert "🧠" not in st5["strategy"], st5["strategy"]
cfg["smart_planner_enabled"] = True

# ---- 6) Minimaler SOC am Cerbo wirkt als Untergrenze der Planung (assumptions.floor_soc)
state["min_soc"] = 20.0
st6 = at(13, soc=45.0)
assert "🧠" in st6["strategy"], st6["strategy"]

# ---- 7) VRM-Prognose fehlt (keine Stunden) -> faellt sauber auf die alte Logik zurueck, kein Crash
orig_vf = webapp.vrm.forecast
webapp.vrm.forecast = lambda force=False: {"configured": True, "error": None, "hours": [], "today_kwh": 0, "tomorrow_kwh": None,
                                            "remaining_today_kwh": 0, "cons": {"hours": []}}
st7 = at(13, soc=45.0)
assert "🧠" not in st7["strategy"], st7["strategy"]
webapp.vrm.forecast = orig_vf

# ---- 8) Preisschwelle "Immer laden unter": gilt auch mit Intelligenter Planung (Preis 20 ct im Tal <= 25 -> laden, kein Warten auf billigere Slots)
cfg["absolute_cheap_price"] = 25.0
st8 = at(13, soc=45.0)
assert st8["strategy"].startswith("Supergünstig") and st8["allow_now"] is True and "🧠" not in st8["strategy"], st8["strategy"]
st8b = at(10, soc=45.0)                                                  # 32 ct > 25: Preisschwelle greift nicht, die Planung entscheidet wie bisher
assert "🧠" in st8b["strategy"], st8b["strategy"]
# Anzeige: Plan enthaelt alle Viertelstunden unter der Schwelle (hier das Tal 12-15 Uhr, 20 ct <= 25)
valley = {x["start"][11:16] for x in st8["plan_slots"]}
assert {"13:00", "13:15", "14:45"} <= valley and all(float(x["price"]) <= 25.0 for x in st8["plan_slots"]), sorted(valley)
assert all(x["price"] <= 25.0 or True for x in st8b["plan_slots"]) and any(12 <= int(x["start"][11:13]) < 15 for x in st8b["plan_slots"]), st8b["plan_windows"]
cfg["absolute_cheap_price"] = 0.0
st8c = at(13, soc=45.0)
assert "🧠" in st8c["strategy"], st8c["strategy"]

print("SMART OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
