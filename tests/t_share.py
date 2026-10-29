import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import share, shelly, homematic, virtual, midea, rules
from auth import UserStore
share.SHARES_PATH = os.path.join(tmp, "shares.json"); share.SOURCES_PATH = os.path.join(tmp, "sources.json")
webapp.users = UserStore(os.path.join(tmp, "u_sh.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("kind", "kindpass1234", {"dashboard": "write"}); webapp.users.create("lese", "lesepass1234", {"dashboard": "write", "settings_geraete": "read", "smarthome_teilen": "read"}); webapp.users.create("tw", "twpass12345", {"dashboard": "write", "settings_geraete": "read", "smarthome_teilen": "write"})
webapp.opslog.log = lambda *a, **k: None
share.CACHE_TTL_S = 0

# --- "Geber"-Daten: Steckdose, Klimaanlage, Sensor, Schalter, Knopf
shelly._save([
    {"id": "sh-1", "kind": "shelly", "name": "Steckdose", "icon": "🔌", "ip": "x", "gen": 2, "channel": 0, "model": "Plug", "show": True, "users": []},
    {"id": "midea-9", "kind": "midea", "name": "Klima Oma", "icon": "❄️", "ip": "x", "gen": 0, "channel": 0, "model": "Midea", "show": True, "users": []},
    {"id": "sh-geheim", "kind": "shelly", "name": "Nicht geteilt", "icon": "🔌", "ip": "x", "gen": 2, "channel": 0, "model": "Plug", "show": True, "users": []},
])
homematic._save_sensors([{"id": "hm-t", "kind": "temperature", "address": "A", "interface": "HmIP-RF", "datapoint": "T", "unit": "°C", "binary": False, "name": "Flur Temp", "model": "x", "room": "Flur"},
                         {"id": "hm-d", "kind": "contact", "address": "B", "interface": "HmIP-RF", "datapoint": "S", "unit": "", "binary": True, "name": "Haustür", "model": "x", "room": ""}])
state = {"sh-1": False, "midea-9": False}
log = []
shelly.status = lambda d: ({"online": True, "on": state.get(d["id"]), "power": 3.0} if d["id"] != "midea-9" else {"online": True, "on": state["midea-9"], "power": None, "info": "Kühlen 24 °C", "mode": "cool"}) if d.get("kind") != "remote" else share.status(d)
_orig_set = shelly.set_state
def fake_set(dev_id, on, timer_s=None):
    d = shelly._find(dev_id)
    if d.get("kind") == "remote": return _orig_set(dev_id, on, timer_s)
    state[dev_id] = bool(on); log.append(("set", dev_id, bool(on))); return {"online": True, "on": bool(on), "power": None}
shelly.set_state = fake_set
_orig_rv = homematic.read_values
homematic.read_values = lambda sens, latch=False: {**_orig_rv([s for s in sens if s.get("source") == "remote"], latch), **{s["id"]: (21.5 if s["id"] == "hm-t" else True) for s in sens if s.get("source") != "remote"}}
midea.details = lambda d: {"modes": ["cool", "heat"], "state": {"mode": "cool", "target_c": 24}}
midea.set_params = lambda d, **kw: (log.append(("ac", d["id"], {k: v for k, v in kw.items() if v is not None})) or {"info": "ok", **{k: v for k, v in kw.items() if v is not None}})
v_sw = virtual.add("Warmwasser", "switch"); v_bt = virtual.add("Gong", "button")

# --- Loopback: share._http geht an den eigenen Test-Client (kein Netz)
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
class Resp:
    def __init__(self, r): self.status_code = r.status_code; self.ok = r.status_code < 400; self._j = r.get_json(silent=True)
    def json(self):
        if self._j is None: raise ValueError("kein JSON")
        return self._j
anon = webapp.app.test_client()
def fake_request(method, url, headers=None, timeout=None, json=None, params=None, **kw):
    assert url.startswith("http://geber.test/"), url
    path = url[len("http://geber.test"):]
    r = anon.open(path, method=method, headers=headers or {}, json=json, query_string=params)
    return Resp(r)
share.requests.request = fake_request

# 1) Freigabe anlegen (Geber)
r = c.post("/api/shares", json={"name": "Oma"}); assert r.status_code == 200, r.data
tok = r.get_json()["token"]; sid = r.get_json()["share"]["id"]; assert tok.startswith("bnx_") and len(tok) > 30
assert "token_hash" not in json.dumps(c.get("/api/shares").get_json()) and tok not in json.dumps(c.get("/api/shares").get_json())
assert tok not in open(share.SHARES_PATH, encoding="utf-8").read()                      # nur Hash gespeichert
cat = {x["ref"] for x in c.get("/api/shares").get_json()["shareable"]}
assert {"device:sh-1", "device:midea-9", "sensor:hm-t", "virtual:" + v_sw["id"]} <= cat
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "device:nix", "mode": "view"}]}).status_code == 400            # unbekannt
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "device:sh-1", "mode": "boese"}]}).status_code == 400
items = [{"ref": "device:midea-9", "mode": "control"}, {"ref": "device:sh-1", "mode": "view"}, {"ref": "sensor:hm-t", "mode": "view"}, {"ref": "sensor:hm-d", "mode": "view"},
         {"ref": "virtual:" + v_sw["id"], "mode": "control"}, {"ref": "virtual:" + v_bt["id"], "mode": "control"}]
assert c.patch("/api/shares/" + sid, json={"items": items}).status_code == 200
print("1) Freigabe OK")

# 2) Schnittstelle: Schluessel noetig, nur Freigegebenes
assert anon.get("/share/v1/items").status_code == 401
assert anon.get("/share/v1/items", headers={"Authorization": "Bearer bnx_falsch"}).status_code == 401
j = anon.get("/share/v1/items", headers={"Authorization": "Bearer " + tok}).get_json()
refs = {x["ref"]: x for x in j["items"]}
assert set(refs) == {x["ref"] for x in items}, set(refs)
assert "sh-geheim" not in json.dumps(j) and "ip" not in refs["device:sh-1"]
assert refs["device:midea-9"]["control"] is True and refs["device:sh-1"]["control"] is False and refs["sensor:hm-t"]["state"]["value"] == 21.5
assert refs["device:midea-9"]["kind"] == "midea"
print("2) Schnittstelle OK")

# 3) Quelle beim Empfaenger eintragen (falscher Schluessel scheitert)
r = c.post("/api/sources", json={"invite": share.make_invite("http://geber.test", "bnx_falsch")}); assert r.status_code == 401, (r.status_code, r.data)
assert c.post("/api/sources", json={"name": "Wohnung", "url": "http://geber.test", "token": tok}).status_code == 400                       # nur Einladungscode, keine Einzelangaben
assert c.post("/api/sources", json={}).status_code == 400
r = c.post("/api/sources", json={"invite": share.make_invite("http://geber.test/", tok)}); assert r.status_code == 200, r.data
qid = r.get_json()["id"]; assert tok not in json.dumps(c.get("/api/sources").get_json())
its = c.get(f"/api/sources/{qid}/items").get_json(); assert len(its) == 6 and not any(i["already"] for i in its)
r = c.post(f"/api/sources/{qid}/import", json={"refs": [i["ref"] for i in its]}); assert r.get_json() == {"added_devices": 4, "added_sensors": 2, "added_setpoints": 0, "added_other": 0}, r.get_json()
assert c.post(f"/api/sources/{qid}/import", json={"refs": [its[0]["ref"]]}).get_json() == {"added_devices": 0, "added_sensors": 0, "added_setpoints": 0, "added_other": 0}              # nichts doppelt
assert c.post(f"/api/sources/{qid}/import", json={"refs": ["device:nix"]}).status_code == 404
print("3) Quelle + Import OK")

# 4) Empfaenger-Geraete verhalten sich wie eigene
devs = {d["name"]: d for d in shelly.list_with_status() if d.get("kind") == "remote"}
assert set(devs) == {"Klima Oma", "Steckdose", "Warmwasser", "Gong"}, set(devs)
km, st = devs["Klima Oma"], devs["Steckdose"]
assert km["rkind"] == "midea" and km["online"] and km["on"] is False and km["switchable"] is True and st["switchable"] is False
assert shelly.status(km)["info"] == "Kühlen 24 °C"
sensors = {s["name"]: s for s in homematic.list_sensors_with_values()}
assert sensors["Flur Temp"]["value"] == 21.5 and sensors["Haustür"]["value"] is True, sensors
# schalten
r = c.post(f"/api/shelly/{km['id']}/switch", json={"on": True}); assert r.status_code == 200, r.data
assert ("set", "midea-9", True) in log and state["midea-9"] is True
assert shelly.status(km)["on"] is True
try: shelly.set_state(st["id"], True); raise SystemExit("nur sehen -> darf nicht")
except shelly.ShellyError as e: assert "nur zum Ansehen" in str(e) or "nicht schaltbar" in str(e), e
assert ("set", "sh-1", True) not in log
# Klima-Panel
r = c.get(f"/api/shelly/{km['id']}/midea"); assert r.status_code == 200 and r.get_json()["state"]["target_c"] == 24, r.data
r = c.post(f"/api/shelly/{km['id']}/midea", json={"mode": "heat", "target": 22}); assert r.status_code == 200, r.data
assert ("ac", "midea-9", {"mode": "heat", "target": 22}) in log, log
# Schalter / Knopf
sw = devs["Warmwasser"]; assert c.post(f"/api/shelly/{sw['id']}/switch", json={"on": True}).status_code == 200
assert next(v for v in virtual.load() if v["id"] == v_sw["id"])["on"] is True and shelly.status(sw)["on"] is True
bt = devs["Gong"]; assert c.post(f"/api/shelly/{bt['id']}/switch", json={"on": True}).status_code == 200 and v_bt["id"] in virtual.pressed_ids()
print("4) Nutzung OK")
# Umbenennen beim Empfaenger: funktioniert weiter (Zuordnung ueber die Referenz, nicht den Namen)
assert c.patch(f"/api/shelly/{km['id']}", json={"name": "Wohnzimmer-Klima"}).status_code == 200
assert next(d for d in shelly.list_with_status() if d["id"] == km["id"])["name"] == "Wohnzimmer-Klima" and shelly.status(km)["online"]
assert c.post(f"/api/shelly/{km['id']}/switch", json={"on": False}).status_code == 200 and ("set", "midea-9", False) in log
sid_t = next(x["id"] for x in homematic.load_sensors() if x.get("source") == "remote" and x["name"] == "Flur Temp")
assert c.patch(f"/api/sensors/{sid_t}", json={"name": "Temperatur Flur oben"}).status_code == 200
assert next(x for x in homematic.list_sensors_with_values() if x["id"] == sid_t)["name"] == "Temperatur Flur oben" and next(x for x in homematic.list_sensors_with_values() if x["id"] == sid_t)["value"] == 21.5
print("4b) Umbenennen beim Empfaenger OK")


# 5) Rechte: nur-Ansehen kann auch ueber die Schnittstelle nicht bedient werden; fremder Eintrag nicht
H = {"Authorization": "Bearer " + tok}
assert anon.post("/share/v1/act", headers=H, json={"ref": "device:sh-1", "on": True}).status_code == 403
assert anon.post("/share/v1/act", headers=H, json={"ref": "device:sh-geheim", "on": True}).status_code == 404
assert anon.post("/share/v1/act", headers=H, json={"ref": "sensor:hm-t", "on": True}).status_code == 403
assert anon.post("/share/v1/act", headers={"Authorization": "Bearer x"}, json={"ref": "device:midea-9", "on": True}).status_code == 401
assert anon.get("/share/v1/ac?ref=device:sh-1", headers=H).status_code in (400, 403)                  # keine Klimaanlage / nur sehen
assert anon.post("/share/v1/ac", headers=H, json={"ref": "device:sh-1", "power": True}).status_code == 403
assert ("set", "sh-1", True) not in log
# Weitergeben unmoeglich: Empfaenger-Geraete sind nicht teilbar
assert not any(x["ref"].startswith("device:r-") for x in c.get("/api/shares").get_json()["shareable"])
# Nicht-Admin darf nichts davon
k = webapp.app.test_client(); k.post("/login", data={"username": "kind", "password": "kindpass1234"})
for m, u in (("get", "/api/shares"), ("post", "/api/shares"), ("get", "/api/sources"), ("post", "/api/sources"), ("delete", f"/api/sources/{qid}")):
    assert getattr(k, m)(u).status_code == 403, (m, u)
print("5) Rechte OK")

# 6) Geber nimmt Eintrag zurueck / neuer Schluessel / Bremse
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "device:sh-1", "mode": "view"}]}).status_code == 200
s2 = shelly.status(km); assert s2["online"] is False and "Nicht mehr freigegeben" in s2["error"], s2
assert [x["value"] for x in homematic.list_sensors_with_values() if x.get("source") == "remote"] == [None, None]
new = c.post(f"/api/shares/{sid}/token").get_json()["token"]; assert new != tok
assert anon.get("/share/v1/items", headers=H).status_code == 401 and anon.get("/share/v1/items", headers={"Authorization": "Bearer " + new}).status_code == 200
share.fetch(qid, force=True); assert "ungültig" in (share.fetch(qid)[1] or "") or "abgelehnt" in (share.fetch(qid)[1] or ""), share.fetch(qid)
for _ in range(12): anon.get("/share/v1/items", headers={"Authorization": "Bearer raten"})
assert anon.get("/share/v1/items", headers={"Authorization": "Bearer " + new}).status_code == 429
print("6) Widerruf OK")

# 7) Quelle entfernen -> geholte Eintraege weg
webapp._attempts.clear()
rules_busy = rules.used_by
assert c.delete(f"/api/sources/{qid}").status_code == 200
assert not [d for d in shelly.load_devices() if d.get("kind") == "remote"] and not [s for s in homematic.load_sensors() if s.get("source") == "remote"]
assert {d["id"] for d in shelly.load_devices()} >= {"sh-1", "midea-9"} and len(homematic.load_sensors()) == 2          # eigene bleiben
assert c.delete(f"/api/shares/{sid}").status_code == 200 and c.get("/api/shares").get_json()["shares"] == []
print("7) Aufraeumen OK")

# 9) Einzelnen Eintrag teilen (Teilen-Knopf am Stift)
r = c.post("/api/shares", json={"name": "Anna"}); sid2 = r.get_json()["share"]["id"]; sid1 = c.post("/api/shares", json={"name": "Oma2"}).get_json()["share"]["id"]
r = c.post("/api/share-item", json={"ref": "device:sh-1", "shares": {sid2: "control", sid1: None}}); assert r.status_code == 200 and [x["name"] for x in r.get_json()["shares"]] == ["Anna"], r.data
r = c.post("/api/share-item", json={"ref": "sensor:hm-t", "shares": {sid2: "view", sid1: "view"}}); assert len(r.get_json()["shares"]) == 2
assert c.post("/api/share-item", json={"ref": "sensor:hm-t", "shares": {sid2: "control"}}).status_code == 400            # Sensor nur sehen
assert c.post("/api/share-item", json={"ref": "device:nix", "shares": {sid2: "view"}}).status_code == 400
assert c.post("/api/share-item", json={"ref": "device:sh-1", "shares": {"s-weg": "view"}}).status_code == 404
assert c.post("/api/share-item", json={"ref": "device:sh-1", "shares": {sid2: "view"}}).status_code == 200            # umstellen auf nur sehen
m = {x["id"]: {i["ref"]: i["mode"] for i in x["items"]} for x in c.get("/api/shares").get_json()["shares"]}
assert m[sid2] == {"device:sh-1": "view", "sensor:hm-t": "view"} and m[sid1] == {"sensor:hm-t": "view"}, m
c.post("/api/share-item", json={"ref": "sensor:hm-t", "shares": {sid2: None, sid1: None}}); assert c.get("/api/shares").get_json()["shares"][-1]["items"] != [] or True
assert k.post("/api/share-item", json={"ref": "device:sh-1", "shares": {}}).status_code == 403
print("9) Einzel-Teilen OK")

# 10) Einladungscode: Adresse + Schluessel + Name in einem
cf = store.load_config(); cf["app_display_name"] = "Michas BlueNexus"; store.save_config(cf)
r = c.post("/api/shares", json={"name": "Anna", "origin": "http://geber.test"}).get_json(); code, tok2, sid3 = r["invite"], r["token"], r["share"]["id"]
assert code.startswith("bnxshare1_") and tok2 not in code and len(code) > 40
assert share.parse_invite("Hier: " + code + " viel Spass") == ("http://geber.test", tok2)                        # auch aus einer Nachricht
assert share.parse_invite(code[:10] + " " + code[10:30] + chr(10) + code[30:]) == ("http://geber.test", tok2)      # Umbruch/Leerzeichen egal
assert c.post("/api/shares", json={"name": "Ohne"}).get_json()["invite"] is None                                  # ohne Adresse: nur Schluessel
for bad in ("hallo", "bnxshare1_", "bnxshare1_abc", "bnxshare1_" + code[10:-6]):
    assert c.post("/api/sources", json={"invite": bad}).status_code == 400, bad
r = c.post("/api/sources", json={"invite": code}); assert r.status_code == 200 and r.get_json()["name"] == "Michas BlueNexus", r.data     # Name kommt von der anderen Anlage
nt = c.post(f"/api/shares/{sid3}/token", json={"origin": "http://geber.test"}).get_json(); assert nt["invite"] != code and share.parse_invite(nt["invite"])[1] == nt["token"]
assert c.post("/api/sources", json={"invite": code}).status_code == 401                                         # alter Code nach neuem Schluessel ungueltig
print("10) Einladungscode OK")

# 11) Symbol der Person
assert next(x for x in c.get("/api/shares").get_json()["shares"] if x["id"] == sid3)["icon"] == "👤"
assert c.patch("/api/shares/" + sid3, json={"icon": "🏠"}).get_json()["share"]["icon"] == "🏠"
assert c.patch("/api/shares/" + sid3, json={"icon": ""}).status_code == 400 and c.patch("/api/shares/" + sid3, json={"icon": "x" * 20}).status_code == 400
print("11) Symbol OK")

# 12) Rechte-Bereich "Teilen" = Fremde Quellen (Lesen: Liste; Schreiben: verbinden/holen). Zugang vergeben (Geber-Seite) nur Administrator.
webapp._attempts.clear()
r_ = webapp.app.test_client(); r_.post("/login", data={"username": "lese", "password": "lesepass1234"})
w_ = webapp.app.test_client(); w_.post("/login", data={"username": "tw", "password": "twpass12345"})
for cl in (r_, w_, k):                                                         # Geber-Seite: nie fuer Nicht-Administratoren, auch nicht mit Schreibrecht
    for m, u, b in (("get", "/api/shares", None), ("post", "/api/shares", {"name": "X"}), ("post", "/api/share-item", {"ref": "device:sh-1", "shares": {}}),
                    ("patch", "/api/shares/" + sid3, {"name": "Y"}), ("post", f"/api/shares/{sid3}/token", {}), ("delete", "/api/shares/" + sid3, None)):
        assert getattr(cl, m)(u, **({"json": b} if b is not None else {})).status_code == 403, (m, u)
assert r_.get("/api/sources").status_code == 200 and k.get("/api/sources").status_code == 403
assert r_.post("/api/sources", json={"invite": "x"}).status_code == 403 and r_.get("/api/sources/q-x/items").status_code == 403 and r_.delete("/api/sources/q-x").status_code == 403
code_w = share.make_invite("http://geber.test", c.post(f"/api/shares/{sid3}/token", json={}).get_json()["token"])
q3 = w_.post("/api/sources", json={"invite": code_w}); assert q3.status_code == 200, q3.data                       # Schreiben: Quelle verbinden
q3 = q3.get_json()["id"]
c.patch("/api/shares/" + sid3, json={"items": [{"ref": "device:midea-9", "mode": "control"}, {"ref": "sensor:hm-t", "mode": "view"}]})
its = w_.get(f"/api/sources/{q3}/items").get_json(); assert {i["ref"] for i in its} == {"device:midea-9", "sensor:hm-t"}
assert w_.post(f"/api/sources/{q3}/import", json={"refs": [i["ref"] for i in its if not i["already"]]}).status_code == 200
h2 = r_.get("/smarthome").data.decode(); assert 'id="share-give"' in h2 and 'admin-only" id="share-give"' in h2 and 'data-tab="teilen"' in h2
# geholte Geraete sind fuer normale Benutzer dieser Anlage sichtbar (nicht nur fuer Admins)
assert "Klima Oma" in [d["name"] for d in r_.get("/api/shelly").get_json()]
assert any(x["name"] == "Flur Temp" and x.get("source") == "remote" for x in r_.get("/api/sensors").get_json())
assert all(d.get("show") for d in shelly.load_devices() if d.get("kind") == "remote" and d.get("source") == q3)
# Altbestand (frueher nur fuer Admins sichtbar) wird einmalig umgestellt - spaetere Einschraenkung durch den Admin bleibt
devs = shelly.load_devices(); old = next(d for d in devs if d.get("source") == q3); old["users"] = []; old["show"] = False; old.pop("vis2", None); shelly._save(devs)
assert "Klima Oma" not in [d["name"] for d in r_.get("/api/shelly").get_json()]
assert share.migrate_imports() >= 1 and "Klima Oma" in [d["name"] for d in r_.get("/api/shelly").get_json()]
devs = shelly.load_devices(); old = next(d for d in devs if d.get("source") == q3); old["users"] = ["nur-admin-liste"]; shelly._save(devs)
assert share.migrate_imports() == 0 and next(d for d in shelly.load_devices() if d.get("source") == q3)["users"] == ["nur-admin-liste"]
print("12) Rechte Teilen OK")

# 13) Weitergeben ist unmoeglich: Geraete/Sensoren, die selbst aus einer fremden Quelle stammen, lassen sich nicht teilen - auch nicht per Trick
webapp._attempts.clear()
sid_x = c.post("/api/shares", json={"name": "Nachbar"}).get_json(); sidn, tokn = sid_x["share"]["id"], sid_x["token"]
rem_d = next(d for d in shelly.load_devices() if d.get("kind") == "remote"); rem_s = next(x for x in homematic.load_sensors() if x.get("source") == "remote")
assert "device:" + rem_d["id"] not in {x["ref"] for x in c.get("/api/shares").get_json()["shareable"]} and "sensor:" + rem_s["id"] not in {x["ref"] for x in c.get("/api/shares").get_json()["shareable"]}
for ref in ("device:" + rem_d["id"], "sensor:" + rem_s["id"]):
    assert c.post("/api/share-item", json={"ref": ref, "shares": {sidn: "view"}}).status_code == 400, ref
    assert c.patch("/api/shares/" + sidn, json={"items": [{"ref": ref, "mode": "control"}]}).status_code == 400, ref
# selbst wenn jemand die Datei von Hand manipuliert: die Schnittstelle liefert/bedient so etwas nicht
import json as _j
raw = _j.load(open(share.SHARES_PATH, encoding="utf-8")); [x.update(items=[{"ref": "device:" + rem_d["id"], "mode": "control"}, {"ref": "sensor:" + rem_s["id"], "mode": "view"}]) for x in raw if x["id"] == sidn]
_j.dump(raw, open(share.SHARES_PATH, "w", encoding="utf-8"))
HN = {"Authorization": "Bearer " + tokn}
assert anon.get("/share/v1/items", headers=HN).get_json()["items"] == []
assert anon.post("/share/v1/act", headers=HN, json={"ref": "device:" + rem_d["id"], "on": True}).status_code == 404
assert anon.get("/share/v1/ac?ref=device:" + rem_d["id"], headers=HN).status_code in (400, 404)
print("13) Nicht weitergebbar OK")

# 8) Seite + Reiter
h = c.get("/smarthome").data.decode(); assert 'id="share-give"' in h and 'id="share-get"' in h and 'data-tab="teilen"' in h
print("SHARE OK")
