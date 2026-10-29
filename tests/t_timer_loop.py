"""Echte Regelschleife (run_rules) mit Nachlauf-Timer: Lampen gehen an, solange er laeuft, und von selbst aus, wenn er ablaeuft."""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import virtual, rules, shelly

virtual.VIRTUAL_PATH = os.path.join(tmp, "virtual_loop.json")
rules.RULES_PATH = os.path.join(tmp, "rules_loop.json"); shelly.DEVICES_PATH = os.path.join(tmp, "dev_loop.json")
for p in (virtual.VIRTUAL_PATH, rules.RULES_PATH, shelly.DEVICES_PATH):
    if os.path.exists(p):
        os.remove(p)

LAMPS = {f"shelly-l{i}": False for i in (1, 2)}
LOG = []
shelly._save([{"id": k, "kind": "shelly", "name": f"Lampe {k[-1]}", "icon": "💡", "ip": f"192.168.50.{9+i}", "channel": 0, "gen": 1, "model": "Shelly Plug", "show": False, "users": [], "power_w": 0, "switchable": True}
              for i, k in enumerate(LAMPS)])
shelly.list_with_status = lambda only_shown=False, ids=None, live=True: [
    {"id": k, "name": f"Lampe {k[-1]}", "kind": "shelly", "online": True, "on": v, "power": 0, "switchable": True, "address": None}
    for k, v in LAMPS.items() if ids is None or k in ids]
def fake_set(did, on, timer_s=None):
    LAMPS[did] = bool(on); LOG.append((round(time.time() - T0, 1), did, on))
shelly.set_state = fake_set

c0 = store.load_config(); c0.update(rules_enabled=True, rules_dry_run=False, modules={"energy": False, "smarthome": True, "cameras": False, "alexa": False}); store.save_config(c0)
t = virtual.add("Hof-Licht", "timer")
assert rules.add_rule({"name": "Licht", "mode": "state", "device_id": "shelly-l1", "when": {"mode": "all", "conds": [{"type": "virtual", "id": t["id"], "is": "on"}]},
                       "then": [{"device_id": "shelly-l1", "state": "on"}, {"device_id": "shelly-l2", "state": "on"}],
                       "else": [{"device_id": "shelly-l1", "state": "off"}, {"device_id": "shelly-l2", "state": "off"}]})        # SONST: ausschalten - ohne diesen Teil bleiben die Lampen an

import json
for c_ in rules.compile_all(rules.list_rules()): print('  COMPILED:', json.dumps(c_, ensure_ascii=False, default=str)[:600])
T0 = time.time()
_orig = webapp.rule_engine.step
def _traced(now, ctx, cfg_, devs, comp):
    acts = _orig(now, ctx, cfg_, devs, comp)
    print(f"  [step t={time.time()-T0:.1f}s] timer_on={[v['on'] for v in ctx['virtual'].values()]} devs={[d['on'] for d in devs]} comp={len(comp)} -> {[(a[0], a[1]['name']) for a in acts]}")
    return acts
webapp.rule_engine.step = _traced
threading.Thread(target=webapp.ctrl.run_rules, daemon=True).start()
time.sleep(3)
assert not any(LAMPS.values()), "Timer aus: Lampen bleiben aus"
items = virtual.load(); next(x for x in items if x["id"] == t["id"])["until"] = time.time() + 5; virtual._save(items)       # Timer laeuft 5 s
webapp.ctrl._rules_wake.set()
time.sleep(2.5)
print("  nach 2,5 s:", LAMPS, LOG)
assert all(LAMPS.values()), "Lampen muessen an sein, solange der Timer laeuft"
time.sleep(5)
print("  nach 7,5 s:", LAMPS, LOG)
print("  Snapshot:", virtual.snapshot()[t["id"]], "next_due:", virtual.next_due())
if any(LAMPS.values()):
    webapp.ctrl._rules_wake.set(); time.sleep(1.5); print("  nach manuellem Wecken:", LAMPS, LOG)
import autolog
for e in autolog.recent("rules", 10): print("  LOG:", e)
print("  status:", dict(webapp.rule_engine.status), "owner:", dict(webapp.rule_engine.owner))
assert not any(LAMPS.values()), "Timer abgelaufen: Lampen muessen von selbst aus gehen"
print("TIMER LOOP OK")
