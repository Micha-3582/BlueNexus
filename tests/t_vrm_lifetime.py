import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
root = sys.argv[1]
sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
from datetime import datetime, timedelta
import vrm

vrm.load_credentials = lambda: {"token": "t", "installation_id": "1"}

calls = []


def fake_request(c, params):
    start = datetime.fromtimestamp(params["start"]); end = datetime.fromtimestamp(params["end"])
    span_days = (end - start).days
    calls.append(span_days)
    # Nachgebautes VRM-Verhalten: ueber 365 Tage kommt STILLSCHWEIGEND nichts zurueck (kein Fehler!)
    if span_days > 365:
        return {"records": {}}
    rec = {}
    t = start
    while t < end:
        ts = int(t.timestamp()) * 1000
        rec.setdefault("Pb", []).append([ts, 10.0])
        rec.setdefault("Gb", []).append([ts, 1.0])
        rec.setdefault("Bc", []).append([ts, 9.0])
        rec.setdefault("Bg", []).append([ts, 0.5])
        t += timedelta(days=1)
    return {"records": rec}


vrm._request = fake_request

now = datetime(2026, 9, 27, 12, 0)
start = datetime(2025, 9, 6)                    # > 365 Tage vor "now" - genau der reale Fall
res = vrm.battery_lifetime_kwh(now, start)
days_total = (now.date() - start.date()).days
expected_charge = days_total * (10.0 + 1.0)
expected_discharge = days_total * (9.0 + 0.5)
print(res, "erwartete Tage:", days_total, "Chunk-Groessen:", calls)
assert all(span <= 365 for span in calls), calls           # nie wieder ueber die 365-Tage-Grenze anfragen
assert abs(res["charge_kwh"] - expected_charge) < 20, res  # keine grosse Luecke mehr (vorher fehlte fast ein Jahr)
assert abs(res["discharge_kwh"] - expected_discharge) < 20, res
assert res["since"] == "2025-09-06"

print("VRM LIFETIME OK", root.split("/")[-1])
