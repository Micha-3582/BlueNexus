import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from datetime import datetime, timedelta
webapp.opslog.log = lambda *a, **k: None
sent = []
webapp.notify.push = lambda key, text, *a, **k: sent.append((key, text))
ctrl = webapp.ctrl


def run(soc, floor, minutes=40):
    store.WATCHDOG_PATH = os.path.join(tmp, "wd_%s_%s.json" % (soc, floor)) if hasattr(store, "WATCHDOG_PATH") else None
    ctrl.soc_floor = floor
    t0 = datetime(2026, 10, 9, 18, 0)
    sent.clear()
    for m in range(0, minutes, 5):
        ctrl._check_battery_watchdog({"grid": {"total": 461}, "battery": {"current": 0.0, "soc": soc}}, t0 + timedelta(minutes=m))
    return [s for s in sent if "Batterie reagiert" in s[1] or "reagiert seit" in s[1]]


# leer (am Mindest-SOC): kein Alarm
assert run(15, 15) == [] and run(16.5, 15) == [], "leerer Akku ist kein Haenger"
# Akku gefuellt, Netz zieht, Strom 0: echter Verdacht -> Alarm
assert len(run(60, 15)) == 1
# Mindest-SOC unbekannt: wie bisher (konservativ) melden
assert len(run(15, None)) == 1
# deutlich ueber dem Minimum: Alarm
assert len(run(25, 15)) == 1
print("WATCHDOG OK")
