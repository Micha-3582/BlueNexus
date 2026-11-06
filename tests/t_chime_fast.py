"""Chime aus Regeln (1.34.10): Chime-Nummern werden gemerkt, Laeuten = ein Abruf; veraltete Nummer -> Liste neu holen; mehrere Chimes gleichzeitig."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera

CALLS = []
PAIRED = [{"deviceId": 7, "netState": 2}, {"deviceId": 9, "netState": 2}, {"deviceId": 11, "netState": 0}]
BAD = set()


def fake_call(item, cmd, param=None, action=0, strict=True):
    CALLS.append((cmd, (param or {}).get("DingDong", {}).get("id")))
    if cmd == "GetDingDongList":
        return {"DingDongList": {"pairedlist": PAIRED}}
    i = param["DingDong"]["id"]
    if i in BAD:
        raise camera.CameraError("weg")
    time.sleep(0.2)
    return {}


camera._call = fake_call
cam = {"id": "c1", "channel": 0}

assert camera.chime_ring_all(cam, 5) == 2                      # erster Lauf: Liste + 2 x Laeuten
assert [c[0] for c in CALLS].count("GetDingDongList") == 1 and len(CALLS) == 3, CALLS
CALLS.clear()
t0 = time.time()
assert camera.chime_ring_all(cam, 5) == 2                      # zweiter Lauf: nur Laeuten, beide gleichzeitig
assert [c[0] for c in CALLS] == ["DingDongOpt", "DingDongOpt"], CALLS
assert time.time() - t0 < 0.35, time.time() - t0               # nicht 2 x 0,2 s hintereinander
# veraltete Nummer: Liste wird einmal neu geholt
CALLS.clear(); camera._chime_ids["c1"] = (time.time(), [99]); BAD.add(99)
assert camera.chime_ring_all(cam, 5) == 2
assert CALLS[0] == ("DingDongOpt", 99) and ("GetDingDongList", None) in CALLS, CALLS
# kein Chime verbunden
PAIRED[:] = []; camera._chime_ids.clear()
try:
    camera.chime_ring_all(cam, 5); raise AssertionError("muss scheitern")
except camera.CameraError as e:
    assert "Kein Chime" in str(e)
print("OK")
