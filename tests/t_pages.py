import os, sys, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
sys.path.insert(0, sys.argv[1] + "/app")
import auth
class U:
    def get(self, n): return {"username": "t", "permissions": dict(auth.PRESETS["admin"])}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U(); cl = webapp.app.test_client()
with cl.session_transaction() as s: s["user"] = "t"
for path in ("/", "/admin", "/automation", "/rules", "/automation-log", "/rules-log", "/report", "/solar-log"):
    r = cl.get(path); assert r.status_code == 200, (path, r.status_code)
    h = r.get_data(as_text=True)
    open(os.path.join(tmp, "x.js"), "w", encoding="utf-8").write("\n".join(re.findall(r"<script>(.*?)</script>", h, re.S)))
    assert subprocess.run(["node", "--check", os.path.join(tmp, "x.js")], capture_output=True, text=True).returncode == 0, path
    assert 'href="/automation"' in h, path
print("PAGES OK", sys.argv[1].split("/")[-1])
