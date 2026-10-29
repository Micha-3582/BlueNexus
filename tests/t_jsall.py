import sys, os, re, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_js.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
bad = 0
for page in ("/", "/kameras", "/admin", "/smarthome", "/rules", "/verlauf"):
    h = c.get(page).data.decode()
    js = "\n".join(re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", h, re.S))
    f = os.path.join(tmp, "x.js"); open(f, "w", encoding="utf-8").write(js)
    r = subprocess.run(["node", "--check", f], capture_output=True, text=True)
    print(page, "OK" if r.returncode == 0 else "FEHLER " + r.stderr[:300]); bad += r.returncode != 0
print("JS ALL", "OK" if not bad else "FEHLER")
