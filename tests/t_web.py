import os, re, sys, tempfile, subprocess, json
sys.path.insert(0, sys.argv[1] + "/app")
os.chdir(sys.argv[1] + "/app")
import vrm
tmp = tempfile.mkdtemp()
vrm.CREDENTIALS_PATH = os.path.join(tmp, "vrm.json")
import webapp
c = webapp.app.test_client()
class U:
    def get(self, n): return {'username': 'test'}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U()
user = 'test'
with c.session_transaction() as s:
    s["user"] = user
print(c.get("/api/vrm/forecast").get_json())
r = c.post("/api/vrm/credentials", json={"installation_id": "x", "token": "t"}); print(r.status_code, r.get_json())
r = c.post("/api/vrm/credentials", json={"installation_id": "844297", "token": "SECRET"}); print(r.status_code)
print(c.get("/api/vrm").get_json())
assert "SECRET" not in c.get("/api/vrm").get_data(as_text=True)
vrm._request = lambda cr, p: {"records": {"solar_yield_forecast": [[1790305987000, 0], [1790309587000, 412.3]]}}
print(c.get("/api/vrm/forecast?refresh=1").get_json()["configured"])
print(c.get("/api/status").get_json()["ui"]["show_shelly_card"])
for path in ("/", "/admin", "/setup", "/solar-log"):
    html = c.get(path).get_data(as_text=True)
    scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
    for i, sc in enumerate(scripts):
        p = os.path.join(tmp, f"s{i}.js"); open(p, "w", encoding="utf-8").write(sc)
        out = subprocess.run(["node", "--check", p], capture_output=True, text=True)
        print(path, i, "node ok" if out.returncode == 0 else out.stderr[:400])
    print(path, "forecast-card" in html, "vrm-admin" in html)
vrm._request = lambda cr, p: (_ for _ in ()).throw(vrm.VrmError("VRM nicht erreichbar: test"))
r = c.post("/api/vrm/restore", json={}); print("restore", r.status_code, r.get_json())
