"""Wake-on-LAN: Magic Packet (an einen lokalen UDP-Empfaenger), Eingabepruefung, Endpunkte, PIN, Ablauf-Schritt."""
import sys, os, json, socket, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import wol, rules, flows, autolog
from auth import UserStore

if os.path.exists(wol.WOL_PATH):
    os.remove(wol.WOL_PATH)

# --- Magic Packet: 6 x FF + 16 x MAC
pkt = wol.magic_packet("aa-bb-cc-dd-ee-ff")
assert len(pkt) == 102 and pkt[:6] == b"\xff" * 6 and pkt[6:12] == bytes.fromhex("aabbccddeeff") and pkt[6:] == bytes.fromhex("aabbccddeeff") * 16
assert wol.normalize_mac("aabb.ccdd.eeff") == "AA:BB:CC:DD:EE:FF" == wol.normalize_mac("AA:BB:CC:DD:EE:FF") == wol.normalize_mac("aabbccddeeff")
for bad in ("", "AA:BB:CC", "GG:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF:00"):
    try:
        wol.normalize_mac(bad); raise AssertionError(bad)
    except wol.WolError:
        pass
print("Paket/MAC OK")

# --- Eintraege
for bad in (dict(name="", mac="AA:BB:CC:DD:EE:FF"), dict(name="x", mac="nope"), dict(name="x", mac="AA:BB:CC:DD:EE:FF", ip="8.8.8.8"),
            dict(name="x", mac="AA:BB:CC:DD:EE:FF", ip="abc"), dict(name="x", mac="AA:BB:CC:DD:EE:FF", broadcast="1.2.3.255"), dict(name="x", mac="AA:BB:CC:DD:EE:FF", port=0)):
    try:
        wol.add(**bad); raise AssertionError(bad)
    except wol.WolError:
        pass
it = wol.add("Mein PC", "aa:bb:cc:dd:ee:ff", ip="192.168.50.50")
assert it["mac"] == "AA:BB:CC:DD:EE:FF" and it["port"] == 9 and wol.targets(it) == ["255.255.255.255", "192.168.50.255"]
assert wol.targets({**it, "broadcast": "192.168.178.255"}) == ["192.168.178.255"] and wol.targets({"mac": it["mac"]}) == ["255.255.255.255"]

# --- Senden: wirklich ueber einen UDP-Socket - Empfaenger auf Loopback (Ziel per Eintrag ueberschrieben)
rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
rx.bind(("127.0.0.1", 0)); rx.settimeout(3)
port = rx.getsockname()[1]
items = wol.load(); items[0]["broadcast"] = "127.0.0.1"; items[0]["port"] = port; wol._save(items)
sent = wol.wake(it["id"]); data, _ = rx.recvfrom(4096)
assert sent == ["127.0.0.1"] and data == pkt, (sent, len(data))
try:
    wol.wake("wol-gibts-nicht"); raise AssertionError("unbekanntes Ziel")
except wol.WolError:
    pass
print("Senden (UDP) OK")

# --- Ping-Anzeige: ohne IP unbekannt; mit Loopback-Aufruf erreichbar (lokaler ping)
assert wol.is_up("") is None
print("Erreichbarkeit:", wol.is_up("127.0.0.1"))

# --- Endpunkte, PIN, Admin
webapp.users = UserStore(os.path.join(tmp, "users_wol.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("helfer", "helferpass1", {"dashboard": "write", "settings_geraete": "write", "rules": "write"})
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
h = webapp.app.test_client(); h.post("/login", data={"username": "helfer", "password": "helferpass1"}, follow_redirects=True)
assert c.post("/api/wol", json={"name": "NAS", "mac": "nonsense"}).status_code == 400
assert c.post("/api/wol", json={"name": "NAS", "mac": "11:22:33:44:55:66", "broadcast": "127.0.0.1"}).status_code == 400            # Loopback als Broadcast ist nicht erlaubt
r = c.post("/api/wol", json={"name": "NAS", "mac": "11:22:33:44:55:66", "port": port}); assert r.status_code == 201
nid = r.get_json()["id"]
assert r.get_json().get("users") == []                                                                    # neu: nur Admin
assert c.patch(f"/api/wol/{nid}", json={"users": None}).status_code == 200                           # fuer den Test freigeben
items = wol.load()
for x in items:
    if x["id"] == nid:
        x["broadcast"] = "127.0.0.1"                                                                                     # nur im Test: Empfaenger auf Loopback
wol._save(items)
lst = {x["id"]: x for x in c.get("/api/wol").get_json()}
assert lst[nid]["pin_set"] is False and "pin_hash" not in json.dumps(lst)
rx.settimeout(0.5)
assert c.post(f"/api/wol/{nid}/wake").status_code == 200
d2, _ = rx.recvfrom(4096); assert d2[6:12] == bytes.fromhex("112233445566")
assert c.patch(f"/api/wol/{nid}", json={"pin": "1234"}).status_code == 200
assert h.patch(f"/api/wol/{nid}", json={"pin": ""}).status_code == 403                             # nur Admin verwaltet PINs
r = h.post(f"/api/wol/{nid}/wake"); assert r.status_code == 403 and r.get_json()["pin_required"] is True
assert h.post(f"/api/wol/{nid}/wake", json={"pin": "0000"}).status_code == 403
assert h.post(f"/api/wol/{nid}/wake", json={"pin": "1234"}).status_code == 200
rx.recvfrom(4096)
for i in range(5):
    h.post(f"/api/wol/{nid}/wake", json={"pin": "9999"})
r = h.post(f"/api/wol/{nid}/wake", json={"pin": "1234"}); assert r.status_code == 429                  # Sperre nach 5 Fehlversuchen
webapp._pin_fails.clear()
assert c.patch(f"/api/wol/{nid}", json={"name": "NAS 2", "show": False, "ip": "192.168.50.60"}).status_code == 200
assert c.patch(f"/api/wol/{nid}", json={"mac": "kaputt"}).status_code == 400
assert [x for x in c.get("/api/wol").get_json() if x["id"] == nid][0]["name"] == "NAS 2"
print("Endpunkte/PIN/Admin OK")

# --- Ablauf-Schritt
log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
webapp.opslog.log = lambda *a, **k: None
ctrl = webapp.ctrl
step = {"type": "wol", "id": nid}
ctrl._apply_flow({"rule_id": "r", "rule": "Test", "branch": "then", "step": step, "after_s": 0}, False, {})
d3, _ = rx.recvfrom(4096); assert d3[6:12] == bytes.fromhex("112233445566") and log[-1][0] == "wol" and "gesendet" in log[-1][2], log[-1]
ctrl._apply_flow({"rule_id": "r", "rule": "Test", "branch": "then", "step": step, "after_s": 0}, True, {})
rx.settimeout(0.3)
try:
    rx.recvfrom(4096); raise AssertionError("Trockenlauf darf nichts senden")
except socket.timeout:
    pass
assert log[-1][3] is True and "würde" in log[-1][2]
ctrl._apply_flow({"rule_id": "r", "rule": "Test", "branch": "then", "step": {"type": "wol", "id": "wol-weg"}, "after_s": 0}, False, {})
assert log[-1][0] == "fail"
a = rules.normalize_rule({"name": "PC wecken", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "07:00", "to": "08:00", "days": []}]},
                          "then": [step], "else": []})
assert a["then"] == [step] and flows.is_flow(a)
for bad in ({"type": "wol", "id": ""}, {"type": "wol"}):
    try:
        rules.normalize_rule({"name": "x", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "07:00", "to": "08:00", "days": []}]}, "then": [bad]})
        raise AssertionError(bad)
    except rules.RuleError:
        pass
try:
    rules.normalize_rule({"name": "x", "when": {"mode": "all", "conds": [{"type": "soc", "op": "above", "pct": 1}]}, "then": [step]})
    raise AssertionError("WOL im Zustands-Modus")
except rules.RuleError:
    pass
# Ziel loeschen entfernt den Schritt aus Regeln
rules.replace_all([a]); assert c.delete(f"/api/wol/{nid}").status_code == 409                       # eingeschaltete Regel verwendet es
rules.replace_all([{**r_, "enabled": False} for r_ in rules.list_rules()]); assert c.delete(f"/api/wol/{nid}").status_code == 200 and rules.list_rules() == []
fam = c.get("/api/device-families").get_json()["families"]; assert fam["wol"] is True                      # (it ist noch angelegt)
print("Ablauf-Schritt OK")
print("WOL OK")
