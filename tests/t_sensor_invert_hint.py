"""Hinweis "Sensor umgekehrt" in der Regel-Anzeige (1.63.4): Ist bei einem Sensor "Wert umkehren" eingeschaltet, nennt der Text der Bedingung es (Regelliste,
Regel-Logbuch), im Regel-Editor steht ein Vermerk neben dem Zustand. Fenster/Tueren sind von Haus aus umgekehrt: dort kein Hinweis.
Hintergrund: Bei einem umgekehrten Bewegungsmelder stand in zwei Regeln "keine Bewegung (TRUE)", die Regeln loesten erst nach der Nachlaufzeit des Melders aus."""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules as R

NOW = datetime.datetime(2026, 1, 1, 12, 0)


def txt(kind, invert, is_, val=True):
    info = {"id": "x", "name": "Flur", "kind": kind}
    if invert is not None:
        info["invert"] = invert
    return R.eval_condition({"type": "sensor", "sensor_id": "x", "is": is_}, {"now": NOW, "sensors": {"x": val}, "sensor_info": {"x": info}})


# Bewegungsmelder, umgekehrt: Hinweis; TRUE heisst hier "keine Bewegung"
ok, t = txt("motion", True, True)
assert ok is True and t == "Flur: keine Bewegung (TRUE, Sensor umgekehrt)", t
ok, t = txt("motion", True, False, val=False)
assert ok is True and t == "Flur: Bewegung erkannt (FALSE, Sensor umgekehrt)", t          # so sieht die richtige Regel aus
# nicht umgekehrt: kein Hinweis
assert txt("motion", False, True)[1] == "Flur: Bewegung erkannt (TRUE)"
assert txt("motion", None, False, val=False)[1] == "Flur: keine Bewegung (FALSE)"
# Fenster/Tuer: von Haus aus umgekehrt, kein Hinweis (Text wie bisher)
assert txt("contact", True, True)[1] == "Flur: geschlossen (TRUE)"
# Sensor ohne Woerter (wahr/falsch), umgekehrt: Hinweis
assert txt("generic", True, True)[1] == "Flur: wahr (TRUE, Sensor umgekehrt)", txt("generic", True, True)[1]
# Messwert-Bedingungen bleiben unberuehrt
ok, t = R.eval_condition({"type": "sensor", "sensor_id": "x", "op": "above", "value": 5.0}, {"now": NOW, "sensors": {"x": 6.0}, "sensor_info": {"x": {"id": "x", "name": "Temp", "kind": "temperature", "unit": "°C", "invert": True}}})
assert t == "Temp über 5 °C", t

# --- Regel-Editor: Vermerk im Quelltext (Regressionswaechter)
src = open(os.path.join(os.path.dirname(os.path.abspath(webapp.__file__)), "templates", "rules.html"), encoding="utf-8").read()
assert "sen.invert && sen.kind !== 'contact'" in src and "⇄ Wert umgekehrt" in src and "⇄ umgekehrt" in src
assert src.count("sen.invert && sen.kind !== 'contact'") == 2                                  # Editor und Kurzfassung

print("t_sensor_invert_hint OK")
