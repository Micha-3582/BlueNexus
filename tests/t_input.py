"""HM-MOD-EM-8 (Eingangsmodul) als Sensor 'Eingang' + Sperrzeit bei Ablauf-Regeln (Lichtschranke -> Foto)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, rules, flows
from datetime import datetime

# --- Sensorsuche
def dev(channel_type):
    return [{"interface": "BidCos-RF", "type": "HM-MOD-EM-8", "name": "Keller - Sensormodul", "id": 1, "channels": [
        {"address": "PEQ0009003:0", "channelType": "MAINTENANCE", "name": "Keller - Sensormodul:0", "id": 10},
        {"address": "PEQ0009003:2", "channelType": channel_type, "name": "Lichtschranke - Hof", "id": 12},
        {"address": "PEQ0009003:3", "channelType": channel_type, "name": "Kellertüre", "id": 13}]}]
homematic._call = lambda m, p=None: dev(CT) if m == "Device.listAllDetail" else []
homematic._param_desc = lambda iface, addr: {"UNREACH": {"OPERATIONS": 5}} if addr.endswith(":0") else {"STATE": {"OPERATIONS": 7}, "INSTALL_TEST": {"OPERATIONS": 4}}
for CT in ("SWITCH_INTERFACE", "ANDERER_TYP"):                      # Kanaltyp-Treffer UND Geraetetyp-Treffer
    found = homematic.discover_sensors(set())
    ids = {f["id"]: f for f in found}
    assert set(ids) == {"hmS-PEQ0009003-2-STATE", "hmS-PEQ0009003-3-STATE"}, (CT, ids.keys())
    f = ids["hmS-PEQ0009003-2-STATE"]
    assert f["kind"] == "input" and f["binary"] is True and f["datapoint"] == "STATE" and f["name"].startswith("Lichtschranke - Hof"), f
b = homematic.build_sensors(["hmS-PEQ0009003-2-STATE"])[0]
assert b["kind"] == "input" and "invert" not in b                   # kein Fenster: TRUE = aktiv
print("Eingang gefunden OK")
words = rules.eval_condition(rules.normalize_condition({"type": "sensor", "sensor_id": "s", "is": True}),
                             {"now": datetime(2026, 10, 4, 12, 0), "sensor_info": {"s": {"id": "s", "name": "Hof", "kind": "input"}}, "sensors": {"s": True}})
assert words[0] is True and "aktiv" in words[1], words

# --- Sperrzeit
rules.RULES_PATH = os.path.join(tmp, "r.json")
body = {"name": "Foto bei Lichtschranke", "mode": "flow", "cooldown_s": "10", "when": {"mode": "all", "conds": [{"type": "sensor", "sensor_id": "s", "is": True}]},
        "then": [{"type": "photo", "id": "cam-1", "text": "Hof"}, {"type": "notify", "text": "x"}], "else": []}
r = rules.normalize_rule(body, "f1"); assert r["cooldown_s"] == 10
assert rules.normalize_rule({**body, "cooldown_s": None}, "f2")["cooldown_s"] == 0
try:
    rules.normalize_rule({**body, "cooldown_s": 999999}); raise SystemExit("zu gross")
except rules.RuleError:
    pass
flows.STATE_PATH = os.path.join(tmp, "fs.json")
eng = flows.FlowEngine()
val = {"v": False}
ctx = lambda: {"sensors": {"s": val["v"]}, "sensor_info": {"s": {"id": "s", "name": "Hof", "kind": "input"}}}
NOW = datetime(2026, 10, 4, 21, 0)
def step():
    return eng.step(NOW, ctx(), [r])
step()                                                   # Ausgangszustand
val["v"] = True; ev = step(); assert [e[0] for e in ev] == ["start"], ev
assert [x["step"]["type"] for x in eng.advance(1000.0)] == ["photo", "notify"]
val["v"] = False; step()
val["v"] = True; ev = step(); assert [e[0] for e in ev] == ["skip"] and "Sperrzeit" in ev[0][2], ev        # gleich nochmal durchgefahren: ignoriert
assert eng.advance(1001.0) == []
val["v"] = False; step()
eng.cool["f1"] -= 11                                     # Sperrzeit vorbei
val["v"] = True; ev = step(); assert [e[0] for e in ev] == ["start"], ev
# ohne Sperrzeit: jedes Mal
r2 = rules.normalize_rule({**body, "cooldown_s": 0}, "f3"); eng2 = flows.FlowEngine()
st = lambda: eng2.step(NOW, ctx(), [r2])
val["v"] = False; st(); val["v"] = True; assert "start" in [e[0] for e in st()]; val["v"] = False; st(); val["v"] = True; assert "start" in [e[0] for e in st()]    # ohne Sperrzeit startet jede Ausloesung (ersetzt den laufenden Ablauf)
# Seite
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
page = c.get("/rules").get_data(as_text=True); assert "r-cool" in page and "Sperrzeit nach dem Auslösen" in page
print("SPERRZEIT OK")
