"""Homematic/HomematicIP ueber die OpenCCU (homematic.py + shelly.py-Anbindung + webapp-Endpunkte).
Gegen einen Mock-CCU-Server, der die JSON-RPC-Form der echten CCU nachbildet (Aufrufformen aus deren webui.js)."""
import sys, os, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, shelly

# ------------------------------------------------------------------ Mock-CCU
def ch(i, addr, name, ctype, idx):
    return {"id": str(i), "name": name, "address": addr, "channelType": ctype, "index": idx, "deviceId": "0"}

DEVICES = [
    {"id": "1001", "name": "Steckdose Studio", "address": "NEQ0000001", "interface": "HmIP-RF", "type": "HmIP-PSM", "channels": [
        ch(1010, "NEQ0000001:0", "HmIP-PSM NEQ0000001:0", "MAINTENANCE", 0),
        ch(1013, "NEQ0000001:3", "HmIP-PSM NEQ0000001:3", "SWITCH_VIRTUAL_RECEIVER", 3),     # Standardname -> Geraetename
        ch(1015, "NEQ0000001:5", "HmIP-PSM NEQ0000001:5", "SWITCH_TRANSMITTER", 5),          # nur lesbar -> ausfiltern
        ch(1016, "NEQ0000001:6", "HmIP-PSM NEQ0000001:6", "ENERGIE_METER_TRANSMITTER", 6)]},
    {"id": "2001", "name": "Wohnzimmer Dimmer", "address": "JEQ0000002", "interface": "BidCos-RF", "type": "HM-LC-Dim1T-FM", "channels": [
        ch(2010, "JEQ0000002:0", "x:0", "MAINTENANCE", 0),
        ch(2011, "JEQ0000002:1", "Deckenlicht", "DIMMER", 1)]},                              # eigener Kanalname
    {"id": "3001", "name": "Waschmaschine", "address": "KEQ0000003", "interface": "BidCos-RF", "type": "HM-ES-PMSw1-Pl", "channels": [
        ch(3010, "KEQ0000003:0", "x:0", "MAINTENANCE", 0),
        ch(3011, "KEQ0000003:1", "KEQ0000003:1", "SWITCH", 1),
        ch(3012, "KEQ0000003:2", "KEQ0000003:2", "POWERMETER", 2)]},
    {"id": "4001", "name": "Wandtaster", "address": "NEQ0000004", "interface": "HmIP-RF", "type": "HmIP-WRC2", "channels": [
        ch(4011, "NEQ0000004:1", "t:1", "KEY_TRANSMITTER", 1)]},
    {"id": "6001", "name": "Wohnzimmer Thermostat", "address": "NEQ0000006", "interface": "HmIP-RF", "type": "HmIP-STHD", "channels": [
        ch(6010, "NEQ0000006:0", "x:0", "MAINTENANCE", 0),
        ch(6011, "NEQ0000006:1", "NEQ0000006:1", "WEATHER_TRANSMITTER", 1)]},
    {"id": "7001", "name": "Fenster Bad", "address": "NEQ0000007", "interface": "HmIP-RF", "type": "HmIP-SWDO", "channels": [
        ch(7010, "NEQ0000007:0", "x:0", "MAINTENANCE", 0),
        ch(7011, "NEQ0000007:1", "NEQ0000007:1", "SHUTTER_CONTACT", 1)]},
    {"id": "8001", "name": "Flur Bewegung", "address": "NEQ0000008", "interface": "HmIP-RF", "type": "HmIP-SMI", "channels": [
        ch(8010, "NEQ0000008:0", "x:0", "MAINTENANCE", 0),
        ch(8011, "NEQ0000008:1", "NEQ0000008:1", "MOTION_DETECTOR", 1)]},
    {"id": "9501", "name": "Fenstergriff Kueche", "address": "NEQ0000009", "interface": "HmIP-RF", "type": "HmIP-SRH", "channels": [
        ch(9510, "NEQ0000009:0", "x:0", "MAINTENANCE", 0),
        ch(9511, "NEQ0000009:1", "NEQ0000009:1", "ROTARY_HANDLE_SENSOR", 1)]},
    {"id": "9601", "name": "Bad Heizkoerper", "address": "NEQ0000010", "interface": "HmIP-RF", "type": "HmIP-eTRV", "channels": [
        ch(9610, "NEQ0000010:0", "x:0", "MAINTENANCE", 0),
        ch(9611, "NEQ0000010:1", "NEQ0000010:1", "HEATING_CLIMATECONTROL_TRANSCEIVER", 1)]},
    {"id": "9701", "name": "Wohnzimmer Heizkoerper", "address": "KEQ0000011", "interface": "BidCos-RF", "type": "HM-CC-RT-DN", "channels": [
        ch(9710, "KEQ0000011:0", "x:0", "MAINTENANCE", 0),
        ch(9714, "KEQ0000011:4", "KEQ0000011:4", "CLIMATECONTROL_RT_TRANSCEIVER", 4)]},
    {"id": "9801", "name": "Tuerschloss Micha", "address": "NEQ0000012", "interface": "HmIP-RF", "type": "HmIP-DLD", "channels": [
        ch(9810, "NEQ0000012:0", "x:0", "MAINTENANCE", 0),
        ch(9811, "NEQ0000012:1", "NEQ0000012:1", "DOOR_LOCK_STATE_TRANSMITTER", 1)]},
    {"id": "9901", "name": "Tuerschloss - Oma", "address": "OEQ0000001", "interface": "BidCos-RF", "type": "HM-Sec-Key-S", "channels": [
        ch(9910, "OEQ0000001:0", "x:0", "MAINTENANCE", 0),
        ch(9911, "OEQ0000001:1", "Tuerschloss - Oma", "KEYMATIC", 1)]},
    {"id": "5001", "name": "Heizungsgruppe", "address": "INT0000005", "interface": "VirtualDevices", "type": "HM-CC-VG-1", "channels": [
        ch(5011, "INT0000005:1", "g:1", "SWITCH", 1)]},
]
PARAMS = {  # Kanal -> {NAME: (TYPE, OPERATIONS)}
    "NEQ0000001:3": {"STATE": ("BOOL", 7), "ON_TIME": ("FLOAT", 2)},
    "NEQ0000001:5": {"STATE": ("BOOL", 5)},
    "NEQ0000001:6": {"POWER": ("FLOAT", 5), "ENERGY_COUNTER": ("FLOAT", 5)},
    "JEQ0000002:1": {"LEVEL": ("FLOAT", 7), "ON_TIME": ("FLOAT", 2)},
    "KEQ0000003:1": {"STATE": ("BOOL", 7), "ON_TIME": ("FLOAT", 2)},
    "KEQ0000003:2": {"POWER": ("FLOAT", 5)},
    "NEQ0000006:1": {"ACTUAL_TEMPERATURE": ("FLOAT", 5), "HUMIDITY": ("INTEGER", 5)},
    "NEQ0000007:1": {"STATE": ("BOOL", 5)},
    "NEQ0000008:1": {"MOTION": ("BOOL", 5), "ILLUMINATION": ("FLOAT", 5)},
    "NEQ0000009:1": {"STATE": ("ENUM", 5)},
    "NEQ0000010:1": {"SET_POINT_TEMPERATURE": ("FLOAT", 7), "ACTUAL_TEMPERATURE": ("FLOAT", 5)},
    "KEQ0000011:4": {"SET_TEMPERATURE": ("FLOAT", 7)},
    "NEQ0000012:1": {"LOCK_STATE": ("ENUM", 5), "LOCK_TARGET_LEVEL": ("ENUM", 7)},
    "OEQ0000001:1": {"STATE": ("BOOL", 7), "STATE_UNCERTAIN": ("BOOL", 5), "OPEN": ("ACTION", 2)},
}
ROOMS = [{"id": "9001", "name": "Wohnzimmer", "channelIds": ["2011"]}, {"id": "9002", "name": "Studio", "channelIds": ["1013"]}]


class Mock:
    def __init__(self):
        self.values = {("NEQ0000001:3", "STATE"): False, ("NEQ0000001:6", "POWER"): 12.3, ("JEQ0000002:1", "LEVEL"): 0.0,
                       ("KEQ0000003:1", "STATE"): True, ("KEQ0000003:2", "POWER"): 1850.0,
                       ("NEQ0000001:0", "UNREACH"): False, ("JEQ0000002:0", "UNREACH"): False, ("KEQ0000003:0", "UNREACH"): True,
                       ("NEQ0000006:1", "ACTUAL_TEMPERATURE"): 19.46, ("NEQ0000006:1", "HUMIDITY"): 58,
                       ("NEQ0000007:1", "STATE"): False, ("NEQ0000008:1", "MOTION"): True, ("NEQ0000008:1", "ILLUMINATION"): 123.0,
                       ("NEQ0000009:1", "STATE"): 2, ("NEQ0000010:1", "SET_POINT_TEMPERATURE"): 21.0, ("KEQ0000011:4", "SET_TEMPERATURE"): 19.5,
                       ("NEQ0000010:0", "UNREACH"): False, ("NEQ0000012:1", "LOCK_STATE"): 1, ("OEQ0000001:1", "STATE"): False, ("OEQ0000001:0", "UNREACH"): False, ("NEQ0000012:0", "UNREACH"): False, ("KEQ0000011:0", "UNREACH"): False, ("NEQ0000006:0", "UNREACH"): False, ("NEQ0000007:0", "UNREACH"): False,
                       ("NEQ0000008:0", "UNREACH"): True, ("NEQ0000009:0", "UNREACH"): False}
        self.sessions, self.log, self.logins = set(), [], 0
        self.strict_bool_string = False      # JSON-true/false ablehnen, nur "1"/"0" akzeptieren
        self.putparamset_fails = False

    def handle(self, method, p):
        if method == "Session.login":
            if p.get("username") == "Admin" and p.get("password") == "geheim":
                self.logins += 1
                sid = f"SID{self.logins}"
                self.sessions.add(sid)
                return sid, None
            return None, {"name": "JSONRPCError", "code": 400, "message": "login failed"}
        if p.get("_session_id_") not in self.sessions:
            return None, {"name": "JSONRPCError", "code": 400, "message": 'access denied ("GUEST" needed 0)'}
        self.log.append((method, {k: v for k, v in p.items() if k != "_session_id_"}))
        if method == "Device.listAllDetail":
            return DEVICES, None
        if method == "Room.getAll":
            return ROOMS, None
        if method == "Interface.getParamsetDescription":
            d = PARAMS.get(p["address"], {})
            return [{"NAME": n, "TYPE": t, "OPERATIONS": o} for n, (t, o) in d.items()], None
        if method == "Interface.getValue":
            return self.values.get((p["address"], p["valueKey"])), None
        if method == "Interface.setValue":
            if self.strict_bool_string and p["type"] == "bool" and isinstance(p["value"], bool):
                return None, {"name": "JSONRPCError", "code": 501, "message": "invalid value"}
            v = p["value"]
            if p["type"] == "bool":
                v = v in (True, "1", "true")
            self.values[(p["address"], p["valueKey"])] = v
            return True, None
        if method == "Interface.putParamset":
            if self.putparamset_fails:
                return None, {"name": "JSONRPCError", "code": 400, "message": 'access denied ("USER" needed 0)'}
            for item in p["set"]:
                self.values[(p["address"], item["name"])] = item["value"]
            return True, None
        return None, {"name": "JSONRPCError", "code": 404, "message": "unknown method " + method}


mock = Mock()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        result, error = mock.handle(body["method"], body.get("params") or {})
        out = json.dumps({"id": body.get("id"), "version": "1.1", "result": result, "error": error}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)


srv = HTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]

# Der echte Code erlaubt nur private LAN-Adressen (kein Web-Proxy-Missbrauch) - fuer den Mock auf Loopback aufweichen
_real_split = homematic._split_host
homematic._split_host = lambda host: ("http", "127.0.0.1")        # Port steckt separat in _base (siehe unten)
_real_post = homematic._post
def _post_local(base, method, params):
    return _real_post(f"http://127.0.0.1:{PORT}", method, params)
homematic._post = _post_local

# ------------------------------------------------------------------ 1) Adress-Pruefung (echter Code)
homematic._split_host = _real_split
for bad in ("127.0.0.1", "8.8.8.8", "ccu.local", "", "http://10.0.0.1.evil.com"):
    try:
        homematic.save_credentials(bad, "Admin", "geheim")
        raise AssertionError(f"{bad!r} haette abgelehnt werden muessen")
    except homematic.HomematicError:
        pass
homematic.save_credentials("192.168.50.22", "Admin", "geheim")
c = homematic.load_credentials()
assert c["host"] == "http://192.168.50.22" and c["password"] == "geheim"
homematic.save_credentials("https://192.168.50.22", "Admin", "")        # leeres Passwort = unveraendert
assert homematic.load_credentials()["password"] == "geheim" and homematic.load_credentials()["host"] == "https://192.168.50.22"
pub = homematic.credentials_public()
assert "password" not in pub and pub["password_set"] is True and pub["configured"] is True
print("1) Adress-Pruefung + Passwort bleibt geheim OK")
homematic._split_host = lambda host: ("http", "127.0.0.1")

# ------------------------------------------------------------------ 2) Login
homematic.save_credentials("192.168.50.22", "Admin", "falsch")
homematic._split_host = lambda host: ("http", "127.0.0.1")
try:
    homematic.test_connection()
    raise AssertionError("falsches Passwort muss scheitern")
except homematic.HomematicError as e:
    assert "Anmeldung" in str(e), e
homematic._split_host = _real_split
homematic.save_credentials("192.168.50.22", "Admin", "geheim")
homematic._split_host = lambda host: ("http", "127.0.0.1")
info = homematic.test_connection()
assert info["devices"] == 12, info                  # ohne die VirtualDevices-Gruppe
print("2) Login (falsch/richtig) + Geraeteanzahl ohne Gruppen OK")

# ------------------------------------------------------------------ 3) Suche
found = shelly.homematic_scan()
by = {f["address"]: f for f in found}
assert set(by) == {"NEQ0000001:3", "JEQ0000002:1", "KEQ0000003:1"}, set(by)
a = by["NEQ0000001:3"]
assert a["datapoint"] == "STATE" and a["power_addr"] == "NEQ0000001:6" and a["name"] == "Steckdose Studio" and a["room"] == "Studio", a
d = by["JEQ0000002:1"]
assert d["datapoint"] == "LEVEL" and d["power_addr"] == "" and d["name"] == "Deckenlicht" and d["room"] == "Wohnzimmer", d
w = by["KEQ0000003:1"]
assert w["power_addr"] == "KEQ0000003:2" and w["name"] == "Waschmaschine", w
assert all(f["known"] is False for f in found)
print("3) Suche: Schalter/Dimmer/Leistungskanal/Namen/Raeume richtig, Taster+Nur-lesen+Gruppe ausgefiltert OK")

# ------------------------------------------------------------------ 4) Anlegen
added = shelly.add_homematic(["NEQ0000001:3", "JEQ0000002:1", "KEQ0000003:1"])
assert len(added) == 3
assert shelly.add_homematic(["NEQ0000001:3"]) == []                       # Doppelte bleiben unveraendert
items = {x["id"]: x for x in shelly.load_devices()}
assert set(items) == {"hm-NEQ0000001-3", "hm-JEQ0000002-1", "hm-KEQ0000003-1"}, set(items)
assert items["hm-JEQ0000002-1"]["icon"] == "💡" and items["hm-NEQ0000001-3"]["icon"] == "🔌"
assert items["hm-NEQ0000001-3"]["kind"] == "homematic" and items["hm-NEQ0000001-3"]["show"] is False
assert all("password" not in x for x in items.values())
try:
    shelly.add_homematic(["GIBT:ES:NICHT"]); raise AssertionError("unbekannter Kanal muss abgelehnt werden")
except shelly.ShellyError:
    pass
print("4) Anlegen: ids, Symbole, keine Doppelten, unbekannter Kanal abgelehnt OK")

# ------------------------------------------------------------------ 5) Status
st = {x["id"]: x for x in shelly.list_with_status()}
s1 = st["hm-NEQ0000001-3"]; assert s1["online"] and s1["on"] is False and s1["power"] == 12.3, s1
s2 = st["hm-JEQ0000002-1"]; assert s2["online"] and s2["on"] is False and s2["power"] is None, s2
s3 = st["hm-KEQ0000003-1"]; assert s3["online"] is False and s3["on"] is None, s3          # UNREACH
print("5) Status: an/aus, Leistung, Dimmer, nicht erreichbar -> offline OK")

# ------------------------------------------------------------------ 6) Schalten
r = shelly.set_state("hm-NEQ0000001-3", True)
assert mock.values[("NEQ0000001:3", "STATE")] is True and r["on"] is True
mock.log.clear()
shelly.set_state("hm-NEQ0000001-3", True, timer_s=600)                       # Sicherheits-Timer ueber ON_TIME
pp = [c for c in mock.log if c[0] == "Interface.putParamset"]
assert pp and {i["name"]: i["value"] for i in pp[0][1]["set"]} == {"ON_TIME": 600.0, "STATE": True}, mock.log
assert mock.values[("NEQ0000001:3", "ON_TIME")] == 600.0
shelly.set_state("hm-NEQ0000001-3", True, timer_s=0)                         # 0 = laufenden Timer aufheben
assert mock.values[("NEQ0000001:3", "ON_TIME")] == 0.0
shelly.set_state("hm-NEQ0000001-3", False)
assert mock.values[("NEQ0000001:3", "STATE")] is False
shelly.set_state("hm-JEQ0000002-1", True)                                     # Dimmer: 100 %
assert mock.values[("JEQ0000002:1", "LEVEL")] == 1.0
assert shelly.list_with_status()[1]["on"] is True
shelly.set_state("hm-JEQ0000002-1", False)
assert mock.values[("JEQ0000002:1", "LEVEL")] == 0.0
print("6) Schalten: an/aus, ON_TIME-Timer, Timer aufheben, Dimmer 100 %/0 OK")

# ------------------------------------------------------------------ 7) Sitzung laeuft ab -> unbemerkt neu anmelden
logins_before = mock.logins
mock.sessions.clear()
shelly.set_state("hm-NEQ0000001-3", True)
assert mock.logins == logins_before + 1 and mock.values[("NEQ0000001:3", "STATE")] is True
print("7) Abgelaufene Sitzung -> transparent neu angemeldet OK")

# ------------------------------------------------------------------ 8) Rueckfaelle
mock.strict_bool_string = True
shelly.set_state("hm-NEQ0000001-3", False)
assert mock.values[("NEQ0000001:3", "STATE")] is False
mock.strict_bool_string = False
mock.putparamset_fails = True
shelly.set_state("hm-NEQ0000001-3", True, timer_s=300)                       # ohne ON_TIME, aber es schaltet trotzdem
assert mock.values[("NEQ0000001:3", "STATE")] is True
mock.putparamset_fails = False
print("8) Rueckfaelle (Bool als Text, putParamset ohne Recht) OK")

# ------------------------------------------------------------------ S) Sensoren
homematic._value_cache.clear(); homematic._pushed.clear()
sfound = homematic.sensors_scan()
sby = {x["id"]: x for x in sfound}
exp = {"hmS-NEQ0000006-1-ACTUAL_TEMPERATURE": ("temperature", "Wohnzimmer Thermostat – Temperatur", "°C", False),
       "hmS-NEQ0000006-1-HUMIDITY": ("humidity", "Wohnzimmer Thermostat – Luftfeuchte", "%", False),
       "hmS-NEQ0000007-1-STATE": ("contact", "Fenster Bad – Fenster/Tür", "", True),
       "hmS-NEQ0000008-1-MOTION": ("motion", "Flur Bewegung – Bewegung", "", True),
       "hmS-NEQ0000008-1-ILLUMINATION": ("brightness", "Flur Bewegung – Helligkeit", "lux", False),
       "hmS-NEQ0000009-1-STATE": ("contact", "Fenstergriff Kueche – Fenster/Tür", "", True),
       "hmS-NEQ0000001-6-POWER": ("power", "Steckdose Studio – Leistung", "W", False),
       "hmS-KEQ0000003-2-POWER": ("power", "Waschmaschine – Leistung", "W", False),
       "hmS-NEQ0000010-1-ACTUAL_TEMPERATURE": ("temperature", "Bad Heizkoerper – Temperatur", "°C", False),
       "hmS-NEQ0000012-1-LOCK_STATE": ("lock", "Tuerschloss Micha – Türschloss", "", True)}
assert set(sby) == set(exp), set(sby) ^ set(exp)
for sid_, (kind, name, unit, binary) in exp.items():
    f = sby[sid_]
    assert (f["kind"], f["name"], f["unit"], f["binary"]) == (kind, name, unit, binary), f
assert all(f["known"] is False for f in sfound)
print("S1) Sensor-Suche: Temperatur/Feuchte/Kontakt/Drehgriff/Bewegung/Helligkeit/Leistung, Namen+Einheiten OK")

added_s = homematic.add_sensors(list(exp))
inv = {x["id"]: x.get("invert") for x in homematic.load_sensors()}
assert inv["hmS-NEQ0000007-1-STATE"] is True and inv["hmS-NEQ0000009-1-STATE"] is True and not inv["hmS-NEQ0000008-1-MOTION"], inv      # Fenster/Tuer: TRUE = geschlossen als Standard
homematic._value_cache.clear(); homematic._pushed.clear()
v0 = homematic.read_values([x for x in homematic.load_sensors() if x["id"] == "hmS-NEQ0000007-1-STATE"])["hmS-NEQ0000007-1-STATE"]
assert v0 is True                                                        # Fenster zu (roh FALSE) -> umgekehrt TRUE
import rules as _r
ok_, txt_ = _r.eval_condition({"type": "sensor", "sensor_id": "x", "is": True}, {"now": __import__("datetime").datetime(2026, 1, 1), "sensors": {"x": True},
                              "sensor_info": {"x": {"id": "x", "name": "Tuer", "kind": "contact", "invert": True}}})
assert ok_ is True and txt_ == "Tuer: geschlossen (TRUE)", txt_            # Text passt zur Umkehr
for sid_ in ("hmS-NEQ0000007-1-STATE", "hmS-NEQ0000009-1-STATE"):
    homematic.update_sensor(sid_, invert=False)                          # die uebrigen Pruefungen gehen vom Rohwert aus (TRUE = offen)
assert len(added_s) == 10 and homematic.add_sensors(["hmS-NEQ0000007-1-STATE"]) == []
try:
    homematic.add_sensors(["hmS-GIBT-ES-NICHT"])
    raise AssertionError("unbekannter Sensor muss abgelehnt werden")
except homematic.HomematicError:
    pass
homematic._value_cache.clear(); homematic._pushed.clear()
vals = {x["id"]: x["value"] for x in homematic.list_sensors_with_values()}
assert vals["hmS-NEQ0000006-1-ACTUAL_TEMPERATURE"] == 19.5          # gerundet auf 0,1
assert vals["hmS-NEQ0000006-1-HUMIDITY"] == 58.0
assert vals["hmS-NEQ0000007-1-STATE"] is False                       # Fenster zu
assert vals["hmS-NEQ0000009-1-STATE"] is True                        # Drehgriff 2 = offen -> wahr
assert vals["hmS-NEQ0000008-1-MOTION"] is None                       # Geraet nicht erreichbar (UNREACH) -> kein Wert
assert vals["hmS-NEQ0000001-6-POWER"] == 12.3
print("S2) Sensorwerte: gerundet, Fenster zu=False, Drehgriff offen=True, nicht erreichbar=None OK")

import rules
c1 = rules.normalize_condition({"type": "sensor", "sensor_id": "hmS-NEQ0000007-1-STATE", "is": True})
assert c1 == {"type": "sensor", "sensor_id": "hmS-NEQ0000007-1-STATE", "is": True}
assert rules.normalize_condition({"type": "sensor", "sensor_id": "a", "is": False})["is"] is False
assert rules.normalize_condition({"type": "sensor", "sensor_id": "x", "is": "false"})["is"] is False
c4 = rules.normalize_condition({"type": "sensor", "sensor_id": "t", "op": "below", "value": "20,5"})
assert c4 == {"type": "sensor", "sensor_id": "t", "op": "below", "value": 20.5}
for bad in ({"type": "sensor"}, {"type": "sensor", "sensor_id": "x", "op": "gleich", "value": 1},
            {"type": "sensor", "sensor_id": "x", "op": "below", "value": "abc"}):
    try:
        rules.normalize_condition(bad)
        raise AssertionError(f"{bad} haette abgelehnt werden muessen")
    except rules.RuleError:
        pass
print("S3) Regel-Bedingung normalisiert: TRUE/FALSE, unter/ueber mit Dezimalkomma, Fehlerfaelle abgelehnt OK")

from datetime import datetime
infos = {x["id"]: x for x in homematic.load_sensors()}


def ctx_for(*ids):
    homematic._value_cache.clear(); homematic._pushed.clear()
    sens = [infos[i] for i in ids]
    return {"now": datetime(2026, 10, 2, 12, 0), "sensors": homematic.read_values(sens), "sensor_info": {i: infos[i] for i in ids}}


W = "hmS-NEQ0000007-1-STATE"; T = "hmS-NEQ0000006-1-ACTUAL_TEMPERATURE"; M = "hmS-NEQ0000008-1-MOTION"; G = "hmS-NEQ0000009-1-STATE"
ctx = ctx_for(W, T, M, G)
ok, txt = rules.eval_condition({"type": "sensor", "sensor_id": W, "is": True}, ctx)
assert ok is False and "offen (TRUE)" in txt, (ok, txt)               # Fenster zu: "offen = TRUE" nicht erfuellt
ok, txt = rules.eval_condition({"type": "sensor", "sensor_id": W, "is": False}, ctx)
assert ok is True and "geschlossen (FALSE)" in txt, (ok, txt)         # "FALSE" (= zu) erfuellt
assert rules.eval_condition({"type": "sensor", "sensor_id": G, "is": True}, ctx)[0] is True
ok, txt = rules.eval_condition({"type": "sensor", "sensor_id": T, "op": "below", "value": 20}, ctx)
assert ok is True and "unter 20 °C" in txt, (ok, txt)
assert rules.eval_condition({"type": "sensor", "sensor_id": T, "op": "above", "value": 20}, ctx)[0] is False
assert rules.eval_condition({"type": "sensor", "sensor_id": T, "op": "above", "value": 19.5}, ctx)[0] is True    # ueber = >= (wie Akku/Preis)
assert rules.eval_condition({"type": "sensor", "sensor_id": M, "is": True}, ctx)[0] is None                     # nicht erreichbar
assert rules.eval_condition({"type": "sensor", "sensor_id": M, "is": False}, ctx)[0] is None                    # auch FALSE trifft dann NICHT zu
ok, txt = rules.eval_condition({"type": "sensor", "sensor_id": "weg", "is": True}, ctx)
assert ok is None and "nicht mehr vorhanden" in txt
print("S4) Auswertung: TRUE/FALSE, unter/ueber, nicht erreichbar & fehlender Sensor -> nie erfuellt OK")

rules.add_rule({"device_id": "hm-NEQ0000001-3", "on": [{"type": "sensor", "sensor_id": W, "is": True}], "off": []})
rules.add_rule({"device_id": "hm-JEQ0000002-1", "enabled": False, "on": [{"type": "sensor", "sensor_id": T, "op": "below", "value": 18}], "off": []})
homematic._value_cache.clear(); homematic._pushed.clear()
mock.log.clear()
rc = webapp.ctrl._rules_ctx(cfg, None, datetime(2026, 10, 2, 12, 0))
assert set(rc["sensors"]) == {W} and set(rc["sensor_info"]) == {W}, rc.get("sensors")
asked = {x[1].get("address") for x in mock.log if x[0] == "Interface.getValue"}
assert "NEQ0000006:1" not in asked, asked                              # Sensor einer ausgeschalteten Regel wird nicht abgefragt
print("S5) Regel-Kontext fragt nur Sensoren aktiver Regeln ab OK")

assert homematic.update_sensor(W, name="Badfenster") and homematic.update_sensor("nein") is False
assert next(x for x in homematic.load_sensors() if x["id"] == W)["name"] == "Badfenster"
assert homematic.remove_sensor(W) and not homematic.remove_sensor(W)
print("S6) Sensor umbenennen/entfernen OK")

# ---- S7) Sensor umkehren
GR = "hmS-NEQ0000009-1-STATE"                                         # Drehgriff: Wert 2 = offen -> True
homematic._value_cache.clear(); homematic._pushed.clear()
assert homematic.read_values([x for x in homematic.load_sensors() if x["id"] == GR])[GR] is True
assert homematic.update_sensor(GR, invert=True)
assert homematic.read_values([x for x in homematic.load_sensors() if x["id"] == GR])[GR] is False       # umgekehrt: jetzt FALSE
assert homematic.update_sensor(GR, invert=False)
homematic._value_cache.clear(); homematic._pushed.clear()
assert homematic.read_values([x for x in homematic.load_sensors() if x["id"] == GR])[GR] is True
print("S7) Sensor umkehren (TRUE <-> FALSE) OK")

# ---- L) Tuerschloss (HmIP-DLD): nur Zustand lesen, TRUE = verriegelt
LK = "hmS-NEQ0000012-1-LOCK_STATE"
lk = lambda: homematic.read_values([x for x in homematic.load_sensors() if x["id"] == LK])[LK]
homematic._value_cache.clear(); homematic._pushed.clear(); assert lk() is True                                  # 1 = verriegelt
mock.values[("NEQ0000012:1", "LOCK_STATE")] = 2; homematic._value_cache.clear(); homematic._pushed.clear(); assert lk() is False       # 2 = entriegelt
mock.values[("NEQ0000012:1", "LOCK_STATE")] = 0; homematic._value_cache.clear(); homematic._pushed.clear(); assert lk() is None        # 0 = unbekannt
mock.values[("NEQ0000012:1", "LOCK_STATE")] = "LOCKED"; homematic._value_cache.clear(); homematic._pushed.clear(); assert lk() is True   # auch als Text
homematic.update_sensor(LK, invert=True); homematic._value_cache.clear(); homematic._pushed.clear(); assert lk() is False
homematic.update_sensor(LK, invert=False)
assert next(x for x in homematic.load_sensors() if x["id"] == LK).get("invert") in (None, False)
print("L) Tuerschloss: verriegelt/entriegelt/unbekannt, Umkehr OK")

# ---- K) Tuerschloss als Aktion (Freigabe, Pegel 0/1/2)
kf = homematic.locks_scan()
assert sorted(f["id"] for f in kf) == ["hmK-NEQ0000012-1", "hmK-OEQ0000001-1"], kf
assert {f["id"]: f["lock_kind"] for f in kf} == {"hmK-NEQ0000012-1": "hmip", "hmK-OEQ0000001-1": "keymatic"}
assert len(homematic.add_locks(["hmK-NEQ0000012-1"])) == 1 and homematic.add_locks(["hmK-NEQ0000012-1"]) == []
assert homematic.load_locks()[0]["allow_open"] is False
mock.values[("NEQ0000012:1", "LOCK_STATE")] = 1; homematic._value_cache.clear(); homematic._pushed.clear()
assert homematic.list_locks_with_state()[0]["locked"] is True
for act in ("open", "unlock"):
    try:
        homematic.lock_action("hmK-NEQ0000012-1", act); raise AssertionError("ohne Freigabe")
    except homematic.HomematicError as e:
        assert "nicht freigegeben" in str(e)
assert homematic.lock_action("hmK-NEQ0000012-1", "lock") == "Tuerschloss Micha" and mock.values[("NEQ0000012:1", "LOCK_TARGET_LEVEL")] == 0     # Verriegeln ist immer erlaubt
homematic.update_lock("hmK-NEQ0000012-1", allow_open=True)
homematic.lock_action("hmK-NEQ0000012-1", "open"); assert mock.values[("NEQ0000012:1", "LOCK_TARGET_LEVEL")] == 2                              # wie im ioBroker-Skript: 2 = Tuer oeffnen
homematic.lock_action("hmK-NEQ0000012-1", "unlock"); assert mock.values[("NEQ0000012:1", "LOCK_TARGET_LEVEL")] == 1
try:
    homematic.lock_action("hmK-NEQ0000012-1", "kaputt"); raise AssertionError("unbekannte Aktion")
except homematic.HomematicError:
    pass
homematic.update_lock("hmK-NEQ0000012-1", allow_open=False)
assert homematic.remove_lock("hmK-NEQ0000012-1") and not homematic.remove_lock("hmK-NEQ0000012-1")
# ---- K2) klassisches Keymatic (HM-Sec-Key, BidCos): STATE wahr = entriegelt, OPEN = Tuer oeffnen
KM = "hmK-OEQ0000001-1"
assert len(homematic.add_locks([KM])) == 1 and homematic.load_locks()[0]["lock_kind"] == "keymatic"
def km_locked():
    homematic._value_cache.clear(); homematic._pushed.clear(); homematic._unreach_cache.clear()
    return next(x for x in homematic.list_locks_with_state() if x["id"] == KM)["locked"]
mock.values[("OEQ0000001:1", "STATE")] = False; assert km_locked() is True, "STATE aus = verriegelt"
mock.values[("OEQ0000001:1", "STATE")] = True; assert km_locked() is False, "STATE an = entriegelt"
mock.values[("OEQ0000001:1", "STATE")] = "false"; assert km_locked() is True, "BidCos liefert teils Text"
mock.values[("OEQ0000001:0", "UNREACH")] = True; assert km_locked() is None, "nicht erreichbar = unbekannt"; mock.values[("OEQ0000001:0", "UNREACH")] = False
for act in ("open", "unlock"):
    try:
        homematic.lock_action(KM, act); raise AssertionError("ohne Freigabe")
    except homematic.HomematicError:
        pass
mock.values[("OEQ0000001:1", "STATE")] = True
assert homematic.lock_action(KM, "lock") == "Tuerschloss - Oma" and mock.values[("OEQ0000001:1", "STATE")] is False
homematic.update_lock(KM, allow_open=True)
homematic.lock_action(KM, "unlock"); assert mock.values[("OEQ0000001:1", "STATE")] is True
homematic.lock_action(KM, "open"); assert mock.values[("OEQ0000001:1", "OPEN")] is True
assert homematic.remove_lock(KM)
print("K2) Keymatic (klassisch): finden, Zustand, verriegeln/entriegeln/oeffnen OK")
print("K) Tuerschloss: Suche, Freigabe-Pflicht, Pegel 0/1/2 OK")

# ---- T) Thermostate
homematic._value_cache.clear(); homematic._pushed.clear()
tfound = homematic.setpoints_scan()
assert {f["id"]: f["datapoint"] for f in tfound} == {"hmT-NEQ0000010-1": "SET_POINT_TEMPERATURE", "hmT-KEQ0000011-4": "SET_TEMPERATURE"}, tfound
assert homematic.add_setpoints(["hmT-NEQ0000010-1", "hmT-KEQ0000011-4"]) and homematic.add_setpoints(["hmT-NEQ0000010-1"]) == []
vals = {x["id"]: x["value"] for x in homematic.list_setpoints_with_values()}
assert vals == {"hmT-NEQ0000010-1": 21.0, "hmT-KEQ0000011-4": 19.5}, vals
res = homematic.set_setpoints(["*"], 0)                                   # 0 Grad -> auf 5 Grad begrenzt (Einstellbereich 5 bis 30)
assert all(v == 5.0 and err is None for _, v, err in res) and len(res) == 2, res
assert mock.values[("NEQ0000010:1", "SET_POINT_TEMPERATURE")] == 5.0 and mock.values[("KEQ0000011:4", "SET_TEMPERATURE")] == 5.0
res = homematic.set_setpoints(["hmT-KEQ0000011-4"], 99)
assert res == [("Wohnzimmer Heizkoerper", 30.0, None)] and mock.values[("NEQ0000010:1", "SET_POINT_TEMPERATURE")] == 5.0, res
assert homematic.set_setpoints(["hmT-weg"], 21)[0][2] == "Thermostat nicht mehr vorhanden"
assert homematic.update_setpoint("hmT-NEQ0000010-1", name="Bad") and homematic.remove_setpoint("hmT-NEQ0000010-1") and not homematic.remove_setpoint("hmT-NEQ0000010-1")
print("T) Thermostate: Suche, Solltemperatur setzen (begrenzt), umbenennen/entfernen OK")

# ------------------------------------------------------------------ 9) CCU nicht erreichbar -> offline, kein Absturz
srv.shutdown(); srv.server_close()
down = shelly.list_with_status()
assert all(x["online"] is False for x in down if x["kind"] == "homematic"), down
try:
    shelly.set_state("hm-NEQ0000001-3", False); raise AssertionError("haette Fehler melden muessen")
except shelly.ShellyError as e:
    assert "Schalten fehlgeschlagen" in str(e), e
print("9) CCU weg -> Geraete offline, Schalten meldet verstaendlichen Fehler OK")

# ------------------------------------------------------------------ 10) Web-Endpunkte
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "users.json"))
webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client()
c.post("/login", data={"username": "admin", "password": "adminpass1"})
j = c.get("/api/homematic").get_json()
assert j["configured"] and "password" not in j and j["password_set"], j
r = c.post("/api/homematic/credentials", json={"host": "8.8.8.8", "user": "x", "password": "y"})
assert r.status_code == 400
r = c.post("/api/homematic/add", json={})
assert r.status_code == 400
print("10) Endpunkte: Info ohne Passwort, Fremdadresse/leer abgelehnt OK")

print("HOMEMATIC OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
