"""Cloudflare Tunnel: Token pruefen/speichern, cloudflared installieren (simuliert), starten/ueberwachen/neustarten, Log ohne Token, Rechte, Loeschen."""
import sys, os, time, json, base64, subprocess, platform
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import tunnel

tunnel.CFG_PATH = os.path.join(tmp, "tn_cfg.json"); tunnel.PID_PATH = os.path.join(tmp, "tn.pid")
tunnel.BIN_DIR = os.path.join(tmp, "tn_bin"); tunnel.BIN_PATH = os.path.join(tunnel.BIN_DIR, "cloudflared")
for p in (tunnel.CFG_PATH, tunnel.PID_PATH):
    if os.path.exists(p):
        os.remove(p)
tunnel.SUPERVISE_S = 0.2; tunnel.BACKOFF_S = (0.3, 0.3)

mk = lambda d: base64.b64encode(json.dumps(d).encode()).decode().rstrip("=")
TOKEN = mk({"a": "acc123", "t": "11111111-2222-3333-4444-555555555555", "s": "geheimgeheimgeheim"})

# 1) Token
for bad in ("", "abc", "eyJ" + "x" * 80, mk({"a": 1}), "kein token"):
    try:
        tunnel.save_token(bad); raise SystemExit("Token %r muss abgelehnt werden" % bad[:20])
    except tunnel.TunnelError:
        pass
assert tunnel.has_token() is False and tunnel.enabled() is False
tunnel.save_token(f"sudo cloudflared service install {TOKEN}")                 # ganzer Befehl eingefuegt
assert tunnel.has_token() and json.load(open(tunnel.CFG_PATH))["token"] == TOKEN
print("1) Token OK")

# 2) Installation (simuliert)
for machine, want in (("x86_64", "cloudflared-linux-amd64"), ("aarch64", "cloudflared-linux-arm64"), ("armv7l", "cloudflared-linux-armhf"), ("armv6l", "cloudflared-linux-arm")):
    platform.machine = lambda m=machine: m; platform.system = lambda: "Linux"
    assert tunnel.asset_name() == want, (machine, tunnel.asset_name())
platform.machine = lambda: "riscv64"; assert tunnel.asset_name() is None
platform.system = lambda: "Windows"; platform.machine = lambda: "AMD64"; assert tunnel.asset_name() is None
try:
    tunnel.install(); raise SystemExit("nicht unterstuetztes System")
except tunnel.TunnelError as e:
    assert "nur für Linux" in str(e)
platform.system = lambda: "Linux"; platform.machine = lambda: "aarch64"
URLS = []
class FakeGet:
    def __init__(self, n): self.n = n
    def raise_for_status(self): pass
    def iter_content(self, size):
        left = self.n
        while left > 0:
            yield b"\0" * min(size, left); left -= size
def fake_get(url, **kw):
    URLS.append(url); return FakeGet(FAKE_SIZE[0])
FAKE_SIZE = [2_000_000]
tunnel.requests.get = fake_get
tunnel._version_uncached = lambda b: "2025.9.0" if os.path.exists(b) else ""
tunnel._ver_cache.clear()
v = tunnel.install()
assert v == "2025.9.0" and os.path.exists(tunnel.BIN_PATH) and URLS == [tunnel.RELEASE_BASE + "cloudflared-linux-arm64"] and not os.path.exists(tunnel.BIN_PATH + ".part"), (v, URLS)
assert tunnel.find_binary() == tunnel.BIN_PATH or os.name == "nt"           # unter Windows fehlt das Ausfuehr-Recht
FAKE_SIZE[0] = 5000
try:
    tunnel.install(); raise SystemExit("zu kleiner Download muss scheitern")
except tunnel.TunnelError as e:
    assert "unvollständig" in str(e)
import requests as _rq
def boom(url, **kw): raise _rq.ConnectionError("kein Netz")
tunnel.requests.get = boom
try:
    tunnel.install(); raise SystemExit("Netzfehler")
except tunnel.TunnelError as e:
    assert "Download fehlgeschlagen" in str(e)
print("2) Installation OK")

# 3) Start / Status / Log ohne Token / Ueberwachung (cloudflared durch ein Test-Skript ersetzt)
FAKE = os.path.join(tmp, "fake_cloudflared.py")
open(FAKE, "w").write('''import os, sys, time
print("INF Starting tunnel", flush=True)
print("INF token=" + os.environ["TUNNEL_TOKEN"], flush=True)
if os.environ.get("FAKE_MODE") == "crash":
    print("ERR Unauthorized: bad token", flush=True); sys.exit(1)
print("INF Registered tunnel connection connIndex=0", flush=True)
print("INF Registered tunnel connection connIndex=1", flush=True)
time.sleep(60)
''')
RUNS = []
_real_popen = subprocess.Popen
def fake_popen(args, **kw):
    RUNS.append((args, dict(kw.get("env") or {}).get("TUNNEL_TOKEN")))
    return _real_popen([sys.executable, FAKE], **kw)
tunnel.subprocess.Popen = fake_popen
tunnel.find_binary = lambda: "fake-cloudflared"
tunnel.set_enabled(True)
for _ in range(40):
    if tunnel.status()["connections"] >= 2: break
    time.sleep(0.1)
st = tunnel.status()
assert st["running"] and st["connected"] and st["connections"] == 2 and "Verbunden" in st["text"] and st["has_token"] and st["enabled"], st
assert RUNS[0][0][1:] == ["tunnel", "--no-autoupdate", "run"] and TOKEN not in " ".join(RUNS[0][0]) and RUNS[0][1] == TOKEN, RUNS[0]      # Token nur per Umgebung
log = "\n".join(tunnel.log_lines())
assert TOKEN not in log and "token=***" in log and "Registered tunnel connection" in log, log
assert TOKEN not in json.dumps(st)
assert tunnel.enabled() and os.path.exists(tunnel.PID_PATH)
tunnel.set_enabled(False)
assert not tunnel.status()["running"] and "Aus" in tunnel.status()["text"] and not os.path.exists(tunnel.PID_PATH)
print("3) Start/Stop OK")

# 4) Absturz -> automatischer Neustart mit Wartezeit
os.environ["FAKE_MODE"] = "crash"
n0 = len(RUNS); tunnel.set_enabled(True)
for _ in range(60):
    if tunnel.status()["restarts"] >= 2: break
    time.sleep(0.1)
st = tunnel.status()
assert st["restarts"] >= 2 and len(RUNS) >= n0 + 3 and "Unauthorized" in st["last_error"], (st, len(RUNS) - n0)
tunnel.set_enabled(False); time.sleep(0.6); n1 = len(RUNS); time.sleep(0.8)
assert len(RUNS) == n1, "ausgeschaltet: kein Neustart mehr"
os.environ["FAKE_MODE"] = ""
print("4) Neustart OK")

# 5) Endpunkte + Rechte + Loeschen
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_tn.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("nur", "nurpass1234", {"dashboard": "write"}); webapp.users.create("lese", "lesepass123", {"settings_system": "read"})
cl = lambda u, p: (lambda c: (c.post("/login", data={"username": u, "password": p}, follow_redirects=True), c)[1])(webapp.app.test_client())
adm, nur, lese = cl("admin", "adminpass1"), cl("nur", "nurpass1234"), cl("lese", "lesepass123")
webapp.opslog.log = lambda *a, **k: None
for cli in (nur,):
    for m, u in (("get", "/api/tunnel"), ("get", "/api/tunnel/log")):
        assert getattr(cli, m)(u).status_code in (302, 403), u
for cli in (nur, lese):
    assert cli.post("/api/tunnel/token", json={"token": TOKEN}).status_code in (302, 403)
    assert cli.delete("/api/tunnel/token").status_code in (302, 403)
    assert cli.post("/api/tunnel/enable", json={"enabled": True}).status_code in (302, 403)
    assert cli.post("/api/tunnel/install").status_code in (302, 403)
assert tunnel.has_token(), "ohne Recht darf nichts geloescht werden"
j = adm.get("/api/tunnel").get_json(); assert j["has_token"] and TOKEN not in json.dumps(j) and TOKEN not in adm.get("/api/tunnel/log").get_data(as_text=True)
assert lese.get("/api/tunnel").status_code == 200 and TOKEN not in lese.get("/api/tunnel").get_data(as_text=True)
assert adm.post("/api/tunnel/token", json={"token": "murks"}).status_code == 400
tunnel.find_binary = lambda: None
r = adm.post("/api/tunnel/enable", json={"enabled": True}); assert r.status_code == 400 and "installiert" in r.get_json()["error"], r.get_json()
tunnel.find_binary = lambda: "fake-cloudflared"
r = adm.post("/api/tunnel/enable", json={"enabled": True}); assert r.status_code == 200 and r.get_json()["enabled"] is True, r.get_json()
for _ in range(40):
    if tunnel.status()["connected"]: break
    time.sleep(0.1)
assert adm.get("/api/tunnel").get_json()["connected"] is True
assert adm.delete("/api/tunnel/token").status_code == 200
j = adm.get("/api/tunnel").get_json()
assert not j["has_token"] and not j["running"] and not j["enabled"] and not os.path.exists(tunnel.CFG_PATH), j
r = adm.post("/api/tunnel/enable", json={"enabled": True}); assert r.status_code == 400 and "Token" in r.get_json()["error"]
r = adm.post("/api/tunnel/install"); assert r.status_code in (200, 400)
print("5) Endpunkte OK")
tunnel.shutdown()
print("TUNNEL OK")
