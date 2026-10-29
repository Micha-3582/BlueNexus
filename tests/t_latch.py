"""Kurze Impulse (Lichtschranke) gehen den Regeln nicht verloren; Foto-Wiederholung bei Kamerafehler."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, notify

STORE = {}
homematic._get_value = lambda iface, addr, key: STORE.get((iface, addr, key), False)
homematic._unreach = lambda d: False
homematic.set_watch(["PEQ0009003:2"])
homematic._edges.clear(); homematic._latch_used.clear(); homematic._value_cache.clear()

S = {"id": "hm-sen1", "interface": "BidCos-RF", "address": "PEQ0009003:2", "datapoint": "STATE", "binary": True, "kind": "input"}
ev = lambda v: (STORE.__setitem__(("BidCos-RF", "PEQ0009003:2", "STATE"), v), homematic._on_event("BidCos-RF", "PEQ0009003:2", "STATE", v))
rd = lambda latch=True, sen=S: (homematic._value_cache.clear(), homematic.read_sensor(sen, latch))[1]

# 1) Impuls: TRUE und sofort wieder FALSE, bevor die Regelschleife nachschaut
assert rd() is False
ev(True); ev(False)
assert rd(latch=False) is False, "Anzeige bleibt beim echten Zustand"
assert rd() is True, "Regeln bekommen den Impuls einmal"
assert rd() is False, "...aber nur einmal"
print("1) Impuls OK")

# 2) Zweiter Impuls wird wieder gemeldet; ein dauerhaft aktiver Eingang meldet nicht doppelt
ev(True); ev(False); assert rd() is True and rd() is False
ev(True); assert rd() is True, "laeuft gerade"
ev(False); assert rd() is False, "Ende des laufenden Zustands darf nicht nochmal ausloesen"
print("2) Mehrfach OK")

# 3) Anzeige verbraucht den Impuls nicht
ev(True); ev(False); rd(latch=False); rd(latch=False); assert rd() is True
print("3) Anzeige OK")

# 4) zu alter Impuls zaehlt nicht mehr; unbeobachtete Geraete werden nicht gemerkt; invertierter Sensor
ev(True); ev(False); e0 = homematic._edges[("BidCos-RF", "PEQ0009003:2", "STATE")]; e0["t"] = (time.time() - homematic.LATCH_MAX_S - 1, e0["t"][1])
assert rd() is False
homematic._on_event("BidCos-RF", "FREMD0001:1", "STATE", True)
assert not any(k[1].startswith("FREMD") for k in homematic._edges)
inv = {**S, "id": "hm-sen2", "invert": True}
STORE[("BidCos-RF", "PEQ0009003:2", "STATE")] = True
assert rd(sen=inv) is False                      # TRUE = inaktiv bei invertiert (erste Abfrage = Ausgangspunkt, alte Meldungen zaehlen nicht)
ev(False); ev(True)                              # kurz FALSE = aktiv, dann wieder TRUE
assert rd(sen=inv) is True and rd(sen=inv) is False
print("4) Grenzfaelle OK")

# 5) Kamera-Foto: bei sporadischem Fehler wird einmal wiederholt
sent = []
notify.send_photo = lambda jpeg, caption="", token=None, chat_id=None, to=None: sent.append((jpeg, caption))
notify.configured = lambda: True
notify.time.sleep = lambda s: None
calls = []
def flaky():
    calls.append(1)
    if len(calls) == 1:
        raise RuntimeError("Kamera antwortet nicht")
    return b"JPG"
assert notify.photo(flaky, "Hof", {"notify_prefix": False})
for _ in range(50):
    if sent: break
    time.sleep(0.05)
assert sent == [(b"JPG", "Hof")] and len(calls) == 2, (sent, calls)
sent.clear(); calls2 = []
def dead():
    calls2.append(1); raise RuntimeError("tot")
notify.photo(dead, "Hof", {"notify_prefix": False}); time.sleep(0.5)
assert sent == [] and len(calls2) == 2
print("5) Foto-Wiederholung OK")
print("LATCH OK")
