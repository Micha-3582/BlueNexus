"""Regelrunde (1.34.11): wartet hoechstens `deadline` Sekunden auf die Geraete; ein langsames Geraet zaehlt mit dem letzten bekannten Zustand."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly

devs = [{"id": "fast", "kind": "tasmota", "ip": "1.1.1.1", "name": "Schnell"}, {"id": "slow", "kind": "tasmota", "ip": "1.1.1.2", "name": "Langsam"}]
shelly.load_devices = lambda: [dict(d) for d in devs]
SLOW = {"s": 0.0}


def fake_live(d):
    if d["id"] == "slow":
        time.sleep(SLOW["s"])
        return {"online": True, "on": True, "power": 3.0}
    return {"online": True, "on": False, "power": None}


shelly._status_live = fake_live
# 1) ohne Verzoegerung: beide Zustaende frisch
out = {d["id"]: d for d in shelly.list_with_status(ids={"fast", "slow"}, deadline=0.5)}
assert out["slow"]["on"] is True and not out["slow"].get("stale") and out["fast"]["on"] is False
# 2) das Geraet haengt: die Runde dauert nicht laenger als die Frist, es zaehlt mit dem letzten Zustand (stale)
SLOW["s"] = 2.0
t0 = time.time()
out = {d["id"]: d for d in shelly.list_with_status(ids={"fast", "slow"}, deadline=0.5)}
dt = time.time() - t0
assert dt < 1.0, dt
assert out["slow"]["on"] is True and out["slow"].get("stale") is True and out["fast"]["on"] is False, out
# 3) Geraet ohne bekannten Zustand: es wird abgewartet (sonst wuesste die Regel gar nichts)
shelly._st_cache.clear(); shelly._last_ok.clear(); shelly._down.clear()
SLOW["s"] = 0.8
t0 = time.time()
out = {d["id"]: d for d in shelly.list_with_status(ids={"slow"}, deadline=0.3)}
assert out["slow"]["on"] is True and time.time() - t0 >= 0.7
# 4) ohne Frist wie bisher: es wird gewartet
SLOW["s"] = 0.6
t0 = time.time(); shelly.list_with_status(ids={"slow"}); assert time.time() - t0 >= 0.55
print("OK")
