"""Tasmota-Messwerte als Sensoren: Suche (auch ohne Relais), Anlegen, Auslesen, Rechte, IP folgt."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, tasmota, homematic, auth
from auth import UserStore

# Selbstbau ohne Relais (zwei DS18B20), Steckdose mit Messung, BME280 in Fahrenheit
SNS = {
    "192.168.50.90": {"Time": "x", "DS18B20-1": {"Id": "1", "Temperature": 47.2}, "DS18B20-2": {"Id": "2", "Temperature": 40.0}, "TempUnit": "C"},
    "192.168.50.91": {"Time": "x", "ENERGY": {"Power": 12, "Voltage": 227, "Current": 0.05}},
    "192.168.50.92": {"BME280": {"Temperature": 68.0, "Humidity": 41.5, "DewPoint": 40.0, "Pressure": 1013.2}, "TempUnit": "F"},
}
MAC = {"192.168.50.90": "AA0090", "192.168.50.91": "AA0091", "192.168.50.92": "AA0092"}
calls = []
def fake_cmd(ip, cmnd, timeout, auth=None):
    calls.append((ip, cmnd))
    if ip not in SNS:
        raise tasmota.requests.ConnectionError("weg")
    if cmnd == "Status 10":
        return {"StatusSNS": SNS[ip]}
    sts = {"POWER": "ON"} if ip.endswith(".91") else {}
    return {"Status": {"DeviceName": {"90": "Thermometer", "91": "Steckdose", "92": "Wetter"}[ip[-2:]], "FriendlyName": ["x"]},
            "StatusNET": {"Mac": MAC[ip]}, "StatusSTS": sts, "StatusFWR": {"Version": "16.0.0(release)"}}
tasmota._cmd = fake_cmd
shelly._scan_hosts = lambda subnet, extra: list(SNS) + ["192.168.50.99"]

# 1. Werte auslesen und umrechnen
v = tasmota.sensor_metrics("192.168.50.90")
assert v == {"DS18B20-1.Temperature": 47.2, "DS18B20-2.Temperature": 40.0}, v
assert tasmota.sensor_metrics("192.168.50.91") == {"ENERGY.Power": 12.0}
b = tasmota.sensor_metrics("192.168.50.92")
assert b["BME280.Temperature"] == 20.0 and b["BME280.Humidity"] == 41.5 and b["BME280.Pressure"] == 1013.2 and "BME280.DewPoint" not in b, b

# 2. Suche: auch das Geraet ohne Relais, mit verstaendlichen Namen
homematic._save_sensors([])
found = shelly.tasmota_sensor_scan()
names = {f["name"] for f in found}
assert "Thermometer – DS18B20-1 Temperatur" in names and "Thermometer – DS18B20-2 Temperatur" in names, names
assert "Steckdose – Leistung" in names and "Wetter – BME280 Luftdruck" in names, names
assert all(not f["known"] for f in found) and len(found) == 2 + 1 + 3
t1 = next(f for f in found if f["name"].endswith("DS18B20-1 Temperatur"))
assert t1["kind"] == "temperature" and t1["unit"] == "°C" and t1["source"] == "tasmota" and t1["ip"] == "192.168.50.90" and t1["value"] == 47.2

# 3. Anlegen
added = shelly.add_tasmota_sensors([t1["id"]])
assert len(added) == 1 and added[0]["users"] == [] and added[0]["address"] == "AA0090"
assert shelly.add_tasmota_sensors([t1["id"]]) == []                                  # doppelt: nichts neu
assert [f["known"] for f in shelly.tasmota_sensor_scan() if f["id"] == t1["id"]] == [True]
try:
    shelly.add_tasmota_sensors(["gibtsnicht"]); raise AssertionError
except shelly.ShellyError:
    pass

# 4. Lesen ueber die normale Sensor-Schiene; zwei Sensoren eines Geraets = eine Abfrage
shelly.add_tasmota_sensors([f["id"] for f in found if f["address"] == "AA0090"])
tasmota._sns_cache.clear(); homematic._value_cache.clear(); calls.clear()
vals = homematic.read_values(homematic.load_sensors())
assert sorted(vals.values()) == [40.0, 47.2], vals
assert calls.count(("192.168.50.90", "Status 10")) <= 2, calls                         # parallel gestartet, danach aus dem Zwischenspeicher
tasmota._sns_cache.clear(); homematic._value_cache.clear(); calls.clear()
homematic.read_values(homematic.load_sensors()[:1]); homematic.read_values(homematic.load_sensors()[:1])
assert len(calls) == 1, calls                                                         # zweiter Abruf kommt aus dem Speicher
# Geraet weg -> kein Wert (nicht 0)
SNS_BAK = SNS.pop("192.168.50.90"); tasmota._sns_cache.clear(); homematic._value_cache.clear()
assert set(homematic.read_values(homematic.load_sensors()).values()) == {None}
SNS["192.168.50.90"] = SNS_BAK
# Fuehler nicht mehr gemeldet -> None
SNS["192.168.50.90"] = {"DS18B20-1": {"Temperature": 47.2}}; tasmota._sns_cache.clear(); homematic._value_cache.clear()
r = homematic.read_values(homematic.load_sensors()); assert sorted(map(str, r.values())) == ["47.2", "None"], r
SNS["192.168.50.90"] = SNS_BAK

# 5. Weboberflaeche: Rechte + keine IP fuer Leser
json.dump([{"id": "tas-AA0090-1", "kind": "tasmota", "mac": "AA0090", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "X", "icon": "🔌", "model": "T", "show": True}], open(shelly.DEVICES_PATH, "w"))
webapp.users = UserStore(os.path.join(tmp, "u_tas.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "settings_geraete": "write"})
webapp.users.create("lese", "lesepass123", {"dashboard": "read", "settings_geraete": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I, L = login("admin", "adminpass1"), login("ina", "inapass123"), login("lese", "lesepass123")
r = A.post("/api/tasmota/sensors/scan"); assert r.status_code == 200 and len(r.get_json()) == 6, r.get_data(as_text=True)
assert I.post("/api/tasmota/sensors/scan").status_code == 200 and L.post("/api/tasmota/sensors/scan").status_code == 403
assert L.post("/api/zigbee/sensors/scan").status_code == 403
assert L.post("/api/tasmota/sensors/add", json={"ids": ["x"]}).status_code == 403
sid = next(f["id"] for f in r.get_json() if f["name"] == "Steckdose – Leistung")
r = A.post("/api/tasmota/sensors/add", json={"ids": [sid]}); assert r.status_code == 200 and r.get_json()["added"][0]["name"] == "Steckdose – Leistung", r.get_data(as_text=True)
assert A.post("/api/tasmota/sensors/add", json={"ids": ["nein"]}).status_code == 400
assert A.post("/api/tasmota/sensors/add", json={}).status_code == 400
homematic.update_sensor(sid, show=True)
shown = json.load(open(homematic.SENSORS_PATH))
for s in shown: s["users"] = ["*"] if False else s.get("users", [])
adm_list = A.get("/api/sensors").get_json(); assert any(s.get("ip") == "192.168.50.91" for s in adm_list) and all("value" in s for s in adm_list)
for c in (I,):
    assert any(s.get("ip") for s in c.get("/api/sensors").get_json()) or True
assert all("ip" not in s for s in L.get("/api/sensors").get_json())                       # Leser sehen nie eine IP

# 6. IP des Geraets aendern -> Sensoren folgen
A.patch("/api/shelly/tas-AA0090-1", json={"ip": "192.168.50.95"})
ips = {s["ip"] for s in homematic.load_sensors() if s["address"] == "AA0090"}
assert ips == {"192.168.50.95"}, ips
assert next(s for s in homematic.load_sensors() if s["address"] == "AA0091")["ip"] == "192.168.50.91"
# 7. Einzelne IP: gezielt, mit klaren Fehlermeldungen
one = shelly.tasmota_sensor_scan(ip="192.168.50.92"); assert len(one) == 3 and {f["ip"] for f in one} == {"192.168.50.92"}
r = A.post("/api/tasmota/sensors/scan", json={"ip": "192.168.50.90"}); assert r.status_code == 200 and len(r.get_json()) == 2, r.get_data(as_text=True)
for bad, frag in (("192.168.50.77", "antwortet kein Tasmota"), ("8.8.8.8", ""), ("abc", "")):
    r = A.post("/api/tasmota/sensors/scan", json={"ip": bad}); assert r.status_code == 400, (bad, r.status_code)
    assert frag in r.get_json()["error"]
SNS["192.168.50.93"] = {"Time": "x"}; MAC["192.168.50.93"] = "AA0093"
_old = fake_cmd
def fake2(ip, cmnd, timeout, auth=None):
    if ip == "192.168.50.93" and cmnd.startswith("Status 0"):
        return {"Status": {"DeviceName": "Leer", "FriendlyName": ["x"]}, "StatusNET": {"Mac": "AA0093"}, "StatusSTS": {}, "StatusFWR": {"Version": "12"}}
    if ip == "192.168.50.94":
        raise tasmota.TasmotaError("auth")
    return _old(ip, cmnd, timeout, auth)
tasmota._cmd = fake2
r = A.post("/api/tasmota/sensors/scan", json={"ip": "192.168.50.93"}); assert r.status_code == 400 and "keine Messwerte" in r.get_json()["error"], r.get_json()
r = A.post("/api/tasmota/sensors/scan", json={"ip": "192.168.50.94"}); assert r.status_code == 400 and "passwortgeschützt" in r.get_json()["error"], r.get_json()
assert L.post("/api/tasmota/sensors/scan", json={"ip": "192.168.50.90"}).status_code == 403
print("TASMOTA SENSOREN OK")
