"""Homematic-Rollladen: finden (LEVEL+STOP), anlegen, Position lesen/fahren/anhalten, Regel-Schritt 'blind', Sichtbarkeit, Loeschschutz."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, rules, autolog
homematic.BLINDS_PATH = os.path.join(tmp, "blinds.json")
rules.RULES_PATH = os.path.join(tmp, "r.json")
for p in (homematic.BLINDS_PATH, rules.RULES_PATH):
    if os.path.exists(p):
        os.remove(p)

LEVEL = {"v": 0.45}
UNREACH = {"v": False}
DEVS = [
    {"interface": "BidCos-RF", "type": "HM-LC-Bl1PBU-FM", "name": "Rollladen Bad", "id": 1, "channels": [
        {"address": "OEQ0009002:0", "channelType": "MAINTENANCE", "name": "Rollladen Bad:0", "id": 10},
        {"address": "OEQ0009002:1", "channelType": "BLIND", "name": "Rollladen Bad", "id": 11}]},
    {"interface": "HmIP-RF", "type": "HmIP-BROLL", "name": "Rollladen Küche", "id": 3, "channels": [
        {"address": "000A:3", "channelType": "BLIND_VIRTUAL_RECEIVER", "name": "Rollladen Küche:3", "id": 31}]},
    {"interface": "BidCos-RF", "type": "HM-LC-Dim1T-FM", "name": "Dimmer", "id": 2, "channels": [
        {"address": "DIM:1", "channelType": "DIMMER", "name": "Dimmer", "id": 21}]},
    {"interface": "BidCos-RF", "type": "HM-X", "name": "Jalousie ohne STOP", "id": 4, "channels": [
        {"address": "JAL:1", "channelType": "BLIND", "name": "Jalousie ohne STOP", "id": 41}]},
]
calls = []


def fake_call(m, p=None):
    if m == "Device.listAllDetail":
        return DEVS
    if m == "Interface.setValue":
        calls.append(p)
        if p["valueKey"] == "LEVEL":
            LEVEL["v"] = p["value"]
        return None
    if m == "Interface.getValue":
        if p["valueKey"] == "LEVEL":
            return LEVEL["v"]
        if p["valueKey"] == "UNREACH":
            return UNREACH["v"]
    return []


homematic._call = fake_call
homematic._param_desc = lambda iface, addr: ({"LEVEL": {"OPERATIONS": 7}, "STOP": {"OPERATIONS": 2}} if addr in ("OEQ0009002:1", "000A:3")
                                             else {"LEVEL": {"OPERATIONS": 7}})
found = homematic.blinds_scan()
assert sorted(f["id"] for f in found) == ["hmR-000A-3", "hmR-OEQ0009002-1"], found                 # Dimmer (DIMMER) und Jalousie ohne STOP nicht
assert {f["name"] for f in found} == {"Rollladen Bad", "Rollladen Küche"} and not any(f["known"] for f in found)
print("Suche OK")

from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_blind.json"))
for f in (os.path.join(tmp, "u_blind.json"),):
    pass
webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "settings_geraete": "write"})
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
ina = webapp.app.test_client(); ina.post("/login", data={"username": "ina", "password": "inapass123"}, follow_redirects=True)

r = c.post("/api/homematic/blinds/add", json={"ids": ["hmR-OEQ0009002-1", "hmR-000A-3"], "edits": {"hmR-OEQ0009002-1": {"name": " Rollladen Wohnzimmer ", "icon": "🏠"}}})
assert r.status_code == 200 and len(r.get_json()["added"]) == 2, r.get_json()
assert c.post("/api/homematic/blinds/add", json={"ids": ["hmR-OEQ0009002-1"], "edits": {"hmR-OEQ0009002-1": {"icon": "nix"}}}).status_code == 400
lst = {x["id"]: x for x in c.get("/api/homematic/blinds").get_json()}
assert lst["hmR-OEQ0009002-1"]["name"] == "Rollladen Wohnzimmer" and lst["hmR-OEQ0009002-1"]["icon"] == "🏠" and lst["hmR-000A-3"]["icon"] == "🏠"        # Standard-Symbol: nur gaengige Emoji (🪟 zeigt manche Handys als Kaestchen)
assert lst["hmR-OEQ0009002-1"]["level"] == 45 and lst["hmR-OEQ0009002-1"]["users"] == [], lst
assert c.get("/api/homematic/blinds?light=1").get_json()[0]["level"] is None                 # ohne Live-Abfrage
UNREACH["v"] = True; homematic._unreach_cache.clear(); homematic._pushed.clear()
assert c.get("/api/homematic/blinds").get_json()[0]["level"] is None                           # nicht erreichbar -> unbekannt
UNREACH["v"] = False; homematic._unreach_cache.clear(); homematic._pushed.clear()
print("Anlegen/Lesen OK")

# Bedienen
r = c.post("/api/homematic/blinds/hmR-OEQ0009002-1/level", json={"level": 0}); assert r.status_code == 200
assert calls[-1] == {"interface": "BidCos-RF", "address": "OEQ0009002:1", "valueKey": "LEVEL", "type": "double", "value": 0.0}, calls[-1]
c.post("/api/homematic/blinds/hmR-OEQ0009002-1/level", json={"level": 100}); assert calls[-1]["value"] == 1.0
c.post("/api/homematic/blinds/hmR-OEQ0009002-1/level", json={"level": 35}); assert calls[-1]["value"] == 0.35
for bad in (-1, 101, "x", None):
    assert c.post("/api/homematic/blinds/hmR-OEQ0009002-1/level", json={"level": bad}).status_code == 400, bad
r = c.post("/api/homematic/blinds/hmR-000A-3/stop"); assert r.status_code == 200
assert calls[-1] == {"interface": "HmIP-RF", "address": "000A:3", "valueKey": "STOP", "type": "bool", "value": True}, calls[-1]
assert c.post("/api/homematic/blinds/nix/level", json={"level": 5}).status_code == 400
print("Fahren/Stopp OK")

# Sichtbarkeit: neu = nur Admin; Freigabe -> Benutzer darf sehen und bedienen
assert ina.get("/api/homematic/blinds").get_json() == []
assert ina.post("/api/homematic/blinds/hmR-000A-3/level", json={"level": 10}).status_code == 404
assert c.patch("/api/homematic/blinds/hmR-000A-3", json={"users": ["ina"]}).status_code == 200
assert [x["id"] for x in ina.get("/api/homematic/blinds").get_json()] == ["hmR-000A-3"]
assert ina.post("/api/homematic/blinds/hmR-000A-3/level", json={"level": 10}).status_code == 200
assert ina.patch("/api/homematic/blinds/hmR-000A-3", json={"name": "x"}).status_code in (403, 302)                    # umbenennen/entfernen nur Admin
assert ina.delete("/api/homematic/blinds/hmR-000A-3").status_code in (403, 302)
print("Sichtbarkeit OK")

# Regel-Schritt
body = {"name": "Abends zu", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]},
        "then": [{"type": "blind", "id": "hmR-OEQ0009002-1", "level": "0"}], "else": []}
r_ = rules.normalize_rule(body, "k1")
assert r_["then"][0] == {"type": "blind", "id": "hmR-OEQ0009002-1", "action": "set", "level": 0}, r_["then"][0]
assert rules.normalize_rule({**body, "then": [{"type": "blind", "id": "x", "action": "stop"}]})["then"][0] == {"type": "blind", "id": "x", "action": "stop"}
for bad in ({"type": "blind", "id": ""}, {"type": "blind", "id": "x", "level": 101}, {"type": "blind", "id": "x", "level": -5}):
    try:
        rules.normalize_rule({**body, "then": [bad]}); raise SystemExit("sollte scheitern")
    except rules.RuleError:
        pass
try:
    rules.normalize_rule({**body, "mode": None}); raise SystemExit("nur im Ablauf")
except rules.RuleError as e:
    assert "Rollladen" in str(e)

log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
webapp.opslog.log = lambda *a, **k: None


def run(step, dry=False):
    webapp.ctrl._apply_flow({"rule_id": "k1", "rule": "Abends zu", "branch": "then", "step": step, "after_s": 0}, dry, {})


n = len(calls); run(r_["then"][0]); assert calls[-1]["valueKey"] == "LEVEL" and calls[-1]["value"] == 0.0 and log[-1][0] == "blind" and "auf 0 %" in log[-1][2], (calls[-1], log[-1])
run({"type": "blind", "id": "hmR-OEQ0009002-1", "action": "stop"}); assert calls[-1]["valueKey"] == "STOP" and "anhalten" in log[-1][2]
n = len(calls); run(r_["then"][0], dry=True); assert len(calls) == n and "würde" in log[-1][2] and log[-1][3]
run({"type": "blind", "id": "weg", "action": "set", "level": 0}); assert log[-1][0] == "fail"
homematic._call = lambda m, p=None: (_ for _ in ()).throw(homematic.HomematicError("CCU nicht erreichbar")) if m == "Interface.setValue" else fake_call(m, p)
run(r_["then"][0]); assert log[-1][0] == "fail" and "CCU" in log[-1][2]
homematic._call = fake_call
print("Regel-Schritt OK")

# Speichern: unbekannter Rollladen abgelehnt; Loeschschutz; Entfernen nimmt den Schritt aus Regeln
bad = {"rules": [{**body, "then": [{"type": "blind", "id": "hmR-weg", "level": 0}]}]}
rr = c.post("/api/automation", json=bad); assert rr.status_code == 400 and "Rollladen" in rr.get_json()["error"], rr.get_json()
assert c.post("/api/automation", json={"rules": [body]}).status_code == 200 and len(rules.list_rules()) == 1
assert c.delete("/api/homematic/blinds/hmR-OEQ0009002-1").status_code == 409
assert c.get("/api/rule-usage?kind=blind&id=hmR-OEQ0009002-1").get_json()["rules"] == ["Abends zu"]
rules.replace_all([{**x, "enabled": False} for x in rules.list_rules()])
assert c.delete("/api/homematic/blinds/hmR-OEQ0009002-1").status_code == 200
assert rules.list_rules() == [], rules.list_rules()
assert c.patch("/api/homematic/blinds/hmR-000A-3", json={"icon": "nix"}).status_code == 400
assert c.patch("/api/homematic/blinds/hmR-000A-3", json={"icon": "🚪", "name": "Küche"}).status_code == 200
x = c.get("/api/homematic/blinds").get_json()[0]; assert x["name"] == "Küche" and x["icon"] == "🚪"
assert c.delete("/api/homematic/blinds/hmR-000A-3").status_code == 200 and c.get("/api/homematic/blinds").get_json() == []
print("BLIND OK")
