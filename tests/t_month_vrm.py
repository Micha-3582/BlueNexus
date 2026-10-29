import sys, os, tempfile, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
root = sys.argv[1]
sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
import store, vrm

tmp = tempfile.mkdtemp()
store.HISTORY_PATH = os.path.join(tmp, "h.json")
store.MONTHLY_PATH = os.path.join(tmp, "m.json")
cfg = {}
store.load_config = lambda: dict(cfg)
vrm.load_credentials = lambda: {"token": "t", "installation_id": "1"}

# ---- lokale Historie kennt nur September 2026 (wie bei Max); Jan-Aug fehlen komplett
now = datetime.datetime(2026, 9, 15, 12, 0)
hours = {f"2026-09-01T{h:02d}": {"solar": 1.0, "verbrauch": 1.0, "g_load": 0.1, "g_batt": 0.0,
                                 "s_grid": 0.0, "b_grid": 0.0, "grid_cost_ct": 10.0} for h in range(24)}
store._dump_json(store.HISTORY_PATH, {"hours": hours, "last": None}, indent=2)


def fake_monthly(start, end):
    assert start == datetime.datetime(2026, 1, 1), start
    assert end == datetime.datetime(2026, 9, 1), end
    return {
        "2026-01": {"solar": 50.0, "verbrauch": 300.0, "import": 260.0, "export": 5.0},
        "2026-03": {"solar": 200.0, "verbrauch": 280.0, "import": 90.0, "export": 15.0},
        "2026-09": {"solar": 999.0, "verbrauch": 999.0, "import": 999.0, "export": 999.0},   # ausserhalb -> muss ignoriert werden
    }


vrm.monthly_energy_totals = fake_monthly
res = store.monthly_overview(now)
by_month = {m["month"]: m for m in res["months"]}
assert "2026-01" in by_month and "2026-03" in by_month, by_month.keys()
assert by_month["2026-01"]["solar"] == 50.0 and by_month["2026-01"]["vrm_only"] is True
assert by_month["2026-01"]["cost_eur"] == 0.0 and by_month["2026-01"]["cost_known"] is False
assert "2026-02" not in by_month                    # VRM hatte fuer Februar keine Daten -> bleibt einfach aus
assert by_month["2026-09"]["solar"] != 999.0 and by_month["2026-09"]["vrm_only"] is False    # echte lokale Daten haben Vorrang

# ---- ohne VRM-Zugang: keine zusaetzlichen Monate, kein Fehler (echte Funktion, nur load_credentials leer)
import importlib
importlib.reload(vrm)                    # nimmt den Monkeypatch von monthly_energy_totals oben zurueck
vrm.load_credentials = lambda: {}
res2 = store.monthly_overview(now)
assert not any(m.get("vrm_only") for m in res2["months"])

# ---- VRM-Fehler beim Auffuellen: sauberer Rueckfall, kein Absturz
vrm.load_credentials = lambda: {"token": "t", "installation_id": "1"}
vrm.monthly_energy_totals = lambda start, end: (_ for _ in ()).throw(RuntimeError("VRM down"))
res3 = store.monthly_overview(now)
assert not any(m.get("vrm_only") for m in res3["months"])

# ---- fester Tarif (wie Anna): Kosten der nachgeholten Monate sind kein Geheimnis - werden berechnet
vrm.load_credentials = lambda: {"token": "t", "installation_id": "1"}
cfg["tariff_mode"] = "fixed"; cfg["fixed_price_ct"] = 30.0
vrm.monthly_energy_totals = fake_monthly
res4 = store.monthly_overview(now)
jan = next(m for m in res4["months"] if m["month"] == "2026-01")
assert jan["vrm_only"] is True and jan["cost_known"] is True, jan
assert abs(jan["cost_eur"] - 260.0 * 30.0 / 100.0) < 0.01, jan       # Netzbezug x fester Preis

print("MONTH VRM OK", root.split("/")[-1])
