"""Periodische Vollladung (webapp._apply_periodic_full_charge, angeregt durch Victrons 'GX Opportunity Loads'):
hebt nur die Ladeobergrenze an, WANN tatsaechlich geladen wird bleibt komplett der normalen preis-/sonnenbewussten
Logik ueberlassen - nie blindes Sofortladen (Max, 30.09.2026)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from logic import Params, PersistentState
from datetime import datetime

apply_fc = webapp.Controller._apply_periodic_full_charge

# ---- Funktion aus (Intervall 0): max_charge_soc bleibt unangetastet, kein "pending"
params = Params(max_charge_soc=95.0, periodic_full_charge_days=0, periodic_full_charge_target_soc=100.0)
state = PersistentState()
apply_fc(state, params, 60.0, datetime(2026, 9, 30))
assert params.max_charge_soc == 95.0 and state.full_charge_pending is False
print("Intervall 0 (aus) -> keine Aenderung OK")

# ---- Noch nie eine Vollladung erreicht -> sofort "faellig", Ladeobergrenze wird angehoben
params = Params(max_charge_soc=95.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
state = PersistentState()
apply_fc(state, params, 60.0, datetime(2026, 9, 30))
assert params.max_charge_soc == 100.0, params.max_charge_soc
assert state.full_charge_pending is True
assert state.last_full_charge_date == ""     # noch nicht erreicht, nur "faellig"
print("Erstmalig faellig (noch nie erreicht) -> Obergrenze angehoben, aber noch nicht erreicht OK")

# ---- Kuerzlich erreicht (vor 5 Tagen bei 30-Tage-Intervall) -> NICHT faellig, Ladeobergrenze bleibt normal
params2 = Params(max_charge_soc=95.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
state2 = PersistentState(last_full_charge_date="2026-09-25")
apply_fc(state2, params2, 60.0, datetime(2026, 9, 30))
assert params2.max_charge_soc == 95.0, params2.max_charge_soc
assert state2.full_charge_pending is False
print("Kuerzlich erreicht (vor 5 von 30 Tagen) -> nicht faellig, normales Ladelimit bleibt OK")

# ---- Genau am Faelligkeitstag (vor 30 Tagen erreicht) -> wieder faellig
params3 = Params(max_charge_soc=95.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
state3 = PersistentState(last_full_charge_date="2026-08-31")   # 30 Tage vor dem 30.09.
apply_fc(state3, params3, 60.0, datetime(2026, 9, 30))
assert params3.max_charge_soc == 100.0, params3.max_charge_soc
print("Genau nach Intervall wieder faellig OK")

# ---- Reales Erreichen des Ziels (SOC >= Ziel - 0.5) waehrend "faellig" -> schliesst den Zyklus ab,
# setzt last_full_charge_date auf heute und pending zurueck
params4 = Params(max_charge_soc=95.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
state4 = PersistentState()
apply_fc(state4, params4, 60.0, datetime(2026, 9, 30))                     # wird faellig
assert state4.full_charge_pending is True
apply_fc(state4, params4, 99.8, datetime(2026, 10, 3))                     # 3 Tage spaeter tatsaechlich fast voll
assert state4.last_full_charge_date == "2026-10-03", state4.last_full_charge_date
assert state4.full_charge_pending is False
print("Ziel real erreicht (99.8% >= 100%-0.5) -> Zyklus abgeschlossen, Datum gesetzt OK")

# ---- NACH Abschluss: sofort wieder anfragen (gleicher Tag, FRISCHES Params-Objekt - genau wie im echten Tick,
# wo Params.from_config(cfg) jeden Durchlauf neu aus der config.json gebaut wird) -> nicht mehr faellig
params4b = Params(max_charge_soc=95.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
apply_fc(state4, params4b, 60.0, datetime(2026, 10, 3))
assert params4b.max_charge_soc == 95.0, "direkt nach Erreichen darf nicht sofort wieder angehoben werden"
print("Direkt nach Erreichen -> nicht sofort wieder faellig OK")

# ---- Sonnentag erreicht das Ziel VON SELBST (ohne dass die Funktion je 'faellig' gemeldet hat, z.B. Intervall
# gerade erst aktiviert) -> auch das zaehlt als Vollladung und setzt das Datum (kein Datenverlust/Doppel-Trigger)
params5 = Params(max_charge_soc=100.0, periodic_full_charge_days=30, periodic_full_charge_target_soc=100.0)
state5 = PersistentState()   # noch nie ein Datum gesetzt
apply_fc(state5, params5, 100.0, datetime(2026, 9, 30))
assert state5.last_full_charge_date == "2026-09-30"
print("Von selbst (z.B. durch Sonne) erreichtes Ziel wird ebenfalls vermerkt OK")

# ---- pv_reserve_kwh wird von der Funktion nicht angefasst (nur max_charge_soc)
params6 = Params(max_charge_soc=95.0, pv_reserve_kwh=5.0, periodic_full_charge_days=1)
state6 = PersistentState()
apply_fc(state6, params6, 60.0, datetime(2026, 9, 30))
assert params6.pv_reserve_kwh == 5.0
print("pv_reserve_kwh bleibt unangetastet OK")

print("FULL CHARGE OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
