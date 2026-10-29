import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
root = sys.argv[1]
sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
import store

tmp = tempfile.mkdtemp()
store.HISTORY_PATH = os.path.join(tmp, "h.json")
store.MONTHLY_PATH = os.path.join(tmp, "m.json")
cfg = {"battery_usable_kwh": 20.0}
store.load_config = lambda: dict(cfg)

# Ein simulierter Tag: 10 kWh Solar->Akku, 5 kWh Netz->Akku (Laden=15), 12 kWh Akku->Verbrauch, 1 kWh Akku->Netz (Entladen=13)
hours = {}
for h in range(24):
    hours[f"2026-09-01T{h:02d}"] = {"solar": 1.0, "verbrauch": 1.0,
                                     "s_batt": 10.0/24, "g_batt": 5.0/24,
                                     "b_load": 12.0/24, "b_grid": 1.0/24,
                                     "s_grid": 0.0, "g_load": 0.0, "grid_cost_ct": 30.0}
store._dump_json(store.HISTORY_PATH, {"hours": hours, "last": None}, indent=2)

import datetime
now = datetime.datetime(2026, 9, 2, 12, 0)     # ein Tag spaeter -> 01.09. wird archiviert
store.archive_finished_days(now)

stats = store.battery_cycle_stats(now)
print(stats)
assert abs(stats["charge_kwh"] - 15.0) < 0.05, stats
assert abs(stats["discharge_kwh"] - 13.0) < 0.05, stats
assert abs(stats["equivalent_full_cycles"] - (15.0 + 13.0) / 2 / 20.0) < 0.05, stats
assert stats["since_month"] == "2026-09"

# ---- ohne battery_usable_kwh: cycles=None statt Exception
cfg["battery_usable_kwh"] = 0
stats2 = store.battery_cycle_stats(now)
assert stats2["equivalent_full_cycles"] is None, stats2

# ---- laufender (nicht archivierter) Monat wird live mitgezaehlt
cfg["battery_usable_kwh"] = 20.0
hours2 = dict(hours)
for h in range(24):
    hours2[f"2026-09-02T{h:02d}"] = {"solar": 0.0, "verbrauch": 0.0, "s_batt": 0.0, "g_batt": 4.0/24,
                                      "b_load": 4.0/24, "b_grid": 0.0, "s_grid": 0.0, "g_load": 0.0, "grid_cost_ct": 0.0}
store._dump_json(store.HISTORY_PATH, {"hours": hours2, "last": None}, indent=2)
stats3 = store.battery_cycle_stats(now)
assert abs(stats3["charge_kwh"] - 19.0) < 0.05, stats3       # 15 (archiviert) + 4 (laufend, noch nicht archiviert)
assert abs(stats3["discharge_kwh"] - 17.0) < 0.05, stats3

# ---- Mit VRM-Zugang: nutzt den vollen Verlauf seit Inbetriebnahme statt der eigenen (kuerzeren) Historie
import vrm
vrm.load_credentials = lambda: {"token": "t", "installation_id": "1"}
cfg["battery_install_date"] = "2025-09-06"


def fake_lifetime(now=None, start=None):
    assert start is not None and start.date().isoformat() == "2025-09-06", start
    return {"charge_kwh": 500.0, "discharge_kwh": 450.0, "since": "2025-09-06"}


vrm.battery_lifetime_kwh = fake_lifetime
stats4 = store.battery_cycle_stats(now)
print(stats4)
assert stats4["source"] == "vrm" and stats4["since_date"] == "2025-09-06"
assert abs(stats4["equivalent_full_cycles"] - (500.0 + 450.0) / 2 / 20.0) < 0.06, stats4

# ---- VRM meldet einen Fehler -> faellt sauber auf die eigene Historie zurueck, kein Absturz
vrm.battery_lifetime_kwh = lambda now=None, start=None: (_ for _ in ()).throw(RuntimeError("VRM down"))
stats5 = store.battery_cycle_stats(now)
assert stats5["source"] == "lokal", stats5

# ---- Jahres-Hochrechnung: 195.6 Zyklen in 386 Tagen -> ~185/Jahr; bei 6000 erwarteten Zyklen -> noch ~31 Jahre
vrm.battery_lifetime_kwh = fake_lifetime
cfg["battery_expected_cycles"] = 6000
stats6 = store.battery_cycle_stats(now)
assert stats6["source"] == "vrm"
days_since = (now.date() - datetime.date(2025, 9, 6)).days
per_year_expected = (500.0 + 450.0) / 2 / 20.0 / days_since * 365.25
assert abs(stats6["cycles_per_year"] - per_year_expected) < 0.1, stats6
years_expected = (6000 - stats6["equivalent_full_cycles"]) / stats6["cycles_per_year"]
assert abs(stats6["years_remaining"] - years_expected) < 0.5, stats6

# ---- Ohne erwartete Zyklenzahl (0/nicht eingetragen): keine Hochrechnung, aber kein Fehler
cfg["battery_expected_cycles"] = 0
stats7 = store.battery_cycle_stats(now)
assert stats7["years_remaining"] is None and stats7["cycles_per_year"] is None, stats7

print("CYCLES OK", root.split("/")[-1])
