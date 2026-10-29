"""cloudflared: Update-Anzeige und -Installation (alles gemockt, kein Netz, kein echter Prozess)."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import tunnel
from auth import UserStore

tunnel.BIN_DIR = os.path.join(tmp, "bin"); tunnel.BIN_PATH = os.path.join(tunnel.BIN_DIR, "cloudflared")
tunnel.CFG_PATH = os.path.join(tmp, "cf.json"); tunnel.PID_PATH = os.path.join(tmp, "cf.pid")
tunnel.asset_name = lambda: "cloudflared-linux-amd64"
tunnel.sandbox.ACTIVE = False

# Version vergleichen
assert tunnel._ver_tuple("2025.9.1") > tunnel._ver_tuple("2025.8.1") > tunnel._ver_tuple("2024.12.2")
assert tunnel._ver_tuple("2025.10.0") > tunnel._ver_tuple("2025.9.9") and tunnel._ver_tuple("") == ()


# Versionsabfrage (Weiterleitung auf .../tag/<Version>)
class R:
    def __init__(self, loc=""):
        self.headers = {"Location": loc}


heads = []
def fake_head(url, **kw):
    heads.append(url); return R("https://github.com/cloudflare/cloudflared/releases/tag/2026.1.0")
tunnel.requests.head = fake_head
assert tunnel.fetch_latest() == "2026.1.0"
tunnel.requests.head = lambda url, **kw: R("")
assert tunnel.fetch_latest() == ""
def boom(url, **kw): raise tunnel.requests.ConnectionError("offline")
tunnel.requests.head = boom
assert tunnel.fetch_latest() == ""

# Zwischenspeicher: nur einmal fragen, Fehlschlag erst nach Wartezeit wieder
tunnel._latest.update(ver="", at=0.0, tried=0.0)
tunnel.requests.head = fake_head; heads.clear()
assert tunnel.check_latest() == "2026.1.0" and tunnel.check_latest() == "2026.1.0" and len(heads) == 1
assert tunnel.check_latest(force=True) == "2026.1.0" and len(heads) == 2
tunnel._latest.update(ver="", at=0.0, tried=0.0); tunnel.requests.head = boom
assert tunnel.check_latest() == "" and tunnel._latest["tried"] > 0
tunnel.requests.head = fake_head; heads.clear()
assert tunnel.check_latest() == "" and not heads                      # zu frueh nach dem Fehlschlag
tunnel._latest["tried"] = time.time() - 1000
assert tunnel.check_latest() == "2026.1.0"

# Programm "installiert" (Version aus dem Dateiinhalt)
os.makedirs(tunnel.BIN_DIR, exist_ok=True)
open(tunnel.BIN_PATH, "w").write("v2025.8.1"); os.chmod(tunnel.BIN_PATH, 0o755)
tunnel._version_uncached = lambda b: open(b).read().strip().lstrip("v") if os.path.isfile(b) and os.path.getsize(b) < 200 or b.endswith(".part") else ""
tunnel.find_binary = lambda: tunnel.BIN_PATH if os.path.isfile(tunnel.BIN_PATH) else None
tunnel._ver_cache.clear()
st = tunnel.status()
assert st["version"] == "2025.8.1" and st["latest"] == "2026.1.0" and st["update"] is True, st
tunnel._latest["ver"] = "2025.8.1"
assert tunnel.status()["update"] is False
tunnel._latest["ver"] = ""
assert tunnel.status()["update"] is False                             # unbekannt = kein Update anzeigen
tunnel._latest["ver"] = "2026.1.0"


# Update installieren: gueltiges Programm wird ersetzt
class Resp:
    def __init__(self, data): self.data = data
    def raise_for_status(self): pass
    def iter_content(self, n):
        for i in range(0, len(self.data), n): yield self.data[i:i + n]


good = b"v2026.1.0" + b" " * 1_100_000
tunnel.os.access = lambda p, m: True
def fake_get(url, **kw):
    assert url.endswith("cloudflared-linux-amd64"), url
    return Resp(good)
tunnel.requests.get = fake_get
tunnel._version_uncached = lambda b: (open(b, "rb").read(20).decode("latin1").strip().lstrip("v") if os.path.isfile(b) else "")
tunnel._running = lambda: False
v = tunnel.update()
assert v == "2026.1.0", v
assert tunnel.status()["version"] == "2026.1.0" and tunnel.status()["update"] is False

# Kaputtes Programm: das alte bleibt erhalten
open(tunnel.BIN_PATH, "wb").write(b"v2025.8.1" + b" " * 1_100_000)
tunnel._ver_cache.clear()
broken = b"X" * 1_100_000
tunnel.requests.get = lambda url, **kw: Resp(broken)
tunnel._version_uncached = lambda b: ("2025.8.1" if b == tunnel.BIN_PATH else "")
try:
    tunnel.install(); raise AssertionError("haette scheitern muessen")
except tunnel.TunnelError as e:
    assert "bisherige bleibt" in str(e), e
assert open(tunnel.BIN_PATH, "rb").read(9) == b"v2025.8.1"
assert not os.path.exists(tunnel.BIN_PATH + ".part")

# Lief der Tunnel: nach dem Update wird neu gestartet
tunnel._version_uncached = lambda b: (open(b, "rb").read(20).decode("latin1").strip().lstrip("v") if os.path.isfile(b) else "")
tunnel.requests.get = fake_get
started = []
tunnel._running = lambda: True
tunnel.enabled = lambda: True
tunnel.start = lambda: started.append(1)
tunnel.update()
assert started == [1]

# Web: Rechte (Einstellungen: System) und Antworten
webapp.users = UserStore(os.path.join(tmp, "u_tn.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "settings_system": "read"})
webapp.users.create("lena", "lenapass12", {"dashboard": "write"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I, L = login("admin", "adminpass1"), login("ina", "inapass123"), login("lena", "lenapass12")
tunnel._running = lambda: False; started.clear()
tunnel.requests.head = fake_head
r = A.post("/api/tunnel/check"); assert r.status_code == 200 and r.get_json()["latest"] == "2026.1.0", r.get_json()
open(tunnel.BIN_PATH, "wb").write(b"v2025.8.1" + b" " * 1_100_000); tunnel._ver_cache.clear()
r = A.get("/api/tunnel"); assert r.get_json()["update"] is True, r.get_json()
assert I.get("/api/tunnel").status_code == 200                           # Lesen darf, wer den Bereich lesen darf
assert I.post("/api/tunnel/check").status_code == 403 and I.post("/api/tunnel/update").status_code == 403
assert L.get("/api/tunnel").status_code == 403 and L.post("/api/tunnel/update").status_code == 403
r = A.post("/api/tunnel/update"); assert r.status_code == 200 and r.get_json()["version"] == "2026.1.0", r.get_json()
assert A.get("/api/tunnel").get_json()["update"] is False
print("TUNNEL UPDATE OK")
