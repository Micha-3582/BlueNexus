"""Kurze Aussetzer von WLAN-Geraeten (1.34.9): ein einzelner Fehlversuch macht ein eben noch erreichbares Geraet nicht sofort 'nicht erreichbar'."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly

calls = {"n": 0}
SEQ = []


def fake_live(d):
    calls["n"] += 1
    return SEQ.pop(0) if SEQ else {"online": True, "on": True, "power": 5.0}


shelly._status_live = fake_live
OK = {"online": True, "on": True, "power": 5.0}
BAD = {"online": False, "on": None, "power": None}
d = {"id": "t1", "kind": "tasmota", "ip": "1.2.3.4"}

# 1) Aussetzer direkt nach einer guten Antwort: zweiter Versuch klappt -> bleibt online
SEQ[:] = [dict(OK)]
assert shelly.status(d)["online"] is True
SEQ[:] = [dict(BAD), dict(OK)]
st = shelly.status(d)
assert st["online"] is True and not st.get("stale"), st

# 2) beide Versuche scheitern, aber kurz zuvor ging es: letzter Zustand bleibt (stale), kein Ruhezustand
SEQ[:] = [dict(BAD), dict(BAD)]
st = shelly.status(d)
assert st["online"] is True and st.get("stale") is True and st["on"] is True, st
assert "t1" not in shelly._down, shelly._down
SEQ[:] = [dict(OK)]
assert shelly.status(d).get("stale") is None

# 3) nach Ablauf der Schonfrist gilt es wirklich als nicht erreichbar (mit Ruhezeit)
shelly._last_ok["t1"] = (time.time() - shelly.BLIP_GRACE_S - 5, dict(OK))
SEQ[:] = [dict(BAD)]
n0 = calls["n"]
st = shelly.status(d)
assert st["online"] is False and calls["n"] - n0 == 1, (st, calls["n"] - n0)
assert "t1" in shelly._down

# 4) ein Geraet, das noch nie geantwortet hat, wird nicht doppelt gefragt
shelly._down.clear()
d2 = {"id": "t2", "kind": "tasmota", "ip": "1.2.3.5"}
SEQ[:] = [dict(BAD)]
n0 = calls["n"]
assert shelly.status(d2)["online"] is False and calls["n"] - n0 == 1
print("OK")
