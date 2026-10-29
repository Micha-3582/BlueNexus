import os, sys, re, json, subprocess, importlib
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
root = sys.argv[1]
webapp, store, cfg, tmp = ps_common.setup(root)
stubs = {n: getattr(store, n) for n in ("load_config", "is_configured", "save_config", "load_state", "save_state", "log_charge_state", "active_ev", "solar_measured_today", "recent_solar_average")}
store = importlib.reload(store)                       # echte solar_log/record-Funktionen
for n, f in stubs.items(): setattr(store, n, f)          # Test-Konfiguration weiter benutzen (nie die echte config.json)
webapp.store = store
store.HISTORY_PATH = os.path.join(tmp, "h.json"); store.SOLAR_LOG_PATH = os.path.join(tmp, "sl.json")
store.SAVINGS_PATH = os.path.join(tmp, "sv.json"); store.PRICE_HISTORY_PATH = os.path.join(tmp, "ph.json"); store._price_cache = None
store.BACKUP_DIR = os.path.join(tmp, "bk"); store.MONTHLY_PATH = os.path.join(tmp, "m.json")
store.FORECAST_HOURS_PATH = os.path.join(tmp, "fh.json")

now = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
yest = (now - timedelta(days=1)).date().isoformat(); today = now.date().isoformat()

def bucket(v, imp):
    return {"verbrauch": v, "solar": 0.0, "soc_min": 50, "soc_max": 50, "soc_sum": 0, "soc_n": 0, "grid_cost_ct": 0.0,
            "s_load": 0, "s_batt": 0, "s_grid": 0, "b_load": 0, "b_grid": 0, "g_load": imp, "g_batt": 0.0}
hours = {}
prices = [20.0 if i < 48 else 40.0 for i in range(96)]           # erste Tageshaelfte 20 ct, zweite 40 ct
for day in (yest, today):
    for i in range(96 if day == yest else 60):
        hours[f"{day}T{i // 4:02d}:{(i % 4) * 15:02d}"] = bucket(0.5, 0.5 if i < 48 else 0.0)   # Verbrauch 0,5 kWh/Slot; Netzbezug nur in der billigen Haelfte
json.dump({"hours": hours, "last": None}, open(store.HISTORY_PATH, "w"))
json.dump({"days": {yest: {"p": prices, "src": "tibber"}, today: {"p": prices, "src": "tibber"}}}, open(store.PRICE_HISTORY_PATH, "w"))

sv = store.savings({"tariff_mode": "tibber"}, now)
assert sv["available"] and sv["mode"] == "tibber", sv
y = [r for r in sv["days"] if r["date"] == yest][0]
# Gestern: ohne Anlage = 48*0,5*20 + 48*0,5*40 = 480+960 = 1440 ct; bezahlt = 48*0,5*20 = 480 ct; Ersparnis 960 ct
assert abs(y["without_ct"] - 1440) < 0.5 and abs(y["cost_ct"] - 480) < 0.5 and abs(y["saving_ct"] - 960) < 0.5, y
# Preis-Timing: Bezug 24 kWh * Tagesdurchschnitt 30 ct - 480 = 240 ct; Rest = Eigenversorgung 720
assert abs(y["timing_ct"] - 240) < 0.5 and abs(y["self_ct"] - 720) < 0.5 and abs(y["avg_price"] - 30) < 0.01, y
assert sv["days"][0]["date"] == today and "today" in sv["totals"] and sv["totals"]["today"] is not None       # heute laeuft mit
saved = json.load(open(store.SAVINGS_PATH))["days"]; assert yest in saved and today not in saved             # nur abgeschlossene Tage gespeichert
# Einfrieren: Preise/Verlauf aendern sich, gespeicherter Tag bleibt
store._price_cache = None; json.dump({"days": {}}, open(store.PRICE_HISTORY_PATH, "w")); store._price_cache = None
sv2 = store.savings({"tariff_mode": "tibber"}, now); assert [r for r in sv2["days"] if r["date"] == yest][0]["saving_ct"] == y["saving_ct"]
assert sv2["totals"]["all"]["days"] >= 1 and sv2["totals"]["d7"]["saving_eur"] >= 9.5
# Fester Tarif: 30 ct konstant -> Ersparnis = (Verbrauch - Bezug) * 30; Timing 0
os.remove(store.SAVINGS_PATH)
svf = store.savings({"tariff_mode": "fixed", "fixed_price_ct": 30.0}, now)
yf = [r for r in svf["days"] if r["date"] == yest][0]
assert abs(yf["saving_ct"] - (48 * 0.5 + 0) * 30 * 1 - 0) < 0.6 and abs(yf["timing_ct"]) < 0.5 and yf["mode"] == "fixed", yf   # Verbrauch 48 kWh, Bezug 24 kWh -> 24 kWh * 30 = 720
assert abs(yf["saving_ct"] - 720) < 0.6, yf
assert store.savings({"tariff_mode": "fixed", "fixed_price_ct": 0}, now)["available"] is False
# Tag ohne Preise -> keine Auswertung
os.remove(store.SAVINGS_PATH); store._price_cache = None
assert store.savings({"tariff_mode": "tibber"}, now)["available"] is False

# ---- Kalibrierung
days = {}
for k in range(1, 8):
    d = (now - timedelta(days=k)).date().isoformat()
    days[d] = {"vrm_forecast": 20.0, "vrm_deviation_pct": -20, "actual": 16.0, "curtailed": False}
json.dump({"days": days}, open(store.SOLAR_LOG_PATH, "w"))
c = store.pv_calibration(now); assert c["ready"] and c["factor"] == 0.8 and c["days"] == 7 and c["avg_dev_pct"] == -20, c
# volle Akkus mit Ertrag unter Prognose zaehlen nicht
for d in list(days)[:3]: days[d]["curtailed"] = True
json.dump({"days": days}, open(store.SOLAR_LOG_PATH, "w")); c = store.pv_calibration(now); assert c["days"] == 4 and not c["ready"], c
for d in list(days)[:3]: days[d].update(curtailed=False, actual=30.0, vrm_forecast=20.0)      # ueber Prognose -> Faktor begrenzt auf 1,1
json.dump({"days": days}, open(store.SOLAR_LOG_PATH, "w")); c = store.pv_calibration(now); assert c["ready"] and 0.6 <= c["factor"] <= 1.1, c

# ---- Anwendung in der Steuerung
store.pv_calibration = lambda now=None: {"ready": True, "factor": 0.8, "days": 7, "min_days": 5, "avg_dev_pct": -20}
cfg["pv_auto_calibration"] = False; webapp.ctrl.safe_tick(); off = webapp.ctrl.status["pv_tom"]
cfg["pv_auto_calibration"] = True; webapp.ctrl.safe_tick(); st = webapp.ctrl.status
assert abs(st["pv_tom"] - off * 0.8) < 0.05 and "gesenkt" in (st.get("pv_note") or "") and webapp.ctrl.pv_cal == 0.8, (off, st["pv_tom"], st.get("pv_note"))
# ---- Endpunkte + Seiten + Bericht
class U:
    def get(self, n): return {"username": "t", "permissions": dict(__import__("auth").PRESETS["admin"])}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U(); cl = webapp.app.test_client()
with cl.session_transaction() as s: s["user"] = "t"
assert cl.get("/api/pv-calibration").get_json()["enabled"] is True
assert "available" in cl.get("/api/savings").get_json()
assert cl.get("/api/status").get_json()["ui"]["show_savings_card"] is True
for path in ("/", "/admin"):
    h = cl.get(path).get_data(as_text=True)
    open(os.path.join(tmp, "x.js"), "w", encoding="utf-8").write("\n".join(re.findall(r"<script>(.*?)</script>", h, re.S)))
    assert subprocess.run(["node", "--check", os.path.join(tmp, "x.js")], capture_output=True, text=True).returncode == 0, path
assert 'id="savings-card"' in cl.get("/").get_data(as_text=True) and "pv_auto_calibration" in cl.get("/admin").get_data(as_text=True)
import report; importlib.reload(report)
store.SAVINGS_PATH = os.path.join(tmp, "sv2.json"); store._price_cache = None
json.dump({"days": {yest: {"p": prices, "src": "tibber"}, today: {"p": prices, "src": "tibber"}}}, open(store.PRICE_HISTORY_PATH, "w"))
report.store = store
md = report.to_markdown(report.build(days=3, ctrl=webapp._ctrl_info()))
assert "Ersparnis ggü." in md and "PV-Kalibrierung: Faktor 0.80" in md and "ANGEWENDET" in md, md[md.find("## Jetzt"):][:900]
print("SAVINGS OK", root.split("/")[-1])
