import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import victron, notify

sent = []
notify.CRED_PATH = os.path.join(tmp, "tg.json")
notify.STATE_PATH = os.path.join(tmp, "ns.json")
import json
json.dump({"token": "t", "chat_id": "1"}, open(notify.CRED_PATH, "w"))
notify._send_async = lambda text: sent.append(text)
webapp.notify = notify
cfg.update({"notify_events": {"alarms": True}})

state = {"overload": 0}


class FakeCerbo2:
    def __init__(self, *a, **k): pass
    def read_soc(self): return 60.0
    def read_ess_mode(self): return 10
    def read_system(self, **k): return None
    def read_min_soc(self): return 20.0
    def read_alarms(self):
        return {"values": {k: (state["overload"] if k == "vebus_overload" else 0) for k in victron.ALARM_REGS}, "errors": {}}
    def write_ess_mode(self, m, dry_run=True): return False


webapp.Cerbo = FakeCerbo2
cfg.update({"cerbo_host": "x", "tibber_token": "x", "dry_run": True})

webapp.ctrl.safe_tick()
assert sent == [], sent          # noch kein Alarm

state["overload"] = 2
webapp.ctrl.safe_tick()
time.sleep(0.05)
assert any("Überlast" in s for s in sent), sent
n = len(sent)

webapp.ctrl.safe_tick()          # bleibt an -> keine zweite Meldung
assert len(sent) == n, sent

state["overload"] = 0
sent.clear()
webapp.ctrl.safe_tick()
time.sleep(0.05)
assert any("wieder in Ordnung" in s for s in sent), sent

print("ALARM NOTIFY OK", sys.argv[1].split("/")[-1])
