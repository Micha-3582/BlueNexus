import os, sys
from datetime import datetime, timedelta
root = sys.argv[1]
sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
import webapp, store, vrm
from logic import PersistentState

class FakeCerbo:
    def __init__(self, *a, **k): pass
    def read_soc(self): return 58.0
    def read_ess_mode(self): return 1
    def read_system(self, **k): return None
    def read_min_soc(self): return 20.0
    def read_alarms(self): return {"values": {}, "errors": {}}
    def read_soh(self): return None
    def write_ess_mode(self, m, dry_run=True): return False
webapp.Cerbo = FakeCerbo
now = datetime.now()
def prices(_):
    t = now.replace(minute=0, second=0, microsecond=0)
    return [{"startsAt": (t + timedelta(minutes=15 * i)).astimezone().isoformat(timespec="seconds"), "total": 0.30, "level": "NORMAL"} for i in range(-8, 150)]
webapp.fetch_tibber_prices = prices

cfg = {"cerbo_host": "x", "tibber_token": "x", "pv_latitude": 51.5, "pv_longitude": 6.5, "pv_planes": [], "dry_run": True,
       "openmeteo_pr": 0.6, "solar_source": "auto"}
store.load_config = lambda: dict(cfg)
store.is_configured = lambda c=None: True
store.load_state = lambda: PersistentState()
store.save_state = lambda s: None
store.log_charge_state = lambda *a, **k: None
store.active_ev = lambda n=None: None
store.solar_measured_today = lambda n=None: 9.0
store.recent_solar_average = lambda days=7, now=None: 15.0
rec = {}
store.record_vrm_forecast = lambda v, now=None: rec.update(vrm_kwh=v)
store.auto_adjust_pr = lambda n=None: None
store.auto_adjust_bucket_factors = lambda n=None: None
store.pv_forecast_range = lambda *a, **k: {"low": 1.0, "high": 2.0}

class OM:
    def get(self): return (30.0, 8.0)
    def get_remaining_today(self, now, bucket_factors=None): return 12.0
    def get_hourly_today(self): return {}
class FS:
    def get(self): return (25.0, 25.0)
ctrl = webapp.Controller()
ctrl._om_source = lambda c: OM(); ctrl._pv_source = lambda c: FS()
seen = {}
orig = webapp.decide
def spy(**k):
    seen.update(today=k["solar_today_raw"], tom=k["solar_tom_raw"]); return orig(**k)
webapp.decide = spy

def vf(**kw):
    d = {"configured": True, "error": None, "updated": (now - timedelta(minutes=10)).isoformat(timespec="seconds"),
         "remaining_today_kwh": 13.0, "today_kwh": 22.0, "tomorrow_kwh": 22.5,
         "hours": [{"day": "today", "hour": 12, "wh": 1}, {"day": "tomorrow", "hour": 12, "wh": 1}]}
    d.update(kw); return d

# 1) VRM aktiv: Regelung bekommt gemessen(9) + Rest(13) = 22 und morgen 22.5; Anzeige ohne Open-Meteo-Spanne
vrm.forecast = lambda force=False: vf()
ctrl.tick()
assert seen == {"today": 22.0, "tom": 22.5}, seen
st = ctrl.status
assert st["pv_source"] == "VRM" and st["pv_note"] is None, st
assert st["pv_today"] == 22.0 and st["pv_tom"] == 22.5
# Das Logbuch bekommt die VRM-Tagesprognose (die Open-Meteo-Gegenprobe gibt es nicht mehr)
assert rec["vrm_kwh"] == 22.0, rec

# 2) VRM faellt aus (alt) -> Durchschnitt der letzten Tage (15): heute max(gemessen 9, 15) = 15, morgen 15, Hinweis
vrm.forecast = lambda force=False: vf(updated=(now - timedelta(hours=5)).isoformat(timespec="seconds"), error="VRM nicht erreichbar")
ctrl.tick()
assert seen == {"today": 15.0, "tom": 15.0}, seen
st = ctrl.status
assert st["pv_source"] == "Ø letzte Tage" and st["pv_note"], st

# 3) Morgen fehlt im VRM -> heute VRM, morgen Durchschnitt der letzten Tage
vrm.forecast = lambda force=False: vf(hours=[{"day": "today", "hour": 12, "wh": 1}], tomorrow_kwh=0.0)
ctrl.tick(); assert seen == {"today": 22.0, "tom": 15.0} and "morgen" in ctrl.status["pv_note"], (seen, ctrl.status["pv_note"])

# 4) kein VRM eingerichtet -> Durchschnitt der letzten Tage mit Hinweis auf die Einstellung
vrm.forecast = lambda force=False: {"configured": False, "error": None, "hours": []}
ctrl.tick(); assert seen == {"today": 15.0, "tom": 15.0} and ctrl.status["pv_source"] == "Ø letzte Tage" and "VRM" in ctrl.status["pv_note"], (seen, ctrl.status["pv_note"])
print("TICK OK", root.split("/")[-1])
