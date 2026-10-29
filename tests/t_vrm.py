import os, sys, tempfile, time
from datetime import datetime, timedelta
sys.path.insert(0, sys.argv[1] + "/app")
import vrm
vrm.CREDENTIALS_PATH = os.path.join(tempfile.mkdtemp(), "vrm.json")

assert vrm.forecast()["configured"] is False
for bad in ("", "abc", "12 3"):
    try: vrm.save_credentials(bad, "t"); raise SystemExit("bad id accepted")
    except vrm.VrmError: pass
try: vrm.save_credentials("1", ""); raise SystemExit("no token accepted")
except vrm.VrmError: pass
vrm.save_credentials("844297", "TOK")
vrm.save_credentials("844297", "")            # Token bleibt
assert vrm.load_credentials()["token"] == "TOK"
assert "token" not in vrm.credentials_public()

now = datetime.now().replace(hour=12, minute=30, second=0, microsecond=0)
d0 = now.replace(hour=0, minute=0)
def rec(day_off, vals):
    base = int(d0.timestamp()) + day_off * 86400
    return [[(base + h * 3600 + 7) * 1000, v] for h, v in vals]
payload = {"success": True, "records": {"solar_yield_forecast":
    rec(0, [(8, 400.0), (12, 2000.0), (13, 1000.0)]) + rec(1, [(10, 3000.0), (11, None)])}}
calls = []
def fake(c, params):
    calls.append((c["token"], dict(params))); return payload
vrm._request = fake
r = vrm.forecast(force=True)
print(r["today_kwh"], r["tomorrow_kwh"], r["remaining_today_kwh"], len(r["hours"]))
assert r["today_kwh"] == 3.4 and r["tomorrow_kwh"] == 3.0
s = vrm._summarize(vrm._parse(payload), now); assert s["remaining_today_kwh"] == 2.0, s
assert calls[0][0] == "TOK" and "start" in calls[0][1]
n_calls = len(calls); vrm.forecast(); assert len(calls) == n_calls          # gepuffert

# Fehler: alte Daten bleiben, Fehler wird gemeldet
def boom(c, p): raise vrm.VrmError("Token abgelehnt")
vrm._request = boom
r = vrm.forecast(force=True)
assert r["error"] and r["hours"], r
# Fallback ohne Zeitraum
vrm._cache.update(until=0, data=None, error=None)
seq = []
def fb(c, p):
    seq.append("start" in p); return {"records": {}} if "start" in p else payload
vrm._request = fb
r = vrm.forecast(force=True); assert seq[:2] == [True, False] and r["today_kwh"] == 3.4
# leer
vrm._cache.update(until=0, data=None, error=None)
vrm._request = lambda c, p: {"records": {}}
r = vrm.forecast(force=True); assert r["error"] and not r["hours"]
print("OK")
