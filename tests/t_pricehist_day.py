"""store.price_day() + /api/prices/history?day= (Tage-zurueck-Blick im Strompreis-Diagramm, siehe index.html)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from datetime import datetime, timedelta


def entries(day, ct=lambda i: 20 + i % 10):
    t0 = datetime.strptime(day, "%Y-%m-%d")
    return [{"startsAt": (t0 + timedelta(minutes=15 * i)).astimezone().isoformat(timespec="seconds"), "total": ct(i) / 100} for i in range(96)]


store.record_prices(entries("2026-09-20"))
assert store.price_day("2026-09-19") is None                      # kein Eintrag -> None, kein Crash
rec = store.price_day("2026-09-20")
assert rec is not None and rec["src"] == "tibber" and len(rec["p"]) == 96 and rec["p"][5] == 25.0
print("store.price_day() OK")

# ---- Derived-Tag (aus Bezugskosten zurueckgerechnet) wird ebenfalls zurueckgegeben (anders als price_slots())
store._price_days()["2026-09-21"] = {"p": [None] * 40 + [30.0] * 56, "src": "derived"}
store._save_price_days(store._price_days())
rec2 = store.price_day("2026-09-21")
assert rec2["src"] == "derived" and rec2["p"][45] == 30.0 and rec2["p"][0] is None
print("store.price_day() derived OK")

# ---- HTTP-Endpunkt mit ?day= gibt genau EINEN Tag zurueck, ohne die Sammel-Info zu berechnen
webapp.users = __import__("auth").UserStore(os.path.join(tmp, "users.json"))
webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client()
c.post("/login", data={"username": "admin", "password": "adminpass1"})
r = c.get("/api/prices/history?day=2026-09-20").get_json()
assert r["day"] == "2026-09-20" and r["record"]["src"] == "tibber" and len(r["record"]["p"]) == 96, r
r2 = c.get("/api/prices/history?day=2099-01-01").get_json()
assert r2["record"] is None, r2                                   # nicht vorhandener Tag -> record: null, kein 500er
r3 = c.get("/api/prices/history?days=5").get_json()
assert "info" in r3 and "days" in r3, r3                          # alte Sammel-Antwort bleibt unveraendert nutzbar
print("HTTP /api/prices/history?day= OK")

print("PRICEHIST DAY OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
