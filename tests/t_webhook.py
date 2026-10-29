import sys, os, threading, time, json
from http.server import BaseHTTPRequestHandler, HTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import virtual, webhook
from auth import UserStore
virtual.VIRTUAL_PATH = os.path.join(tmp, "virtual_wh.json")
webapp.users = UserStore(os.path.join(tmp, "u_wh.json")); webapp.users.create("admin", "adminpass1"); webapp.opslog.log = lambda *a, **k: LOG.append(a)
webapp.users.create("demo", "demopass1234", {a: ("read" if a != "dashboard" else "write") for a in webapp.auth.AREA_IDS})
store.module_on = lambda n, cfg=None: True
LOG = []
HITS = []


class H(BaseHTTPRequestHandler):
    def _go(self):
        HITS.append((self.command, self.path))
        code = 500 if "/fail" in self.path else 200
        self.send_response(code); self.end_headers(); self.wfile.write(b"x")
    do_GET = do_POST = _go
    def log_message(self, *a): pass


srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_port}"
adm = webapp.app.test_client(); adm.post("/login", data={"username": "admin", "password": "adminpass1"})
dm = webapp.app.test_client(); dm.post("/login", data={"username": "demo", "password": "demopass1234"})

# 1) Pruefung der Adresse
for bad in ("", "ftp://x/y", "http://169.254.169.254/latest/meta-data", "http://[fe80::1]/x", "http://a b/c", "http://host:99999/x", "http://0.0.0.0/x"):
    try:
        webhook.validate(bad); raise AssertionError("haette abgelehnt werden muessen: " + bad)
    except webhook.WebhookError:
        pass
assert webhook.validate("192.168.50.50/relay") == "http://192.168.50.50/relay" and webhook.validate("https://x.example/a?b=1").startswith("https://")
print("1) Adresspruefung OK")

# 2) Anlegen: nur Admin, nur Knopf; Adresse bleibt geheim
SECRET = BASE + "/geheim/schalten?key=abc123"
r = adm.post("/api/virtual", json={"name": "Garage", "kind": "button", "url": SECRET, "method": "GET"}); assert r.status_code == 201, r.get_json()
j = r.get_json(); vid = j["id"]; assert j["has_url"] is True and "url" not in j and "abc123" not in json.dumps(j)
assert adm.post("/api/virtual", json={"name": "S", "kind": "switch", "url": SECRET}).status_code == 400, "Web-Aufruf nur bei Knopf"
assert dm.post("/api/virtual", json={"name": "X", "kind": "button", "url": SECRET}).status_code == 403, "nur Administratoren"
lst = adm.get("/api/virtual").get_data(as_text=True); assert "abc123" not in lst and "geheim" not in lst and '"has_url": true' in lst.replace('":true', '": true')
dl = dm.get("/api/virtual").get_data(as_text=True); assert "abc123" not in dl
print("2) Anlegen/Geheimhaltung OK")

# 3) Druecken: GET wird aufgerufen, Ergebnis kommt zurueck
r = adm.post(f"/api/virtual/{vid}/press"); jj = r.get_json()
assert r.status_code == 200 and jj["call"] == "ok", jj
assert HITS and HITS[-1] == ("GET", "/geheim/schalten?key=abc123"), HITS
assert not any("abc123" in str(x) for x in LOG), "Adresse darf nicht im Logbuch stehen"
assert any("Web-Aufruf" in str(x) and "ausgelöst" in str(x) for x in LOG)
print("3) Druecken -> Aufruf OK")

# 4) POST, Fehlercodes, nicht erreichbar
assert adm.patch(f"/api/virtual/{vid}", json={"method": "POST"}).status_code == 200
adm.post(f"/api/virtual/{vid}/press"); assert HITS[-1][0] == "POST"
assert adm.patch(f"/api/virtual/{vid}", json={"url": BASE + "/fail"}).status_code == 200
jj = adm.post(f"/api/virtual/{vid}/press").get_json(); assert jj["call"] == "fehler" and jj["call_text"] == "HTTP 500", jj
assert adm.patch(f"/api/virtual/{vid}", json={"url": "http://127.0.0.1:1/zu"}).status_code == 200
jj = adm.post(f"/api/virtual/{vid}/press").get_json(); assert jj["call"] == "fehler" and "127.0.0.1" not in jj["call_text"], jj
assert adm.patch(f"/api/virtual/{vid}", json={"url": "http://169.254.169.254/x"}).status_code == 400
print("4) POST/Fehler/Sperrziele OK")

# 5) Entfernen der Adresse -> normaler Knopf; Regel-Impuls funktioniert auch ohne Adresse
assert adm.patch(f"/api/virtual/{vid}", json={"clear_url": True}).status_code == 200
it = next(v for v in virtual.load() if v["id"] == vid); assert "url" not in it and "method" not in it
n = len(HITS); jj = adm.post(f"/api/virtual/{vid}/press").get_json(); assert jj == {"ok": True} and len(HITS) == n
assert adm.patch(f"/api/virtual/{vid}", json={"url": BASE + "/neu"}).status_code == 200
time.sleep(0.2); t0 = time.time(); assert virtual.press(vid) is True                  # wie aus einer Regel/NFC: Impuls + Aufruf
res = webhook.result_since(vid, t0, 3); assert res and res[0] is True and HITS[-1][1] == "/neu", (res, HITS[-3:])
print("5) Entfernen/Regel-Druck OK")

# 6) Administrator sieht/aendert die Adresse, andere nicht
assert adm.patch(f"/api/virtual/{vid}", json={"url": SECRET}).status_code == 200
j2 = adm.get(f"/api/virtual/{vid}/url").get_json(); assert j2["url"] == SECRET and j2["method"] in ("GET", "POST")
assert dm.get(f"/api/virtual/{vid}/url").status_code == 403
print("6) Adresse fuer Admin sichtbar OK")

# 7) Regel-Schritt "Adresse aufrufen"
import rules
rules.RULES_PATH = os.path.join(tmp, "rules_wh.json")
step = {"type": "http", "method": "POST", "url": BASE + "/regel?k=geheim99", "label": "Hoftor"}
body = {"rules": [{"name": "Tor", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]}, "then": [step], "else": []}], "groups": []}
r = adm.post("/api/automation", json=body); assert r.status_code == 200, r.get_json()
bad = {**body, "rules": [{**body["rules"][0], "then": [{"type": "http", "method": "GET", "url": "ftp://x"}]}]}
assert adm.post("/api/automation", json=bad).status_code == 400
bad2 = {**body, "rules": [{**body["rules"][0], "then": [{"type": "http", "method": "PUT", "url": BASE + "/x"}]}]}
assert adm.post("/api/automation", json=bad2).status_code == 400
ra = adm.get("/api/rules").get_json()["rules"][0]["then"][0]; assert ra["url"] == BASE + "/regel?k=geheim99" and ra["method"] == "POST" and ra["label"] == "Hoftor"
rd = dm.get("/api/rules").get_json()["rules"][0]["then"][0]; assert rd["url"] == "" and rd["url_hidden"] is True and "geheim99" not in json.dumps(dm.get("/api/rules").get_json())
ctrl = webapp.ctrl; n = len(HITS)
ctrl._apply_flow({"rule_id": "r1", "rule": "Tor", "branch": "then", "step": ra, "after_s": 0}, True, {}); time.sleep(0.5); assert len(HITS) == n, "Trockenlauf ruft nie auf"
ctrl._apply_flow({"rule_id": "r1", "rule": "Tor", "branch": "then", "step": ra, "after_s": 0}, False, {})
for _ in range(30):
    if len(HITS) > n: break
    time.sleep(0.1)
assert HITS[-1] == ("POST", "/regel?k=geheim99"), HITS[-2:]
assert not any("geheim99" in str(x) for x in LOG), "Adresse nicht im Logbuch"
print("7) Regel-Schritt Adresse aufrufen OK")
print("WEBHOOK OK")
