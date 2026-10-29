"""Homematic-Soundmodul (HM-OU-CM-PCB): finden, anlegen, abspielen (SUBMIT-String), Regel-Schritt 'sound'."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, rules, autolog
homematic.SOUNDS_PATH = os.path.join(tmp, "sounds.json")
rules.RULES_PATH = os.path.join(tmp, "r.json")

CT = {"v": "SIGNAL_CHIME"}
def devs():
    return [{"interface": "BidCos-RF", "type": "HM-OU-CM-PCB", "name": "Soundmodul - Hans", "id": 1, "channels": [
        {"address": "OEQ0009001:0", "channelType": "MAINTENANCE", "name": "Soundmodul - Hans:0", "id": 10},
        {"address": "OEQ0009001:1", "channelType": CT["v"], "name": "Soundmodul - Hans", "id": 11}]},
        {"interface": "BidCos-RF", "type": "HM-LC-Sw1-FM", "name": "Schalter", "id": 2, "channels": [
        {"address": "ABC:1", "channelType": "SWITCH", "name": "Schalter", "id": 21}]}]
calls = []
def fake_call(m, p=None):
    if m == "Device.listAllDetail":
        return devs()
    if m == "Interface.setValue":
        calls.append(p); return None
    return []
homematic._call = fake_call
homematic._param_desc = lambda iface, addr: {"SUBMIT": {"OPERATIONS": 2}} if addr == "OEQ0009001:1" else {"STATE": {"OPERATIONS": 7}}
for ct in ("SIGNAL_CHIME", "IRGENDWAS"):                         # Kanaltyp- bzw. Geraetetyp-Treffer (HM-OU-C...)
    CT["v"] = ct
    found = homematic.sounds_scan()
    assert [f["id"] for f in found] == ["hmA-OEQ0009001-1"] and found[0]["name"] == "Soundmodul - Hans" and not found[0]["known"], found
print("Suche OK")

# Format wie im ioBroker-Skript
assert homematic.sound_value(3) == "1,1,108000,3" and homematic.sound_value(3, 50, 2) == "0.5,2,108000,3" and homematic.sound_value(1, 0) == "0,1,108000,1"
for bad in ((0,), (256,), (1, 101), (1, 100, 0), (1, 100, 21), ("x",)):
    try:
        homematic.sound_value(*bad); raise SystemExit("sollte scheitern %r" % (bad,))
    except homematic.HomematicError:
        pass

from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
r = c.post("/api/homematic/sounds/add", json={"ids": ["hmA-OEQ0009001-1"], "edits": {"hmA-OEQ0009001-1": {"name": " Klingel Esszimmer "}}}); assert r.status_code == 200, r.get_json()
lst = c.get("/api/homematic/sounds").get_json(); assert lst[0]["name"] == "Klingel Esszimmer" and lst[0]["address"] == "OEQ0009001:1"
assert c.get("/api/homematic/sounds/scan") .status_code == 405 and c.post("/api/homematic/sounds/scan").get_json()[0]["known"] is True
r = c.post("/api/homematic/sounds/hmA-OEQ0009001-1/play", json={"track": 3, "volume": 100}); assert r.status_code == 200
assert calls[-1] == {"interface": "BidCos-RF", "address": "OEQ0009001:1", "valueKey": "SUBMIT", "type": "string", "value": "1,1,108000,3"}, calls[-1]
assert c.post("/api/homematic/sounds/hmA-OEQ0009001-1/play", json={"track": 999}).status_code == 400
assert c.post("/api/homematic/sounds/nix/play", json={"track": 1}).status_code == 400
print("Anlegen/Abspielen OK")

# Regel mit Sound-Schritt
body = {"name": "Klingel", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]},
        "then": [{"type": "sound", "id": "hmA-OEQ0009001-1", "track": "3", "volume": "80", "repeats": "2"}], "else": []}
r_ = rules.normalize_rule(body, "k1"); assert r_["then"][0] == {"type": "sound", "id": "hmA-OEQ0009001-1", "track": 3, "volume": 80, "repeats": 2}
for bad in ({"type": "sound", "id": ""}, {"type": "sound", "id": "x", "track": 0}, {"type": "sound", "id": "x", "volume": 101}):
    try:
        rules.normalize_rule({**body, "then": [bad]}); raise SystemExit("sollte scheitern")
    except rules.RuleError:
        pass
try:
    rules.normalize_rule({**body, "mode": None}); raise SystemExit("nur im Ablauf")
except rules.RuleError as e:
    assert "Sound" in str(e)
log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
webapp.opslog.log = lambda *a, **k: None
def run(step, dry=False):
    webapp.ctrl._apply_flow({"rule_id": "k1", "rule": "Klingel", "branch": "then", "step": step, "after_s": 0}, dry, {})
n = len(calls); run(r_["then"][0]); assert calls[-1]["value"] == "0.8,2,108000,3" and log[-1][0] == "sound" and "abgespielt" in log[-1][2], (calls[-1], log[-1])
n = len(calls); run(r_["then"][0], dry=True); assert len(calls) == n and "würde" in log[-1][2] and log[-1][3]
run({"type": "sound", "id": "weg", "track": 1, "volume": 100, "repeats": 1}); assert log[-1][0] == "fail"
homematic._call = lambda m, p=None: (_ for _ in ()).throw(homematic.HomematicError("CCU nicht erreichbar")) if m == "Interface.setValue" else fake_call(m, p)
run(r_["then"][0]); assert log[-1][0] == "fail" and "CCU" in log[-1][2]
homematic._call = fake_call
# Speichern: unbekanntes Modul abgelehnt; Modul loeschen entfernt den Schritt
bad = {"rules": [{**body, "then": [{"type": "sound", "id": "hmA-weg", "track": 1}]}]}
rr = c.post("/api/automation", json=bad); assert rr.status_code == 400 and "Soundmodul" in rr.get_json()["error"], rr.get_json()
assert c.post("/api/automation", json={"rules": [body]}).status_code == 200 and len(rules.list_rules()) == 1
assert lst[0]["icon"] == "🔔"
assert c.patch("/api/homematic/sounds/hmA-OEQ0009001-1", json={"icon": "🚨"}).status_code == 200 and c.get("/api/homematic/sounds").get_json()[0]["icon"] == "🚨"
assert c.patch("/api/homematic/sounds/hmA-OEQ0009001-1", json={"icon": "nix"}).status_code == 400
assert c.patch("/api/homematic/sounds/hmA-OEQ0009001-1", json={"name": "Gong"}).status_code == 200 and c.get("/api/homematic/sounds").get_json()[0]["name"] == "Gong"
assert c.delete("/api/homematic/sounds/hmA-OEQ0009001-1").status_code == 409                  # Regel "Klingel" ist eingeschaltet
rules.replace_all([{**r_, "enabled": False} for r_ in rules.list_rules()])
assert c.delete("/api/homematic/sounds/hmA-OEQ0009001-1").status_code == 200 and c.get("/api/homematic/sounds").get_json() == []
assert rules.list_rules() == [], rules.list_rules()
r = c.post("/api/homematic/sounds/add", json={"ids": ["hmA-OEQ0009001-1"], "edits": {"hmA-OEQ0009001-1": {"name": "Gong 2", "icon": "📢"}}}); assert r.status_code == 200
x = c.get("/api/homematic/sounds").get_json()[0]; assert x["name"] == "Gong 2" and x["icon"] == "📢", x
assert c.delete("/api/homematic/sounds/hmA-OEQ0009001-1").status_code == 200
r = c.post("/api/homematic/sounds/add", json={"ids": ["hmA-OEQ0009001-1"], "edits": {"hmA-OEQ0009001-1": {"icon": "nix"}}}); assert r.status_code == 400 and c.get("/api/homematic/sounds").get_json() == []
assert c.post("/api/homematic/sounds/scan").get_json()[0]["icon"] == "🔔"
page = c.get("/rules").get_data(as_text=True); assert "Sound abspielen" in page
assert "hm-sound-scan" in c.get("/smarthome").get_data(as_text=True)
print("SOUND OK")
