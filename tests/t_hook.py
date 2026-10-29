"""Schaltvorgaenge von aussen (Lichtschranke/Taster): Tasmota-Meldungs-Regel, Hook mit Schluessel, Echo-Unterdrueckung, Homematic-Push."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, tasmota, homematic, devicelog, extapi
from auth import UserStore
store.module_on = lambda n, cfg=None: True
webapp.opslog.log = lambda *a, **k: None
extapi.lan_ip = lambda: "192.168.50.40"
json.dump([{"id": "tasmota-AA11-1", "kind": "tasmota", "mac": "AA11", "channel": 1, "gen": 0, "ip": "192.168.50.90", "name": "Lichtschranke", "icon": "x", "model": "T", "show": True},
           {"id": "tasmota-AA11-2", "kind": "tasmota", "mac": "AA11", "channel": 2, "gen": 0, "ip": "192.168.50.90", "name": "Hoftor K2", "icon": "x", "model": "T", "show": True},
           {"id": "tasmota-BB22-1", "kind": "tasmota", "mac": "BB22", "channel": 1, "gen": 0, "ip": "192.168.50.91", "name": "Andere", "icon": "x", "model": "T", "show": True},
           {"id": "hm-1", "kind": "homematic", "address": "HM1:1", "interface": "HmIP-RF", "datapoint": "STATE", "name": "Flurlicht", "icon": "x", "model": "m", "show": True}], open(shelly.DEVICES_PATH, "w"))
sent = []
def fake(ip, cmnd, timeout, auth=None):
    sent.append((ip, cmnd)); return {"POWER": "ON"}
tasmota._cmd = fake
webapp.users = UserStore(os.path.join(tmp, "u_hook.py.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})
ents = lambda: devicelog.recent(20)
H = {"X-Forwarded-For": "192.168.50.50"}

# 1) Einrichten: Regel 3 mit allen Relaiskanaelen des Geraets, Schluessel nie in der Geraeteliste
assert L.post("/api/shelly/tasmota-AA11-1/hook").status_code == 403
r = A.post("/api/shelly/tasmota-AA11-1/hook"); assert r.status_code == 200 and r.get_json()["hook"] is True, r.get_data(as_text=True)
ip, cmnd = sent[-1]; assert ip == "192.168.50.90" and cmnd.startswith("Backlog Rule3 ON Power1#State DO WebSend [192.168.50.40:") and "ON Power2#State" in cmnd and cmnd.endswith("; Rule3 1"), cmnd
assert cmnd.count("/hook/tas/AA11/") == 2 and "%value%" in cmnd and len(cmnd) < 520
devs = {d["id"]: d for d in shelly.load_devices()}; tok = devs["tasmota-AA11-1"]["hook_token"]
assert devs["tasmota-AA11-2"]["hook"] and devs["tasmota-AA11-2"]["hook_token"] == tok and not devs["tasmota-BB22-1"].get("hook")
pub = A.get("/api/shelly?light=1").get_json(); assert all("hook_token" not in d for d in pub) and next(d for d in pub if d["id"] == "tasmota-AA11-2")["hook"] is True and tok not in json.dumps(pub)
assert A.post("/api/shelly/hm-1/hook").status_code == 400                                            # nur Tasmota
print("1) Einrichten OK")

# 2) Meldung des Geraets: nur Heimnetz + Schluessel; protokolliert als "von aussen"; Anzeige gleich richtig
c = webapp.app.test_client()
url = lambda ch, t, s: f"/hook/tas/AA11/{ch}/{t}/{s}"
assert c.get(url(1, "falsch", "ON"), headers=H).status_code == 404 and c.get(url(1, tok, "ON"), headers={"CF-Connecting-IP": "203.0.113.5"}).status_code == 404       # falscher Schluessel / aus dem Internet
assert c.get(url(1, tok, "VIELLEICHT"), headers=H).status_code == 400 and not ents()
assert c.get(url(1, tok, "ON"), headers=H).status_code == 204
e = ents()[0]; assert e["ref"] == "device:tasmota-AA11-1" and e["text"] == "eingeschaltet" and e["by"] == devicelog.EXTERNAL and e["name"] == "Lichtschranke", e
assert shelly._st_cache["tasmota-AA11-1"][1]["on"] is True
time.sleep(1.1); assert c.get(url(1, tok, "0"), headers=H).status_code == 204 and ents()[0]["text"] == "ausgeschaltet"
assert c.get(f"/hook/tas/BB22/1/{tok}/ON", headers=H).status_code == 404                              # Geraet ohne Meldung / fremder Schluessel
n = len(ents()); assert c.post(url(2, tok, "ON"), headers=H).status_code == 204 and len(ents()) == n + 1       # POST geht auch
print("2) Hook OK")

# 3) Echo: schaltet die APP selbst, meldet das Geraet gleich danach zurueck - das ist KEIN "von aussen"
n = len(ents()); shelly.set_state("tasmota-AA11-1", True)
assert len(ents()) == n + 1 and ents()[0]["by"] != devicelog.EXTERNAL
assert c.get(url(1, tok, "ON"), headers=H).status_code == 204 and len(ents()) == n + 1, "Echo wurde doppelt protokolliert"
devicelog._app_act["device:tasmota-AA11-1"] -= 20                                                     # nach der Echo-Zeit zaehlt es wieder
time.sleep(1.1); assert c.get(url(1, tok, "OFF"), headers=H).status_code == 204 and ents()[0]["by"] == devicelog.EXTERNAL and ents()[0]["text"] == "ausgeschaltet"
time.sleep(0.1); n = len(ents()); c.get(url(1, tok, "OFF"), headers=H); assert len(ents()) == n          # doppelte Meldung desselben Zustands innerhalb 1 s
print("3) Echo OK")

# 4) Dauerbeschuss mit falschem Schluessel wird gebremst
for i in range(12): c.get(url(1, f"x{i}", "ON"), headers={"X-Forwarded-For": "192.168.50.77"})
assert c.get(url(1, "x", "ON"), headers={"X-Forwarded-For": "192.168.50.77"}).status_code == 429
print("4) Bremse OK")

# 5) Ausschalten der Meldung
r = A.delete("/api/shelly/tasmota-AA11-1/hook"); assert r.status_code == 200 and sent[-1][1] == "Rule3 0", sent[-1]
assert not any(d.get("hook") for d in shelly.load_devices() if d.get("mac") == "AA11")
assert c.get(url(1, tok, "ON"), headers={"X-Forwarded-For": "192.168.50.51"}).status_code == 404       # ohne Meldung keine Annahme mehr
print("5) Ausschalten OK")

# 6) Homematic: Taster/Funk am Schalt-Aktor -> "von aussen"; eigene Bedienung -> nicht
homematic._unreach = lambda x: False
pre = homematic.PUSH_ID_PREFIX + "HmIP-RF"
homematic._on_event(pre, "HM1:1", "STATE", False); time.sleep(0.4)                                      # Ausgangszustand merken
n = len(ents()); homematic._on_event(pre, "HM1:1", "STATE", True); time.sleep(0.5)
e = ents()[0]; assert len(ents()) == n + 1 and e["ref"] == "device:hm-1" and e["text"] == "eingeschaltet" and e["by"] == devicelog.EXTERNAL, e
devicelog.note_app_action("device:hm-1"); n = len(ents()); homematic._on_event(pre, "HM1:1", "STATE", False); time.sleep(0.5)
assert len(ents()) == n, "Echo einer eigenen Bedienung darf nicht als 'von aussen' stehen"
print("6) Homematic OK")
# 7) Zustand eines Geraets als Sensor (Torstatus: AN = geschlossen)
state = {"on": "ON", "fail": False}
def cmd2(ip, cmnd, timeout, auth=None):
    if state["fail"]: raise tasmota.requests.ConnectionError("weg")
    return {"StatusSTS": {"POWER2": state["on"]}, "POWER2": state["on"], "POWER": state["on"]}
tasmota._cmd = cmd2
assert L.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"}).status_code == 403
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "gibtsnicht"}).status_code == 400
assert A.post("/api/shelly/nix/as-sensor", json={"preset": "contact_closed"}).status_code == 400
r = A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed", "name": "Hoftor Zustand"}); assert r.status_code == 201 and r.get_json()["name"] == "Hoftor Zustand", r.get_data(as_text=True)
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"}).status_code == 400                    # nur einmal
dv = next(d for d in shelly.load_devices() if d["id"] == "tasmota-AA11-2"); assert dv["as_sensor"] == "devS-tasmota-AA11-2" and dv["switchable"] is False
sn = next(s for s in homematic.load_sensors() if s["id"] == "devS-tasmota-AA11-2"); assert sn["kind"] == "contact" and sn.get("dev_inv") is True and sn.get("invert") is True and sn["dev_v2"] and sn["source"] == "device" and sn["users"] == []
val = lambda: next(s for s in A.get("/api/sensors").get_json() if s["id"] == sn["id"])["value"]
shelly._st_cache.clear(); homematic._value_cache.clear(); shelly._down.clear()
assert val() is True                                                                                   # Relais AN -> Tor geschlossen: TRUE = geschlossen (wie bei Fenstern/Tueren ueblich)
state["on"] = "OFF"; shelly._st_cache.clear(); homematic._value_cache.clear(); assert val() is False   # AUS -> offen
state["fail"] = True; shelly._st_cache.clear(); shelly._down.clear(); homematic._value_cache.clear(); assert val() is None   # nicht erreichbar -> unbekannt
state["fail"] = False; shelly._down.clear()
# Meldung von aussen steht mit den Worten des Sensors im Logbuch (statt "eingeschaltet")
shelly.tasmota_hook_set("tasmota-AA11-1", "192.168.50.40:5005")
tok2 = next(d for d in shelly.load_devices() if d["id"] == "tasmota-AA11-2")["hook_token"]
devicelog._app_act.clear(); devicelog._sens_last.clear()
n = len(ents()); assert c.get(f"/hook/tas/AA11/2/{tok2}/ON", headers=H).status_code == 204
e = ents()[0]; assert e["cat"] == "sensor" and e["name"] == "Hoftor Zustand" and e["text"] == "geschlossen" and e["by"] == "Sensor", e
assert not any(x["ref"] == "device:tasmota-AA11-2" for x in ents()[:2])
time.sleep(1.1); c.get(f"/hook/tas/AA11/2/{tok2}/OFF", headers=H); assert ents()[0]["text"] == "offen"
c.get(f"/hook/tas/AA11/2/{tok2}/OFF", headers=H); n2 = len(ents()); time.sleep(1.1); c.get(f"/hook/tas/AA11/2/{tok2}/OFF", headers=H); assert len(ents()) == n2          # gleicher Zustand: kein neuer Eintrag
print("7) Zustand als Sensor OK")
# 8) Korrigieren und Entfernen (der Knopf bleibt: Sensor aendern oder wieder loeschen)
sid = "devS-tasmota-AA11-2"
assert L.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "motion"}).status_code == 403 and L.delete("/api/shelly/tasmota-AA11-2/as-sensor").status_code == 403
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "quatsch"}).status_code == 400
r = A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "motion", "name": "Lichtschranke Hof"}); assert r.status_code == 200 and r.get_json()["preset"] == "motion", r.get_data(as_text=True)
sn = next(s for s in homematic.load_sensors() if s["id"] == sid); assert sn["kind"] == "motion" and "invert" not in sn and "dev_inv" not in sn and sn["name"] == "Lichtschranke Hof"
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_open"}).get_json()["preset"] == "contact_open"
assert shelly.sensor_preset_of(next(s for s in homematic.load_sensors() if s["id"] == sid)) == "contact_open"
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"}).get_json()["preset"] == "contact_closed"
pub = {d["id"]: d for d in A.get("/api/shelly?light=1").get_json()}; assert pub["tasmota-AA11-2"]["as_sensor"] == sid           # Knopf sieht: es gibt einen Sensor
r = A.delete("/api/shelly/tasmota-AA11-2/as-sensor", json={"unlock": True}); assert r.status_code == 200
assert not any(s["id"] == sid for s in homematic.load_sensors()); dv = next(d for d in shelly.load_devices() if d["id"] == "tasmota-AA11-2"); assert "as_sensor" not in dv and dv["switchable"] is True
assert A.delete("/api/shelly/tasmota-AA11-2/as-sensor").status_code == 400 and A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "motion"}).status_code == 400
# nochmal anlegen, diesmal in der Sensorliste loeschen: Verknuepfung am Geraet faellt weg, Geraet bleibt wie es ist
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"}).status_code == 201
assert A.delete("/api/sensors/" + sid).status_code == 200
dv = next(d for d in shelly.load_devices() if d["id"] == "tasmota-AA11-2"); assert "as_sensor" not in dv and dv["switchable"] is False
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "input", "lock_switch": False}).status_code == 201                    # und kann neu angelegt werden
assert next(d for d in shelly.load_devices() if d["id"] == "tasmota-AA11-2")["switchable"] is False                                         # bleibt wie zuvor
# 9) Richtige Worte + "Umkehren" des Sensors getrennt von der Zuordnung; Altbestand (erste Fassung, Umkehren statt Zuordnung) wird richtiggestellt
A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"}) if not any(s["id"] == sid for s in homematic.load_sensors()) else None
A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "contact_closed"})
state["on"] = "ON"; shelly._st_cache.clear(); homematic._value_cache.clear(); shelly._down.clear()
api = lambda: next(s for s in A.get("/api/sensors").get_json() if s["id"] == sid)
assert api()["value"] is True and api()["invert"] is True                                           # AN = geschlossen = TRUE (Anzeige: "TRUE - geschlossen", Dashboard gruen)
state["on"] = "OFF"; shelly._st_cache.clear(); homematic._value_cache.clear(); assert api()["value"] is False     # AUS = offen
state["on"] = "ON"; shelly._st_cache.clear(); homematic._value_cache.clear()
assert A.patch("/api/sensors/" + sid, json={"invert": False}).status_code == 200                                    # Anwender dreht "Umkehren" weg: TRUE/FALSE tauschen, die Bedeutung (geschlossen bei AN) bleibt
homematic._value_cache.clear(); assert api()["value"] is False and api()["dev_inv"] is True and not api().get("invert")
A.patch("/api/sensors/" + sid, json={"invert": True}); homematic._value_cache.clear(); assert api()["value"] is True
alt = [{"id": "devS-x", "kind": "contact", "source": "device", "address": "tasmota-AA11-2", "interface": "device", "datapoint": "", "binary": True, "unit": "", "model": "T", "room": "", "name": "Alt", "invert": True},
       {"id": "devS-y", "kind": "motion", "source": "device", "address": "tasmota-AA11-1", "interface": "device", "datapoint": "", "binary": True, "unit": "", "model": "T", "room": "", "name": "Alt2"}]
homematic._save_sensors(alt); assert shelly.migrate_device_sensors() == 2
fx = {s["id"]: s for s in homematic.load_sensors()}; assert fx["devS-x"]["dev_inv"] is True and "invert" not in fx["devS-x"] and "dev_inv" not in fx["devS-y"] and fx["devS-x"]["dev_fixed"]
assert shelly.migrate_device_sensors() == 0                                                         # nur einmal
assert shelly.migrate_device_sensors_v2() == 2                                                      # zweite Korrektur: AN = geschlossen soll TRUE sein
fx = {s["id"]: s for s in homematic.load_sensors()}; assert fx["devS-x"]["invert"] is True and fx["devS-x"]["dev_inv"] is True and "invert" not in fx["devS-y"] and fx["devS-x"]["dev_v2"]
assert shelly.migrate_device_sensors_v2() == 0
fx["devS-x"]["invert"] = False; homematic._save_sensors(list(fx.values())); assert shelly.migrate_device_sensors() == 0 and shelly.migrate_device_sensors_v2() == 0 and next(s for s in homematic.load_sensors() if s["id"] == "devS-x")["invert"] is False   # spaeteres "Umkehren" bleibt
# Logbuch-Worte folgen der Anzeige: bei "Umkehren" (TRUE = geschlossen) steht fuer TRUE "geschlossen", nicht "offen"
w = {"kind": "contact", "invert": True}; assert devicelog.sensor_word(w, True) == "geschlossen" and devicelog.sensor_word(w, False) == "offen"
w = {"kind": "contact"}; assert devicelog.sensor_word(w, True) == "offen" and devicelog.sensor_word(w, False) == "geschlossen"
w = {"kind": "motion"}; assert devicelog.sensor_word(w, True) == "Bewegung erkannt" and devicelog.sensor_word(w, False) is None
print("9) Zuordnung/Umkehren/Migration OK")
print("8) Aendern/Entfernen OK")
# 10) Zustand aus der Leistung (Bewegungsmelder-Lampe hinter einem Messrelais): Wahr, wenn mehr als die Schwelle fliesst
pw = {"w": 0.0, "fail": False, "energy": True}
def cmd3(ip, cmnd, timeout, auth=None):
    if pw["fail"]: raise tasmota.requests.ConnectionError("weg")
    d = {"StatusSTS": {"POWER2": "ON"}, "POWER2": "ON", "POWER": "ON"}
    if pw["energy"]: d["StatusSNS"] = {"ENERGY": {"Power": pw["w"]}}
    return d
tasmota._cmd = cmd3
for s_ in [x for x in homematic.load_sensors() if x["address"] == "tasmota-AA11-2"]: A.delete("/api/sensors/" + s_["id"])
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "running", "power_min": "abc"}).status_code == 400
assert A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "running", "power_min": -3}).status_code == 400
r = A.post("/api/shelly/tasmota-AA11-2/as-sensor", json={"preset": "running", "name": "Garagenlampe", "power_min": "5,5", "lock_switch": False}); assert r.status_code == 201, r.get_data(as_text=True)
sid = "devS-tasmota-AA11-2"; sn = next(s for s in homematic.load_sensors() if s["id"] == sid); assert sn["kind"] == "running" and sn["power_min"] == 5.5 and "dev_inv" not in sn and "invert" not in sn
def rd(w=None, **kw):
    pw.update(kw); 
    if w is not None: pw["w"] = w
    shelly._st_cache.clear(); homematic._value_cache.clear(); shelly._down.clear()
    return next(x for x in A.get("/api/sensors").get_json() if x["id"] == sid)["value"]
assert rd(0.0) is False and rd(5.5) is False and rd(5.6) is True and rd(120.0) is True and rd(2.0) is False                  # Schwelle: mehr als 5,5 W
assert rd(fail=True) is None; pw["fail"] = False                                                                                 # nicht erreichbar -> unbekannt
assert rd(energy=False) is None; pw["energy"] = True                                                                           # keine Leistungsmessung am Geraet -> unbekannt (nicht "aus")
# Logbuch: Wechsel mit Worten "an"/"aus"
devicelog._sens_last.clear(); rd(0.0); rd(40.0)
e = ents()[0]; assert e["cat"] == "sensor" and e["name"] == "Garagenlampe" and e["text"] == "an", e
rd(1.0); assert ents()[0]["text"] == "aus"
# Aendern: Schwelle anderes, wieder auf Schaltzustand zurueck
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"power_min": "50"}).status_code == 200 and rd(40.0) is False and rd(60.0) is True
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"power_min": "kaputt"}).status_code == 400
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"name": "Nur Name"}).status_code == 200 and next(x for x in homematic.load_sensors() if x["id"] == sid).get("power_min") == 50.0       # ohne Angabe bleibt sie
assert A.patch("/api/shelly/tasmota-AA11-2/as-sensor", json={"power_min": None}).status_code == 200 and "power_min" not in next(x for x in homematic.load_sensors() if x["id"] == sid)
assert rd(0.0) is True                                                                                                         # wieder am Schaltzustand: Relais AN -> wahr
print("10) Leistungs-Schwelle OK")
print("VON-AUSSEN OK")
