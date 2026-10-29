"""Tasmota schalten: kein zweiter Abruf, PulseTime 0 nur wenn noetig, Zustand aus der Antwort."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, tasmota

json.dump([{"id": "t1", "kind": "tasmota", "mac": "AA", "channel": 1, "gen": 0, "ip": "192.168.178.57", "name": "Steckdose", "icon": "🔌", "model": "T", "show": True},
           {"id": "t2", "kind": "tasmota", "mac": "BB", "channel": 1, "gen": 0, "ip": "192.168.178.58", "name": "Steckdose 2", "icon": "🔌", "model": "T", "show": True},
           {"id": "t3", "kind": "tasmota", "mac": "CC", "channel": 2, "gen": 0, "ip": "192.168.178.59", "name": "Mehrfach K2", "icon": "🔌", "model": "T", "show": True}], open(shelly.DEVICES_PATH, "w"))
sent = []
def fake(ip, cmnd, timeout, auth=None):
    sent.append((ip, cmnd))
    low = cmnd.lower()
    if "status" in low:
        return {"StatusSTS": {"POWER": "ON"}}
    want_on = low.rstrip().endswith("on")
    if ip.endswith(".59"):
        return {"POWER2": "ON" if want_on else "OFF"}
    return {"POWER": "ON" if want_on else "OFF"}
tasmota._cmd = fake
tasmota._pulse_zero.clear()

# Ausschalten: nur ein Befehl, Zustand aus der Antwort, KEIN zweiter Abruf
sent.clear(); r = shelly.set_state("t1", False)
assert sent == [("192.168.178.57", "Power1 Off")], sent
assert r == {"online": True, "on": False, "power": None}, r
# 1. Einschalten (timer 0 = laufenden Timer aufheben): Sammelbefehl mit PulseTime 0
sent.clear(); r = shelly.set_state("t1", True, timer_s=0)
assert sent == [("192.168.178.57", "Backlog PulseTime1 0; Power1 On")], sent
assert r["on"] is True and r["online"] is True
# jedes weitere Einschalten innerhalb der Stunde: nur noch "Power1 On"
for _ in range(3):
    sent.clear(); shelly.set_state("t1", True, timer_s=0)
    assert sent == [("192.168.178.57", "Power1 On")], sent
# anderes Geraet hat seinen eigenen Merker
sent.clear(); shelly.set_state("t2", True, timer_s=0)
assert sent == [("192.168.178.58", "Backlog PulseTime1 0; Power1 On")], sent
# Einschalten MIT Timer (z. B. Regel/Automatik): PulseTime wird gesetzt, der Merker verfaellt
sent.clear(); shelly.set_state("t1", True, timer_s=600)
assert sent == [("192.168.178.57", "Backlog PulseTime1 %d; Power1 On" % tasmota._pulse_value(600))], sent
sent.clear(); shelly.set_state("t1", True, timer_s=0)
assert sent == [("192.168.178.57", "Backlog PulseTime1 0; Power1 On")], "nach einem Timer wird PulseTime wieder auf 0 gestellt: " + str(sent)
# nach einer Stunde sicherheitshalber wieder neu setzen
tasmota._pulse_zero[("192.168.178.57", 1)] -= tasmota.PULSE_ZERO_S + 1
sent.clear(); shelly.set_state("t1", True, timer_s=0)
assert sent[0][1].startswith("Backlog PulseTime1 0"), sent
# ohne Timer-Angabe (normales Einschalten) bleibt ein vorhandener PulseTime unberuehrt
sent.clear(); shelly.set_state("t2", True)
assert sent == [("192.168.178.58", "Power1 On")], sent
# Mehrkanal: Antwort POWER2, Kanalnummer richtig
sent.clear(); r = shelly.set_state("t3", False)
assert sent == [("192.168.178.59", "Power2 Off")] and r["on"] is False, (sent, r)
# Fehler bleiben Fehler (kein falscher "ok"-Zustand)
def boom(ip, cmnd, timeout, auth=None): raise tasmota.requests.ConnectionError("weg")
tasmota._cmd = boom
try:
    shelly.set_state("t1", True); raise AssertionError("haette scheitern muessen")
except shelly.ShellyError as e:
    assert "fehlgeschlagen" in str(e)
# ein gescheiterter Versuch setzt den Merker nicht
tasmota._pulse_zero.clear()
try:
    shelly.set_state("t1", True, timer_s=0)
except shelly.ShellyError:
    pass
assert not tasmota._pulse_zero
# Antwort ohne POWER-Schluessel: gewuenschter Zustand
tasmota._cmd = lambda ip, cmnd, timeout, auth=None: {"Command": "ok"}
assert shelly.set_state("t2", True)["on"] is True and shelly.set_state("t2", False)["on"] is False
print("TASMOTA SCHNELL OK")
