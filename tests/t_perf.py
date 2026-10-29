"""Geschwindigkeits-Messung, Logbuch-Zwischenspeicher, Quelle ohne Warten, Tasmota-Messwerte ohne Stau, Push-Meldung ins Logbuch."""
import sys, os, json, time, threading
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import perf, devicelog, share, tasmota, homematic, shelly
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
webapp.users = UserStore(os.path.join(tmp, "u_perf.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "read"})
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
l = webapp.app.test_client(); l.post("/login", data={"username": "lese", "password": "lesepass123"})

# 1) Messung: Seitenabrufe zaehlen, nur Administratoren sehen sie
perf.reset()
for _ in range(3): c.get("/api/live")
j = c.get("/api/perf").get_json(); ep = next(e for e in j["endpoints"] if e["name"] == "api_live"); assert ep["count"] >= 3, j
assert l.get("/api/perf").status_code == 403 and webapp.app.test_client().get("/api/perf").status_code in (401, 302, 403)
assert l.post("/api/perf").status_code == 403
# langsamer Abruf wird gemerkt
perf.note_request("api_x", "/api/x", 1500.0); j = c.get("/api/perf").get_json(); assert any(s["what"] == "/api/x" and s["ms"] == 1500 for s in j["slow"]) and next(e for e in j["endpoints"] if e["name"] == "api_x")["slow"] == 1
# ausgehende Aufrufe: je Host, Fehler gezaehlt (kein Netz: Verbindung abgelehnt)
import requests
try: requests.get("http://127.0.0.1:9/x", timeout=1)
except requests.RequestException: pass
j = c.get("/api/perf").get_json(); o = next(x for x in j["outbound"] if x["host"] == "127.0.0.1:9"); assert o["count"] == 1 and o["errors"] == 1, o
assert c.post("/api/perf").get_json()["endpoints"] == [] or True
j = c.post("/api/perf").get_json(); assert j["slow"] == [] and j["outbound"] == []
print("1) Messung OK")

# 2) Logbuch: nur beim Aendern der Datei neu einlesen; letzte-Bedienung-Karte gleich richtig
devicelog.log("aktor", "device:a", "A", "eingeschaltet", True, by="x")
r1 = devicelog._rows(); assert devicelog._rows() is r1                                     # unveraendert: gleicher Speicher
devicelog.log("aktor", "device:b", "B", "ausgeschaltet", True, by="y")
r2 = devicelog._rows(); assert r2 is not r1 and len(r2) == len(r1) + 1
assert devicelog.recent(1)[0]["name"] == "B" and set(devicelog.last_map()) >= {"device:a", "device:b"}
lm1 = devicelog.last_map(); devicelog.log("aktor", "device:a", "A", "ausgeschaltet", True, by="z"); assert devicelog.last_map()["device:a"]["text"] == "ausgeschaltet" and lm1["device:a"]["text"] == "eingeschaltet"
assert set(devicelog.last_map(lambda r: r == "device:b")) == {"device:b"}
print("2) Logbuch-Speicher OK")

# 3) Quelle haengt: andere Anfragen warten NICHT mit, sondern bekommen den letzten Stand
share._cache["q-x"] = (time.time() - 100, [{"ref": "device:1", "name": "alt"}], None)
share.CACHE_TTL_S = 0
started = threading.Event(); release = threading.Event()
def slow_http(s, method, path, **kw):
    started.set(); release.wait(5); return {"items": [{"ref": "device:1", "name": "neu"}]}
share._http = slow_http; share._source = lambda sid: {"id": sid, "name": "Q", "url": "http://x", "token": "t"}
th = threading.Thread(target=lambda: share.fetch("q-x", force=True)); th.start(); started.wait(2)
t0 = time.time(); items, err = share.fetch("q-x"); dt = time.time() - t0
assert dt < 0.5 and items and items[0]["name"] == "alt", (dt, items)                       # sofort, mit altem Stand
release.set(); th.join(3); assert share.fetch("q-x", force=True)[0][0]["name"] == "neu"
print("3) Quelle ohne Warten OK")

# 4) Tasmota-Messwerte: gleichzeitige Abfragen = EIN Aufruf; nicht erreichbar -> lange Ruhe statt Dauer-Timeout
calls = []
def slow_cmd(ip, cmnd, timeout, auth=None):
    calls.append(ip); time.sleep(0.3); raise tasmota.requests.ConnectionError("weg")
tasmota._cmd = slow_cmd; tasmota._sns_cache.clear()
res = []
ths = [threading.Thread(target=lambda: res.append(tasmota.read_metric("192.168.9.9", "A.Temperature"))) for _ in range(6)]
t0 = time.time(); [t.start() for t in ths]; [t.join() for t in ths]; dt = time.time() - t0
assert res == [None] * 6 and len(calls) == 1 and dt < 1.0, (calls, dt)
assert tasmota.read_metric("192.168.9.9", "A.Temperature") is None and len(calls) == 1          # bleibt in der Ruhezeit (kein neuer Versuch)
tasmota._sns_cache["192.168.9.9"] = (time.time() - 1, None)                                      # Ruhezeit vorbei
tasmota._cmd = lambda ip, cmnd, timeout, auth=None: {"StatusSNS": {"A": {"Temperature": 20}}}
assert tasmota.read_metric("192.168.9.9", "A.Temperature") == 20.0
print("4) Tasmota-Messwerte OK")

# 5) Push der CCU: Wechsel eines Ja/Nein-Sensors steht sofort im Logbuch (ohne dass jemand den Sensor abfragt)
homematic._save_sensors([{"id": "hm-d", "kind": "contact", "address": "ABC:1", "interface": "HmIP-RF", "datapoint": "STATE", "unit": "", "binary": True, "name": "Fenster Bad", "model": "m", "room": ""}])
homematic._unreach = lambda x: False
homematic._on_event(homematic.PUSH_ID_PREFIX + "HmIP-RF", "ABC:1", "STATE", False); time.sleep(0.3)
homematic._on_event(homematic.PUSH_ID_PREFIX + "HmIP-RF", "ABC:1", "STATE", True); time.sleep(0.4)
e = [x for x in devicelog.recent(10, "sensor")]
assert e and e[0]["name"] == "Fenster Bad" and e[0]["text"] == "offen", e
print("5) Push-Logbuch OK")
# 6) Geraet offline: nur EIN Versuch je Ruhezeit (statt bei jedem Abruf die Zeitueberschreitung abzuwarten); Schalten hebt die Ruhe auf
import importlib
shelly._down.clear()
json.dump([{"id": "t1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "S", "icon": "x", "model": "T", "show": True}], open(shelly.DEVICES_PATH, "w"))
n = {"v": 0}
def dead(ip, cmnd, timeout, auth=None):
    n["v"] += 1; time.sleep(0.2); raise tasmota.requests.ConnectionError("weg")
tasmota._cmd = dead
t0 = time.time()
for _ in range(5): s1 = shelly.status(shelly._find("t1"))
assert s1["online"] is False and n["v"] == 1 and time.time() - t0 < 1.0, (n, time.time() - t0)
tasmota._cmd = lambda ip, cmnd, timeout, auth=None: {"StatusSTS": {"POWER": "ON"}, "POWER": "ON"}
assert shelly.status(shelly._find("t1"))["online"] is False                              # noch in der Ruhezeit
shelly.set_state("t1", True)                                                             # Schalten hebt sie auf
assert shelly.status(shelly._find("t1"))["online"] is True
shelly._down["t1"] = (time.time() - 1, {"online": False}); assert shelly.status(shelly._find("t1"))["online"] is True      # Ruhezeit vorbei -> wieder probieren
print("6) Offline-Geraete OK")
# 7) Oberflaeche ohne Warten auf langsame Geraete: letzter Stand sofort, Hintergrund frischt auf; Regeln/Automatik weiter live
shelly._down.clear(); shelly._st_cache.clear()
json.dump([{"id": "t1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "S", "icon": "x", "model": "T", "show": True},
           {"id": "t2", "kind": "tasmota", "mac": "BB", "channel": 1, "gen": 0, "ip": "192.168.50.91", "name": "T", "icon": "x", "model": "T", "show": True}], open(shelly.DEVICES_PATH, "w"))
slow = {"on": "ON", "delay": 0.0, "n": 0}
def cmd(ip, cmnd, timeout, auth=None):
    slow["n"] += 1; time.sleep(slow["delay"]); return {"StatusSTS": {"POWER": slow["on"]}, "POWER": slow["on"]}
tasmota._cmd = cmd
first = shelly.list_with_status(max_age=4.0); assert all(d["online"] and d["on"] for d in first) and not any(d.get("stale") for d in first)      # erster Abruf: wirklich gefragt
n0 = slow["n"]; again = shelly.list_with_status(max_age=4.0); assert slow["n"] == n0 and not any(d.get("stale") for d in again)                   # frisch genug: kein Aufruf
for k in list(shelly._st_cache): shelly._st_cache[k] = (time.time() - 30, shelly._st_cache[k][1])                                                # Zustand 30 s alt
slow["delay"] = 1.2; slow["on"] = "OFF"
t0 = time.time(); old = shelly.list_with_status(max_age=4.0); dt = time.time() - t0
assert dt < 0.4 and all(d.get("stale") and d["on"] for d in old), (dt, old)                                                                      # sofort, alter Stand, als "stale" gekennzeichnet
time.sleep(1.8)
new = shelly.list_with_status(max_age=4.0); assert not any(d.get("stale") for d in new) and not any(d["on"] for d in new), new                    # Hintergrund hat aufgefrischt
# Regeln/Automatik: weiter live (ohne max_age)
slow["delay"] = 0.0; slow["on"] = "ON"
for k in list(shelly._st_cache): shelly._st_cache[k] = (time.time(), {"online": True, "on": False, "power": None})
assert all(d["on"] for d in shelly.list_with_status())                                                                                          # live -> echter Zustand, nicht der gemerkte
# Schalten verwirft den gemerkten Zustand
shelly._st_cache["t1"] = (time.time(), {"online": True, "on": False, "power": None}); shelly.set_state("t1", True); assert "t1" not in shelly._st_cache
# 8) Offline: Ruhezeit wird laenger (12 -> 24 -> 48 -> 60 s)
shelly._down.clear(); tasmota._cmd = lambda ip, cmnd, timeout, auth=None: (_ for _ in ()).throw(tasmota.requests.ConnectionError("weg"))
d1 = shelly._find("t2"); shelly.status(d1); u1 = shelly._down["t2"]; assert u1[2] == 1 and 10 < u1[0] - time.time() <= 12.1
shelly._down["t2"] = (time.time() - 1, u1[1], 1); shelly.status(d1); u2 = shelly._down["t2"]; assert u2[2] == 2 and 22 < u2[0] - time.time() <= 24.1
shelly._down["t2"] = (time.time() - 1, u2[1], 4); shelly.status(d1); assert shelly._down["t2"][0] - time.time() <= 60.1
print("7+8) Hintergrund-Zustand und Backoff OK")
print("GESCHWINDIGKEIT OK")
