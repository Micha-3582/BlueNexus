"""WLED beschaeftigt (503): Wiederholung, Anfragen nacheinander, Namenslisten-Cache, Teilergebnis ohne Effektliste."""
import sys, os, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import wled

busy = {"/json/eff": 2, "/json/state": 0}                  # so oft antwortet der Pfad zuerst mit 503
hits = {}
active = {"n": 0, "max": 0}
lock = threading.Lock()
DATA = {"/json/eff": ["Solid", "Blink"], "/json/pal": ["Default"], "/presets.json": {"1": {"n": "A"}},
        "/json/state": {"on": True, "bri": 255, "seg": [{"col": [[1, 2, 3]], "fx": 0, "pal": 0}]}}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            hits[self.path] = hits.get(self.path, 0) + 1
        time.sleep(0.05)
        code, obj = 200, DATA.get(self.path, {})
        if busy.get(self.path, 0) > 0:
            busy[self.path] -= 1
            code = 503
        b = json.dumps(obj if code == 200 else {"error": 503}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)
        with lock:
            active["n"] -= 1


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
d = {"ip": f"127.0.0.1:{PORT}"}
real_sleep, real_time = time.sleep, time.time
wled.time = type("T", (), {"sleep": staticmethod(lambda s: real_sleep(0.01)), "time": staticmethod(real_time)})      # Wartezeiten im Test kurz

# 1) 503 -> wiederholen, dann klappt es; Effektliste landet im Cache
w = wled.details(d)
assert [e["name"] for e in w["effects"]] == ["Solid", "Blink"] and w["partial"] is False and hits["/json/eff"] == 3, (w, hits)
n = hits["/json/eff"]
wled.details(d)
assert hits["/json/eff"] == n, "Namensliste muss aus dem Cache kommen"
print("1) Wiederholung + Cache OK")

# 2) dauerhaft beschaeftigt: kein Absturz, Teilergebnis (Farbe/Voreinstellungen), alte Liste bleibt nutzbar
wled._names.clear()
busy["/json/eff"] = 99
w = wled.details(d)
assert w["partial"] is True and w["effects"] == [] and w["presets"] and w["color"] == "#010203", w
wled._names[d["ip"]] = (0.0, [{"id": 0, "name": "Solid"}], [])                 # veraltet, aber vorhanden
w = wled.details(d)
assert w["partial"] is False and w["effects"] == [{"id": 0, "name": "Solid"}], w
print("2) Teilergebnis OK")

# 3) Anfragen an dieselbe Lampe nie gleichzeitig; status mit Wiederholung
active["max"] = 0
busy["/json/state"] = 1
res = []
ts = [threading.Thread(target=lambda: res.append(wled.status(d))) for _ in range(6)]
[t.start() for t in ts]
[t.join() for t in ts]
assert active["max"] == 1 and all(r["online"] and r["on"] and r["brightness"] == 100 for r in res), (active, res)
print("WLED BUSY OK")
