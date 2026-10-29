import os, sys, tempfile, math
from datetime import datetime, timedelta
def setup(root):
    sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
    import webapp, store, vrm, price_cache
    from logic import PersistentState
    tmp = tempfile.mkdtemp()
    price_cache.PATH = os.path.join(tmp, "pc.json"); store.PLANSIM_LOG_PATH = os.path.join(tmp, "ps.json")
    # Alle Verlaufs-/Statistikdateien in den Testordner umleiten - sonst schreiben Tests versehentlich
    # ins echte app/-Verzeichnis (history.json, das neue history_archive/, monthly_summary.json, ...).
    store.HISTORY_PATH = os.path.join(tmp, "history.json")
    store.HISTORY_ARCHIVE_DIR = os.path.join(tmp, "history_archive")
    store.MONTHLY_PATH = os.path.join(tmp, "monthly_summary.json")
    store.SAVINGS_PATH = os.path.join(tmp, "savings_days.json")
    store.SOLAR_LOG_PATH = os.path.join(tmp, "solar_log.json")
    store.PRICE_HISTORY_PATH = os.path.join(tmp, "price_history.json")
    store._price_cache = None
    store.CONTRACT_PERIODS_PATH = os.path.join(tmp, "contract_periods.json")
    store.STATE_PATH = os.path.join(tmp, "state.json")
    import devicelog, opslog
    devicelog.PATH = os.path.join(tmp, "devicelog.jsonl")
    opslog.EVENTS_PATH = os.path.join(tmp, "events.jsonl")
    import shelly, homematic, tuya
    shelly.DEVICES_PATH = os.path.join(tmp, "shelly_devices.json")
    homematic.CREDENTIALS_PATH = os.path.join(tmp, "homematic.json")
    homematic.SENSORS_PATH = os.path.join(tmp, "homematic_sensors.json")
    import rules as _rules
    _rules.RULES_PATH = os.path.join(tmp, "rules.json")
    _rules.STATE_PATH = os.path.join(tmp, "rules_state.json")
    homematic.SETPOINTS_PATH = os.path.join(tmp, "homematic_setpoints.json")
    homematic.LOCKS_PATH = os.path.join(tmp, "homematic_locks.json")
    import wol as _wol
    _wol.WOL_PATH = os.path.join(tmp, "wol.json")
    import zigbee as _zigbee
    _zigbee.CREDENTIALS_PATH = os.path.join(tmp, "zigbee.json")
    import flows as _flows, virtual as _virtual
    _flows.STATE_PATH = os.path.join(tmp, "flows_state.json")
    _virtual.VIRTUAL_PATH = os.path.join(tmp, "virtual.json")
    tuya.CREDENTIALS_PATH = os.path.join(tmp, "tuya_cloud.json")
    store.BACKUP_DIR = os.path.join(tmp, "backups")
    class FakeCerbo:
        def __init__(self, *a, **k): pass
        def read_soc(self): return 42.0
        def read_ess_mode(self): return 10
        def read_system(self): return None
        def write_ess_mode(self, m, dry_run=True): return False
    webapp.Cerbo = FakeCerbo
    now = datetime.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    def prices(_):
        out = []
        for i in range(192):
            t = day0 + timedelta(minutes=15 * i)
            ct = 21 if t.hour < 6 else (46 if 17 <= t.hour < 21 else 31)
            out.append({"startsAt": t.strftime("%Y-%m-%dT%H:%M:%S+02:00"), "total": ct / 100, "level": "NORMAL"})
        return out
    webapp.fetch_tibber_prices = prices
    cfg = {"cerbo_host": "x", "tibber_token": "x", "dry_run": True}
    store.load_config = lambda: dict(cfg)
    store.is_configured = lambda c=None: True
    store.save_config = lambda c: (cfg.clear(), cfg.update(c))      # nie die echte config.json anfassen
    store.load_state = lambda: PersistentState()
    store.save_state = lambda s: None
    store.log_charge_state = lambda *a, **k: None
    store.active_ev = lambda n=None: None
    store.solar_measured_today = lambda n=None: 3.0
    store.record_vrm_forecast = lambda v, n=None: None
    store.recent_solar_average = lambda days=7, now=None: 15.0
    def hours(kind):
        rows = []
        for dname in ("today", "tomorrow"):
            for h in range(24):
                if kind == "solar": wh = max(0.0, (900 if os.environ.get("PS_WEAK") else 3000) * math.sin(math.pi * (h - 6.5) / 13)) if 7 <= h <= 19 else 0.0
                else: wh = 900 + (700 if h in (7, 8, 18, 19, 20) else 0)
                rows.append({"day": dname, "hour": h, "wh": round(wh, 1), "ts": 0})
        return rows
    def vf(force=False):
        return {"configured": True, "error": None, "updated": now.isoformat(timespec="seconds"), "hours": hours("solar"),
                "today_kwh": 22.0, "tomorrow_kwh": 23.0, "remaining_today_kwh": 15.0,
                "cons": {"hours": hours("cons"), "today_kwh": 21.0, "tomorrow_kwh": 21.0, "remaining_today_kwh": 14.0}}
    vrm.forecast = vf
    return webapp, store, cfg, tmp
