"""Offene Lese-Schnittstelle /api/v1: Schluessel, nur LAN (auch gegen Tunnel), nur lesen, Auswahl, Zeitpunkte, Verwaltung nur Admin."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import extapi, shelly, homematic, virtual, auth
from auth import UserStore

extapi.KEYS_PATH = os.path.join(tmp, "api_keys.json"); extapi.CHANGES_PATH = os.path.join(tmp, "api_changes.json")

# ---- reine Logik
for ip in ("192.168.50.5", "10.1.2.3", "172.16.0.9", "127.0.0.1", "::1", "fe80::1", "fd00::5", "::ffff:192.168.1.1"):
    assert extapi._private(ip), ip
for ip in ("8.8.8.8", "100.64.0.1", "2a00:1450::1", "", "kaputt", "::ffff:8.8.8.8"):
    assert not extapi._private(ip), ip
H = lambda **kw: {k.replace("_", "-"): v for k, v in kw.items()}
assert extapi.lan_request_ok({}, "192.168.50.20")
assert not extapi.lan_request_ok({}, "8.8.8.8")
assert not extapi.lan_request_ok(H(CF_Connecting_IP="1.2.3.4"), "127.0.0.1")                     # Tunnel: kommt von localhost, aber mit Cloudflare-Kopf
assert not extapi.lan_request_ok({"CF-Ray": "abc"}, "127.0.0.1")
assert not extapi.lan_request_ok({"X-Forwarded-For": "203.0.113.5"}, "127.0.0.1")
assert not extapi.lan_request_ok({"X-Forwarded-For": "192.168.50.9, 203.0.113.5"}, "127.0.0.1")
assert extapi.lan_request_ok({"X-Forwarded-For": "192.168.50.9"}, "127.0.0.1")                      # Proxy im LAN ist in Ordnung
assert not extapi.lan_request_ok({"Forwarded": 'for=203.0.113.9;proto=https'}, "127.0.0.1")
assert extapi.normalize_allow(["192.168.50.40", " 192.168.50.0/24 ", "192.168.50.40"]) == ["192.168.50.40", "192.168.50.0/24"]
try:
    extapi.normalize_allow(["hallo"]); raise AssertionError("ungueltig")
except extapi.ApiKeyError:
    pass
assert extapi.normalize_refs(["sensor:a", "sensor:a", "foo:b", "device:", "virtual:x y", "device:ok-1"]) == ["sensor:a", "device:ok-1"]
print("Logik OK")

# ---- Daten
json.dump([{"id": "lampe", "name": "Flurlicht", "kind": "zigbee", "uniqueid": "x", "icon": "💡", "ip": "1.2.3.4", "model": "m", "show": False, "password": "geheim", "pin_hash": "xx"},
           {"id": "boiler", "name": "Boiler", "kind": "shelly", "ip": "1.2.3.5", "icon": "🔌", "model": "m", "show": True}], open(shelly.DEVICES_PATH, "w"))
state = {"lampe": True}
shelly.status = lambda d: {"online": d["id"] != "boiler", "on": state.get(d["id"], False), "power": 12.5 if d["id"] == "lampe" else None}
homematic._save_sensors([{"id": "tor", "name": "Hallentor", "kind": "contact", "binary": True, "show": False, "source": "zigbee", "address": "a", "model": "m", "room": "Halle"},
                         {"id": "tor2", "name": "Seitentür", "kind": "contact", "binary": True, "invert": True, "source": "zigbee", "address": "c", "model": "m"},
                         {"id": "temp", "name": "Außen", "kind": "temperature", "binary": False, "unit": "°C", "source": "homematic", "address": "b", "model": "m"},
                         {"id": "cam-p", "name": "Hof – Person", "kind": "motion", "binary": True, "source": "camera", "datapoint": "people", "address": "c1", "model": "R"},
                         {"id": "cam-k", "name": "Haustür – Klingel", "kind": "motion", "binary": True, "source": "camera", "datapoint": "visitor", "address": "c1", "model": "R"},
                         {"id": "cam-m", "name": "Hof – Bewegung", "kind": "motion", "binary": True, "source": "camera", "datapoint": "md", "address": "c1", "model": "R"},
                         {"id": "tot", "name": "Tot", "kind": "contact", "binary": True, "source": "zigbee", "address": "d", "model": "m"}])
vals = {"cam-p": True, "cam-k": False, "cam-m": False, "tor": True, "tor2": True, "temp": 4.5, "tot": None}
homematic.read_values = lambda items: {s["id"]: vals.get(s["id"]) for s in items}
vb = virtual.add("Garagentor", "button"); vs = virtual.add("Licht", "switch")

webapp.users = UserStore(os.path.join(tmp, "users_api.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "settings_geraete": "write", "settings_system": "write"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")
anon = webapp.app.test_client()

# ---- Verwaltung: nur Administratoren
assert A.get("/api/apikeys").get_json() == []
ib = A.get("/api/apikeys/info"); assert ib.status_code == 200
bu = ib.get_json()["base_url"]; assert bu == "" or (bu.startswith("http://") and "127." not in bu), bu          # Heimnetz-Adresse, nie die Internet-Adresse
assert I.get("/api/apikeys/info").status_code == 403 and anon.get("/api/apikeys/info").status_code in (401, 302)
r = A.get("/api/apikeys/info", headers={"Host": "meinhaus.example.de"}); assert "example.de" not in r.get_data(as_text=True)
assert I.get("/api/apikeys").status_code == 403 and I.post("/api/apikeys", json={"name": "x"}).status_code == 403
assert anon.get("/api/apikeys").status_code in (401, 302)
assert A.post("/api/apikeys", json={"name": " "}).status_code == 400
r = A.post("/api/apikeys", json={"name": "Info-Monitor", "items": ["sensor:tor", "sensor:tor2", "sensor:temp", "sensor:tot", "sensor:cam-p", "sensor:cam-k", "sensor:cam-m"], "allow": ["192.168.50.0/24", "127.0.0.1"]})
assert r.status_code == 201, r.get_data(as_text=True)
k1 = r.get_json(); tok1 = k1["token"]; kid1 = k1["key"]["id"]
assert tok1.startswith("bnxapi_") and "hash" not in k1["key"] and tok1 not in json.dumps(A.get("/api/apikeys").get_json())
assert tok1 not in open(extapi.KEYS_PATH, encoding="utf-8").read()                                  # nur der Hash liegt auf der Platte
r = A.post("/api/apikeys", json={"name": "Alles", "all": True}); k2 = r.get_json(); tok2 = k2["token"]
assert A.post("/api/apikeys", json={"name": "X", "allow": ["quatsch"]}).status_code == 400

B = lambda t: {"Authorization": "Bearer " + t}
G = lambda path, t=None, c=None, **kw: (c or anon).get(path, headers=B(t) if t else {}, **kw)

# ---- Zugriff
assert G("/api/v1/items").status_code == 401 and G("/api/v1/items", "bnxapi_falsch").status_code == 401
assert G("/api/v1/items", "bnx_" + tok1[7:]).status_code == 401
assert A.get("/api/v1/items").status_code == 401                                                     # eine angemeldete Sitzung ersetzt keinen Schluessel
r = G("/api/v1/", tok1); assert r.status_code == 200 and r.get_json()["api"] == "BlueNexus" and r.get_json()["v"] == 1, r.get_data(as_text=True)
assert r.headers["Cache-Control"] == "no-store"
assert G("/api/v1", tok1).status_code == 200

# ---- Auswahl und Inhalt (Schluessel 1 = nur die vier Sensoren)
r = G("/api/v1/items", tok1); assert r.status_code == 200
d = r.get_json(); its = {i["id"]: i for i in d["items"]}
assert sorted(its) == ["cam-k", "cam-m", "cam-p", "temp", "tor", "tor2", "tot"], sorted(its)
assert its["tor"]["state"] == "open" and its["tor"]["text"] == "offen" and its["tor"]["value"] is True and its["tor"]["online"] is True and its["tor"]["room"] == "Halle"
assert its["tor2"]["state"] == "closed" and its["tor2"]["text"] == "geschlossen" and its["tor2"]["value"] is True       # umgekehrt eingestellt: gleiche Rohwerte, andere Worte
assert its["temp"]["value"] == 4.5 and its["temp"]["text"] == "4,5 °C" and its["temp"]["unit"] == "°C" and its["temp"]["state"] is None
assert its["tot"]["online"] is False and its["tot"]["value"] is None and its["tot"]["text"] == "kein Wert"
for i in d["items"]:
    assert i["ref"] == "sensor:" + i["id"] and i["changed_at"] and i["updated_at"] and "T" in i["changed_at"]
blob = json.dumps(d)
assert "1.2.3.4" not in blob and "geheim" not in blob and "pin_hash" not in blob and "address" not in blob and "uniqueid" not in blob
assert (its["cam-p"]["state"], its["cam-p"]["text"]) == ("person", "Person erkannt")
assert (its["cam-k"]["state"], its["cam-k"]["text"]) == ("none", "nicht geklingelt") and (its["cam-m"]["text"]) == "keine Bewegung"
# gefiltert
assert [i["id"] for i in G("/api/v1/items?type=sensor&ref=sensor:tor,sensor:temp", tok1).get_json()["items"]] == ["tor", "temp"]
assert G("/api/v1/items?type=device", tok1).get_json()["items"] == []                                  # nicht freigegeben
assert G("/api/v1/items?type=quatsch", tok1).status_code == 400
r = G("/api/v1/items/sensor:tor", tok1); assert r.status_code == 200 and r.get_json()["item"]["name"] == "Hallentor"
assert G("/api/v1/items/device:lampe", tok1).status_code == 404 and G("/api/v1/items/sensor:gibtsnicht", tok1).status_code == 404

# ---- Schluessel 2 = alles
d = G("/api/v1/items", tok2).get_json(); ids = sorted(i["ref"] for i in d["items"])
assert ids == sorted(["sensor:cam-p", "sensor:cam-k", "sensor:cam-m", "sensor:tor", "sensor:tor2", "sensor:temp", "sensor:tot", "device:lampe", "device:boiler", "virtual:" + vb["id"], "virtual:" + vs["id"]]), ids
its = {i["ref"]: i for i in d["items"]}
assert its["device:lampe"]["state"] == "on" and its["device:lampe"]["power_w"] == 12.5 and its["device:lampe"]["switchable"] is True
assert its["device:boiler"]["online"] is False and its["device:boiler"]["state"] is None and its["device:boiler"]["text"] == "nicht erreichbar"
assert its["virtual:" + vb["id"]]["state"] == "button" and its["virtual:" + vs["id"]]["state"] == "off"
blob = json.dumps(d)
assert "password" not in blob and "1.2.3.5" not in blob and "pin" not in blob.replace("pinned", "")

# ---- nur lesen
for m in ("post", "put", "patch", "delete"):
    rr = getattr(anon, m)("/api/v1/items", headers=B(tok2)); assert rr.status_code in (401, 405), (m, rr.status_code, rr.get_data(as_text=True)[:200])
assert anon.post("/api/v1/items/device:lampe", headers=B(tok2)).status_code in (401, 405)

# ---- nur LAN: Tunnel / Internet
assert anon.get("/api/v1/items", headers={**B(tok2), "CF-Connecting-IP": "203.0.113.7"}).status_code == 403      # ueber den Tunnel (kommt von localhost!)
assert anon.get("/api/v1/items", headers={**B(tok2), "CF-Ray": "8a1b2c"}).status_code == 403
assert anon.get("/api/v1/items", headers={**B(tok2), "X-Forwarded-For": "203.0.113.7"}).status_code == 403
assert anon.get("/api/v1/items", headers=B(tok2), environ_overrides={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403   # direkt aus dem Internet
assert anon.get("/api/v1/", headers=B("bnxapi_falsch"), environ_overrides={"REMOTE_ADDR": "8.8.8.8"}).status_code == 403   # auch der Fehlschlag verraet nichts
assert anon.get("/api/v1/items", headers=B(tok2), environ_overrides={"REMOTE_ADDR": "192.168.50.77"}).status_code == 200
# erlaubte Absender: Schluessel 1 nur aus 192.168.50.0/24 und 127.0.0.1
assert anon.get("/api/v1/items", headers=B(tok1), environ_overrides={"REMOTE_ADDR": "192.168.50.50"}).status_code == 200
assert anon.get("/api/v1/items", headers=B(tok1), environ_overrides={"REMOTE_ADDR": "192.168.3.50"}).status_code == 403
assert anon.get("/api/v1/items", headers=B(tok1), environ_overrides={"REMOTE_ADDR": "10.0.0.5"}).status_code == 403

# ---- Bremse gegen Raten
bad = [anon.get("/api/v1/items", headers=B("bnxapi_x"), environ_overrides={"REMOTE_ADDR": "192.168.9.9"}).status_code for _ in range(12)]
assert bad[:10] == [401] * 10 and bad[10] == 429, bad
assert anon.get("/api/v1/items", headers=B(tok2), environ_overrides={"REMOTE_ADDR": "192.168.9.9"}).status_code == 429       # auch der richtige wartet dann

# ---- Zeitpunkt der letzten Aenderung
t0 = G("/api/v1/items/sensor:tor", tok1).get_json()["item"]["changed_at"]
time.sleep(1.2)
assert G("/api/v1/items/sensor:tor", tok1).get_json()["item"]["changed_at"] == t0                       # unveraendert -> gleicher Zeitpunkt
vals["tor"] = False
time.sleep(0.1)
it = G("/api/v1/items/sensor:tor", tok1).get_json()["item"]
assert it["state"] == "closed" and it["changed_at"] > t0, (it, t0)
assert extapi.sample_once() > 0
extapi._track_flush(force=True)
saved = json.load(open(extapi.CHANGES_PATH, encoding="utf-8")); assert "sensor:tor" in saved
extapi._track.clear(); extapi._track_loaded = False                                                    # "Neustart"
assert G("/api/v1/items/sensor:tor", tok1).get_json()["item"]["changed_at"] == it["changed_at"]

# ---- Verwaltung: aendern, neuer Schluessel, loeschen
r = A.patch("/api/apikeys/" + kid1, json={"name": "Monitor 2", "items": ["sensor:temp"], "allow": []}); assert r.status_code == 200
assert [i["id"] for i in G("/api/v1/items", tok1).get_json()["items"]] == ["temp"]
assert anon.get("/api/v1/items", headers=B(tok1), environ_overrides={"REMOTE_ADDR": "10.0.0.5"}).status_code == 200      # Absenderliste geleert
r = A.post("/api/apikeys/" + kid1 + "/token"); tok1b = r.get_json()["token"]; assert tok1b != tok1
assert G("/api/v1/items", tok1).status_code == 401 and G("/api/v1/items", tok1b).status_code == 200
assert A.patch("/api/apikeys/gibtsnicht", json={"name": "x"}).status_code == 404
assert I.patch("/api/apikeys/" + kid1, json={"name": "x"}).status_code == 403 and I.delete("/api/apikeys/" + kid1).status_code == 403
assert A.delete("/api/apikeys/" + kid1).status_code == 200 and G("/api/v1/items", tok1b).status_code == 401
webapp.note_failed_attempt  # (Bremse ist je Adresse; nichts weiter)

# ---- Teilen bleibt unberuehrt: eigener Pfad, anderer Schluessel gilt dort nicht
assert anon.get("/share/v1/items", headers=B(tok2)).status_code == 401
print("EXTAPI OK")
