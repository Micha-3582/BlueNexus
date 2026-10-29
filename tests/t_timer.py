"""Nachlauf-Timer (virtuell): neu startbar, laeuft von selbst ab, gemeinsamer Nachlauf fuer mehrere Ausloeser, Regeln, Endpunkte."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import virtual, rules, flows, shelly
from datetime import datetime

virtual.VIRTUAL_PATH = os.path.join(tmp, "virtual_timer.json")
rules.RULES_PATH = os.path.join(tmp, "rules_timer.json"); shelly.DEVICES_PATH = os.path.join(tmp, "dev_timer.json")
for p in (virtual.VIRTUAL_PATH, rules.RULES_PATH, shelly.DEVICES_PATH):
    if os.path.exists(p):
        os.remove(p)

# 1) Anlegen
t = virtual.add("Hof-Licht", "timer")
assert t["kind"] == "timer" and t["minutes"] == 3 and t["until"] == 0 and t["icon"] == "⏲️" and t["users"] == [], t
t2 = virtual.add("Lang", "timer", minutes="45"); assert t2["minutes"] == 45
for bad in (0, 1441, "abc"):
    try:
        virtual.add("X", "timer", minutes=bad); raise SystemExit("Minuten %r muessen abgelehnt werden" % (bad,))
    except virtual.VirtualError:
        pass
assert virtual.add("Sw", "switch")["kind"] == "switch" and "minutes" not in virtual.load()[-1]
print("1) Anlegen OK")

# 2) Start, Restzeit, Verlaengern, Stop
tid = t["id"]
assert virtual.snapshot()[tid]["on"] is False and virtual.next_due() is None
assert virtual.set_state(tid, True)
s = virtual.snapshot()[tid]; assert s["on"] is True and 175 <= s["remaining_s"] <= 180 and s["kind"] == "timer", s
due1 = virtual.next_due(); assert due1 and abs(due1 - (time.time() + 180)) < 3
# nachtriggern: Zeit wird NEU gestartet (nicht addiert)
items = virtual.load(); next(x for x in items if x["id"] == tid)["until"] = time.time() + 20; virtual._save(items)       # fast abgelaufen
assert virtual.snapshot()[tid]["remaining_s"] <= 20
assert virtual.press(tid) is True                                               # Druecken/Regel-Schritt = neu starten
assert virtual.snapshot()[tid]["remaining_s"] >= 175
assert virtual.toggle(tid) is True and virtual.snapshot()[tid]["on"] is False   # umschalten: laeuft -> stoppen
assert virtual.toggle(tid) is True and virtual.snapshot()[tid]["on"] is True    # ... gestoppt -> starten
assert virtual.set_state(tid, False) and virtual.snapshot()[tid]["on"] is False and virtual.next_due() is None
# Ablauf von selbst
items = virtual.load(); next(x for x in items if x["id"] == tid)["until"] = time.time() - 1; virtual._save(items)
assert virtual.snapshot()[tid]["on"] is False and virtual.snapshot()[tid]["remaining_s"] == 0
assert virtual.press("v-gibtsnicht") is False
print("2) Timer OK")

# 3) Regel-Bedingung "Timer ist an" folgt dem Timer
ctx = lambda: {"virtual": virtual.snapshot(), "now": datetime.now()}
cond_on = rules.normalize_condition({"type": "virtual", "id": tid, "is": "on"})
res = lambda: rules.eval_condition(cond_on, ctx())[0]
assert res() is False
virtual.set_state(tid, True); assert res() is True
virtual.set_state(tid, False); assert res() is False
print("3) Bedingung OK")

# 4) Ablauf-Regel mit Timer als Ausloeser setzt den Timer NICHT zurueck (ein Timer laeuft von selbst ab)
virtual.set_state(tid, False)
flow = rules.normalize_rule({"name": "Test", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "virtual", "id": tid, "is": "on"}]},
                             "then": [{"type": "notify", "text": "hi"}], "else": []}, "tf1")
fe = flows.FlowEngine(); fe.step(datetime.now(), ctx(), [flow])           # Ausgangszustand: Timer aus
virtual.set_state(tid, True); fe.step(datetime.now(), ctx(), [flow])      # Timer startet -> Auslöser
assert fe.runs and fe.runs[0]["reset"] == [], fe.runs
# zum Vergleich: ein normaler Schalter wird nach dem Ablauf zurueckgesetzt
sw = virtual.load()[-1]
flow2 = rules.normalize_rule({"name": "Test2", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "virtual", "id": sw["id"], "is": "on"}]},
                              "then": [{"type": "notify", "text": "hi"}], "else": []}, "tf2")
fe2 = flows.FlowEngine(); fe2.step(datetime.now(), ctx(), [flow2]); virtual.set_state(sw["id"], True); fe2.step(datetime.now(), ctx(), [flow2]); assert fe2.runs and fe2.runs[0]["reset"] == [sw["id"]], fe2.runs
virtual.set_state(tid, False)
print("4) Ablauf-Reset OK")

# 5) Endpunkte
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_timer.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
webapp.opslog.log = lambda *a, **k: None
r = c.post("/api/virtual", json={"name": "Garten-Licht", "kind": "timer", "minutes": 7}); assert r.status_code == 201 and r.get_json()["minutes"] == 7, r.get_json()
gid = r.get_json()["id"]
assert c.post("/api/virtual", json={"name": "Falsch", "kind": "timer", "minutes": 0}).status_code == 400
lst = {x["id"]: x for x in c.get("/api/virtual").get_json()}
assert lst[gid]["on"] is False and lst[gid]["remaining_s"] == 0 and lst[gid]["kind"] == "timer"
assert c.post(f"/api/virtual/{gid}/press").status_code == 200
lst = {x["id"]: x for x in c.get("/api/virtual").get_json()}; assert lst[gid]["on"] is True and 415 <= lst[gid]["remaining_s"] <= 420, lst[gid]
assert c.post(f"/api/virtual/{gid}/set", json={"on": False}).status_code == 200 and not {x["id"]: x for x in c.get("/api/virtual").get_json()}[gid]["on"]
assert c.post(f"/api/virtual/{gid}/set", json={"on": True}).status_code == 200 and {x["id"]: x for x in c.get("/api/virtual").get_json()}[gid]["on"]
assert c.patch(f"/api/virtual/{gid}", json={"minutes": 10}).status_code == 200 and virtual.load()[-1]["minutes"] == 10 if False else True
assert c.patch(f"/api/virtual/{gid}", json={"minutes": 10}).status_code == 200
assert next(x for x in virtual.load() if x["id"] == gid)["minutes"] == 10
assert c.patch(f"/api/virtual/{gid}", json={"minutes": 99999}).status_code == 400
print("5) Endpunkte OK")

# 6) Regel mit Timer speichern (Schritt "Eigenen Schalter setzen" + Zustand-halten-Regel mit Timer als Bedingung)
d = shelly.add_by_ip if False else None
shelly._save([{"id": "shelly-l1", "kind": "shelly", "name": "Lampe", "icon": "💡", "ip": "192.168.50.9", "channel": 0, "gen": 1, "model": "Shelly Plug", "show": False, "users": [], "power_w": 0}])
r1 = c.post("/api/rules", json={"name": "Haustuer", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]},
                                "then": [{"type": "virtual", "id": tid, "state": "on"}], "else": []}); assert r1.status_code == 201, r1.get_json()
r2 = c.post("/api/rules", json={"name": "Licht an solange Timer", "mode": "state", "device_id": "shelly-l1", "when": {"mode": "all", "conds": [{"type": "virtual", "id": tid, "is": "on"}]},
                                "then": [{"device_id": "shelly-l1", "state": "on"}], "else": [{"device_id": "shelly-l1", "state": "off"}]})
assert r2.status_code == 201, r2.get_json()
assert rules.used_by("virtual", tid) == ["Haustuer", "Licht an solange Timer"], rules.used_by("virtual", tid)
assert c.delete(f"/api/virtual/{tid}").status_code in (409, 200)
print("6) Regeln OK")
# 7) Rule-Engine: Lampe geht an, solange der Timer laeuft, und aus, wenn er abgelaufen ist
virtual.set_state(tid, False)
dev = lambda on: [{"id": "shelly-l1", "name": "Lampe", "kind": "shelly", "online": True, "on": on, "power": 0, "switchable": True}]
comp = rules.compile_all(rules.list_rules())
cfg0 = store.load_config()
def tick(on):
    ctx = {"virtual": virtual.snapshot(), "now": datetime.now(), "sensors": {}, "devices": {}}
    return webapp.rule_engine.step(datetime.now(), ctx, cfg0, dev(on), comp)
acts = tick(False); assert not acts, acts                        # Timer aus: nichts zu tun
virtual.set_state(tid, True)
acts = tick(False); assert acts and "shelly-l1" in str(acts[0]) and "on" in str(acts[0]).lower(), acts; print("   Aktion:", acts[0])          # Timer laeuft -> Lampe an
acts = tick(True); print("   zweiter Lauf:", acts); assert not acts or acts[0][0] != "off"
items = virtual.load(); next(x for x in items if x["id"] == tid)["until"] = time.time() - 1; virtual._save(items)   # Nachlauf abgelaufen
acts = tick(True); assert acts and "shelly-l1" in str(acts[0]), acts; print("   Aktion:", acts[0])                                                  # -> Lampe aus
print("7) Engine OK")
print("TIMER OK")
