"""Alles teilen: Tuerschloesser, Rollladen, Soundmodule, Wake-on-LAN (Geber + Empfaenger), mit Rechten, Zustand, Bedienen, Entfernen."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import share, shelly, homematic, wol
from auth import UserStore
share.SHARES_PATH = os.path.join(tmp, "shares.json"); share.SOURCES_PATH = os.path.join(tmp, "sources.json")
wol.WOL_PATH = os.path.join(tmp, "wol.json")
homematic.BLINDS_PATH = os.path.join(tmp, "hm_blinds.json"); homematic.SOUNDS_PATH = os.path.join(tmp, "hm_sounds.json")
webapp.users = UserStore(os.path.join(tmp, "u_shall.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("kind", "kindpass1234", {"dashboard": "write"})
webapp.opslog.log = lambda *a, **k: None
share.CACHE_TTL_S = 0
shelly._save([]); homematic._save_sensors([]); homematic._save_setpoints([])

homematic._save_locks([{"id": "hmK-1", "address": "L:1", "interface": "HmIP-RF", "model": "DLD", "room": "Flur", "name": "Haustür", "allow_open": False},
                       {"id": "hmK-2", "address": "L:2", "interface": "HmIP-RF", "model": "DLD", "room": "", "name": "Garage", "allow_open": True},
                       {"id": "hmK-geheim", "address": "L:9", "interface": "HmIP-RF", "model": "DLD", "room": "", "name": "Nicht geteilt", "allow_open": True}])
homematic._save_blinds([{"id": "hmR-1", "address": "R:1", "interface": "HmIP-RF", "model": "BROLL", "room": "Wohnen", "name": "Rollladen Terrasse", "icon": "🪟"},
                        {"id": "hmR-2", "address": "R:2", "interface": "HmIP-RF", "model": "BROLL", "room": "Bad", "name": "Rollladen Bad", "icon": "🪟"}])
homematic._save_sounds([{"id": "hmA-1", "address": "S:1", "interface": "HmIP-RF", "model": "OU", "room": "", "name": "Gong", "icon": "🔔"}])
wol.WOL_PATH = os.path.join(tmp, "wol.json")
wol._save([{"id": "w-1", "name": "Oma-PC", "icon": "💻", "mac": "AA:BB:CC:DD:EE:FF", "ip": "192.168.50.50", "show": True},
           {"id": "w-geheim", "name": "Server", "icon": "🖥", "mac": "11:22:33:44:55:66", "ip": "", "show": True}])

hm = {"L:1": 1, "L:2": 2, "L:9": 1, "R:1": 0.4, "R:2": 1.0}      # LOCK_STATE: 1 verriegelt, 2 entriegelt; Rollladen LEVEL 0..1
sent = []
def fake_call(method, params=None):
    if method == "Interface.setValue":
        sent.append((params["address"], params["valueKey"], params["value"]))
        if params["valueKey"] == "LEVEL": hm[params["address"]] = params["value"]
        if params["valueKey"] == "LOCK_TARGET_LEVEL": hm[params["address"]] = {0: 1, 1: 2, 2: 2}[params["value"]]
    return {}
homematic._call = fake_call
homematic._get_value = lambda itf, addr, key: str(hm[addr]) if key == "LOCK_STATE" else hm[addr]
homematic._unreach = lambda x: False
wol.is_up = lambda ip: True if ip == "192.168.50.50" else None
woken = []
wol.wake_real = None
_orig_wake = wol.wake
def fake_wake_local(wid):
    it = next(x for x in wol.load() if x["id"] == wid)
    if it.get("source") == "remote": return _orig_wake(wid)
    woken.append(wid); return ["x"]
wol.wake = fake_wake_local

c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
class Resp:
    def __init__(self, r): self.status_code = r.status_code; self.ok = r.status_code < 400; self._j = r.get_json(silent=True)
    def json(self):
        if self._j is None: raise ValueError("kein JSON")
        return self._j
anon = webapp.app.test_client()
def fake_request(method, url, headers=None, timeout=None, json=None, params=None, **kw):
    return Resp(anon.open(url[len("http://geber.test"):], method=method, headers=headers or {}, json=json, query_string=params))
share.requests.request = fake_request

# ---- Geber
r = c.post("/api/shares", json={"name": "Oma"}); tok = r.get_json()["token"]; sid = r.get_json()["share"]["id"]
cat = {x["ref"]: x for x in c.get("/api/shares").get_json()["shareable"]}
for ref, label in (("lock:hmK-1", "Türschloss"), ("blind:hmR-1", "Rollladen"), ("sound:hmA-1", "Soundmodul"), ("wol:w-1", "Wake-on-LAN")):
    assert cat[ref]["detail"] == label, (ref, cat.get(ref))
items = [{"ref": "lock:hmK-1", "mode": "control"}, {"ref": "lock:hmK-2", "mode": "view"}, {"ref": "blind:hmR-1", "mode": "control"}, {"ref": "blind:hmR-2", "mode": "view"},
         {"ref": "sound:hmA-1", "mode": "control"}, {"ref": "wol:w-1", "mode": "control"}]
assert c.patch("/api/shares/" + sid, json={"items": items}).status_code == 200
H = {"Authorization": "Bearer " + tok}
j = anon.get("/share/v1/items", headers=H).get_json(); refs = {x["ref"]: x for x in j["items"]}
assert set(refs) == {i["ref"] for i in items} and "Nicht geteilt" not in json.dumps(j) and "Server" not in json.dumps(j) and "AA:BB" not in json.dumps(j) and "192.168" not in json.dumps(j)
assert refs["lock:hmK-1"]["state"]["locked"] is True and refs["lock:hmK-2"]["state"]["locked"] is False
assert refs["blind:hmR-1"]["state"]["level"] == 40 and refs["blind:hmR-2"]["state"]["level"] == 100
assert refs["wol:w-1"]["state"]["up"] is True and refs["lock:hmK-2"]["control"] is False and refs["wol:w-1"]["control"] is True
# Rechte an der Schnittstelle: nur sehen = 403; Fremdes = 404; ohne Schluessel 401
assert anon.post("/share/v1/act", headers=H, json={"ref": "lock:hmK-2", "action": "unlock"}).status_code == 403
assert anon.post("/share/v1/act", headers=H, json={"ref": "blind:hmR-2", "level": 0}).status_code == 403
assert anon.post("/share/v1/act", headers=H, json={"ref": "lock:hmK-geheim", "action": "lock"}).status_code == 404
assert anon.post("/share/v1/act", headers=H, json={"ref": "wol:w-geheim"}).status_code == 404
assert anon.post("/share/v1/act", headers={"Authorization": "Bearer x"}, json={"ref": "wol:w-1"}).status_code == 401
# Schloss: Verriegeln geht, Entriegeln nur mit allow_open des Gebers (hier hmK-1: aus)
r = anon.post("/share/v1/act", headers=H, json={"ref": "lock:hmK-1", "action": "unlock"}); assert r.status_code == 400 and "nicht freigegeben" in r.get_json()["error"], r.get_data(as_text=True)
assert hm["L:1"] == 1 and not sent
assert anon.post("/share/v1/act", headers=H, json={"ref": "lock:hmK-1", "action": "bogus"}).status_code == 400
assert anon.post("/share/v1/act", headers=H, json={"ref": "lock:hmK-1", "action": "lock"}).status_code == 200
print("Geber OK")

# ---- Empfaenger
qid = c.post("/api/sources", json={"invite": share.make_invite("http://geber.test", tok)}).get_json()["id"]
its = c.get(f"/api/sources/{qid}/items").get_json(); assert len(its) == 6 and {i["type"] for i in its} == {"lock", "blind", "sound", "wol"}
r = c.post(f"/api/sources/{qid}/import", json={"refs": [i["ref"] for i in its]}); assert r.get_json() == {"added_devices": 0, "added_sensors": 0, "added_setpoints": 0, "added_other": 6}, r.get_json()
assert c.post(f"/api/sources/{qid}/import", json={"refs": ["lock:hmK-1"]}).get_json()["added_other"] == 0
assert all(i["already"] for i in c.get(f"/api/sources/{qid}/items").get_json())
loc = lambda lst, n: next(x for x in lst if x["name"] == n and x.get("source") == "remote")
locks, blinds, sounds, wols = homematic.load_locks(), homematic.load_blinds(), homematic.load_sounds(), wol.load()
k1, k2, b1, b2, s1, w1 = loc(locks, "Haustür"), loc(locks, "Garage"), loc(blinds, "Rollladen Terrasse"), loc(blinds, "Rollladen Bad"), loc(sounds, "Gong"), loc(wols, "Oma-PC")
assert k1["switchable"] is True and k2["switchable"] is False and k1["allow_open"] is False and w1["mac"] == "00:00:00:00:00:00" and "192.168" not in json.dumps(w1)
# Zustand
ls = {x["name"]: x for x in c.get("/api/homematic/locks").get_json()}
assert ls["Haustür"]["locked"] is True and ls["Garage"]["locked"] is False and ls["Haustür"]["source"] == "remote"
bl = {x["name"]: x for x in c.get("/api/homematic/blinds").get_json()}
assert bl["Rollladen Terrasse"]["level"] == 40 and bl["Rollladen Bad"]["level"] == 100
ws = {x["name"]: x for x in c.get("/api/wol").get_json()}; assert ws["Oma-PC"]["up"] is True
# Rollladen bedienen: geht zum Geber
r = c.post(f"/api/homematic/blinds/{b1['id']}/level", json={"level": 75}); assert r.status_code == 200, r.get_data(as_text=True)
assert ("R:1", "LEVEL", 0.75) in sent and {x["name"]: x for x in c.get("/api/homematic/blinds").get_json()}["Rollladen Terrasse"]["level"] == 75
r = c.post(f"/api/homematic/blinds/{b1['id']}/stop"); assert r.status_code == 200 and ("R:1", "STOP", True) in sent
# nur sehen: Fehlermeldung, nichts passiert
n = len(sent)
r = c.post(f"/api/homematic/blinds/{b2['id']}/level", json={"level": 0}); assert r.status_code == 400 and "nur zum Ansehen" in r.get_json()["error"], r.get_data(as_text=True)
assert len(sent) == n
# Soundmodul spielt beim Geber
r = c.post(f"/api/homematic/sounds/{s1['id']}/play", json={"track": 3, "volume": 50}); assert r.status_code == 200, r.get_data(as_text=True)
assert any(a == "S:1" and k == "SUBMIT" for a, k, v in sent)
# Wake-on-LAN beim Geber
r = c.post(f"/api/wol/{w1['id']}/wake"); assert r.status_code == 200, r.get_data(as_text=True)
assert woken == ["w-1"]
# Schloss ueber Regeln-Weg: Verriegeln darf immer, Entriegeln braucht beim Empfaenger allow_open UND beim Geber
assert homematic.lock_action(k1["id"], "lock") == "Haustür"
for act in ("unlock", "open"):
    try: homematic.lock_action(k1["id"], act); raise SystemExit("haette scheitern muessen")
    except homematic.HomematicError as e: assert "nicht freigegeben" in str(e)
assert c.patch(f"/api/homematic/locks/{k1['id']}", json={"allow_open": True}).status_code == 200
try: homematic.lock_action(k1["id"], "unlock"); raise SystemExit("Geber hat es nicht freigegeben")
except homematic.HomematicError as e: assert "nicht freigegeben" in str(e), e
assert hm["L:1"] == 1                                                                     # blieb verriegelt
# Von Hand bedienen (Knoepfe in der Liste): braucht keine Regel-Freigabe; bei Geteiltem erlaubt "sehen & bedienen" es
kl = webapp.app.test_client(); kl.post("/login", data={"username": "kind", "password": "kindpass1234"})
assert kl.post(f"/api/homematic/locks/{k1['id']}/action", json={"action": "unlock"}).status_code == 403              # nur Dashboard-Recht reicht nicht
r = c.post(f"/api/homematic/locks/{k1['id']}/action", json={"action": "unlock"}); assert r.status_code == 200, r.get_data(as_text=True)
assert hm["L:1"] == 2 and ("L:1", "LOCK_TARGET_LEVEL", 1) in sent                                                   # beim GEBER entriegelt, obwohl seine Regel-Freigabe aus ist
assert {x["name"]: x for x in c.get("/api/homematic/locks").get_json()}["Haustür"]["locked"] is False
assert c.post(f"/api/homematic/locks/{k1['id']}/action", json={"action": "lock"}).status_code == 200 and hm["L:1"] == 1
assert c.post(f"/api/homematic/locks/{k1['id']}/action", json={"action": "open"}).status_code == 200 and ("L:1", "LOCK_TARGET_LEVEL", 2) in sent
r = c.post(f"/api/homematic/locks/{k2['id']}/action", json={"action": "unlock"}); assert r.status_code == 400 and "nur zum Ansehen" in r.get_json()["error"], r.get_data(as_text=True)
assert c.post(f"/api/homematic/locks/{k1['id']}/action", json={"action": "bogus"}).status_code == 400
assert c.post("/api/homematic/locks/gibtsnicht/action", json={"action": "lock"}).status_code == 400
# eigenes (lokales) Schloss von Hand, auch ohne allow_open
loc_k = homematic.load_locks()[0]; assert loc_k.get("source") != "remote" and loc_k["id"] == "hmK-1" and not loc_k["allow_open"]
assert c.post("/api/homematic/locks/hmK-1/action", json={"action": "unlock"}).status_code == 200 and hm["L:1"] == 2
hm["L:1"] = 1
# Weitergeben unmoeglich
cat2 = {x["ref"] for x in c.get("/api/shares").get_json()["shareable"]}
assert not any(r.split(":", 1)[1].startswith("r-") for r in cat2 if r.split(":", 1)[0] in ("lock", "blind", "sound", "wol", "setpoint"))
# Geber nimmt zurueck
assert c.patch("/api/shares/" + sid, json={"items": [{"ref": "lock:hmK-1", "mode": "view"}]}).status_code == 200
assert {x["name"]: x for x in c.get("/api/homematic/blinds").get_json()}["Rollladen Terrasse"]["level"] is None
r = c.post(f"/api/homematic/blinds/{b1['id']}/level", json={"level": 10}); assert r.status_code == 400 and "freigegeben" in r.get_json()["error"], r.get_data(as_text=True)
# Quelle entfernen nimmt alles mit
r = c.delete(f"/api/sources/{qid}"); assert r.status_code == 200 and r.get_json()["removed"] == 6, r.get_data(as_text=True)
assert not [x for lst in (homematic.load_locks(), homematic.load_blinds(), homematic.load_sounds(), wol.load()) for x in lst if x.get("source") == "remote"]
assert len(homematic.load_locks()) == 3 and len(homematic.load_blinds()) == 2 and len(wol.load()) == 2
print("Empfaenger OK")
print("ALLES TEILEN OK")
