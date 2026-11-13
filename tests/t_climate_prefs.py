"""Vorgaben der Klimaanlagen sind fuer alle Marken gleich: Was in BlueNexus (Klimafenster) von Hand eingestellt wurde, gilt bei jedem Einschalten
(Ueberschuss-Automatik, Regeln, Kachel), bis es dort wieder geaendert wird. Hier die Midea-Anlage (ESPHome prueft t_esphome_ac.py)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, midea

D = {"id": "mid1", "name": "Schlafzimmer", "kind": "midea", "ip": "192.168.1.50", "switchable": True}
STATE = {"on": False, "mode": "cool", "target_c": 22.0, "fan": "auto", "swing": "off", "eco": False, "online": True}
CALLS = []


def fake_status(d):
    return dict(STATE, power=None, info="x")


def fake_set(d, **kw):
    CALLS.append(kw)
    if "power" in kw:
        STATE["on"] = bool(kw["power"])
    for k, key in (("mode", "mode"), ("target", "target_c"), ("fan", "fan"), ("swing", "swing"), ("eco", "eco")):
        if k in kw:
            STATE[key] = kw[k]
    return fake_status(d)


midea.status = fake_status
midea.set_params = fake_set
shelly._midea_dev = lambda dev_id: D
if os.path.exists(shelly.CLIMATE_PREFS_PATH):
    os.remove(shelly.CLIMATE_PREFS_PATH)

# 1) Erste Beobachtung der laufenden Anlage legt die Vorgabe an (der jetzige Stand gilt sofort)
STATE.update(on=True, mode="heat", target_c=30.0, fan="high", swing="off", eco=False)
shelly.status(D)
assert shelly.climate_prefs("mid1") == {"mode": "heat", "target": 30.0, "fan": "high", "swing": "off", "eco": False}, shelly.climate_prefs("mid1")

# 2) Aus -> Ueberschuss-Automatik / Kachel / Regel schalten ein: immer mit der Vorgabe
for how in ("climate_power_on", "midea_set"):
    STATE.update(on=False, mode="cool", target_c=22.0, fan="auto")                      # die Anlage hat selbst etwas anderes gespeichert / Fernbedienung
    CALLS.clear()
    shelly.climate_power_on(D) if how == "climate_power_on" else shelly.midea_set("mid1", power=True)
    assert CALLS == [{"power": True, "mode": "heat", "target": 30.0, "fan": "high", "swing": "off", "eco": False}], (how, CALLS)

# 3) Laeuft sie schon: nichts umstellen
CALLS.clear(); shelly.climate_power_on(D)
assert CALLS == [{"power": True}], CALLS

# 4) Aenderung ohne remember (Regel, Fernbedienung) aendert die Vorgabe nicht; im Klimafenster (remember) schon
shelly.midea_set("mid1", target=18.0)
assert shelly.climate_prefs("mid1")["target"] == 30.0
shelly.midea_set("mid1", target=24.5, fan="low", remember=True)
assert shelly.climate_prefs("mid1")["target"] == 24.5 and shelly.climate_prefs("mid1")["fan"] == "low" and shelly.climate_prefs("mid1")["mode"] == "heat"

# 5) Ausdruecklich genannte Werte gehen vor der Vorgabe
STATE["on"] = False; CALLS.clear()
shelly.climate_power_on(D, {"target": 20.0})
assert CALLS == [{"power": True, "mode": "heat", "target": 20.0, "fan": "low", "swing": "off", "eco": False}], CALLS
assert shelly.climate_prefs("mid1")["target"] == 24.5                                  # ohne remember bleibt die Vorgabe

print("t_climate_prefs OK")
