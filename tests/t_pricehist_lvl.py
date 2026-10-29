"""record_prices() speichert jetzt Tibbers Einstufung (level) mit, price_day() gibt sie zurueck."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from datetime import datetime, timedelta

LEVELS = ["VERY_CHEAP", "CHEAP", "NORMAL", "EXPENSIVE", "VERY_EXPENSIVE"]


def entries(day, lvl=lambda i: LEVELS[i % 5]):
    t0 = datetime.strptime(day, "%Y-%m-%d")
    return [{"startsAt": (t0 + timedelta(minutes=15 * i)).strftime("%Y-%m-%dT%H:%M:%S+02:00"),
             "total": (20 + i % 10) / 100, "level": lvl(i)} for i in range(96)]


assert store.record_prices(entries("2026-09-28")) == 1
rec = store.price_day("2026-09-28")
assert rec["src"] == "tibber" and len(rec["lvl"]) == 96
assert rec["lvl"][0] == "VERY_CHEAP" and rec["lvl"][2] == "NORMAL" and rec["lvl"][4] == "VERY_EXPENSIVE"
print("record_prices() speichert level OK")

# ---- Alter Tag ohne "lvl"-Feld (Datensatz von vor der Umstellung) - price_day() darf nicht crashen,
# sondern muss lvl mit None auffuellen (Rueckwaertskompatibilitaet, siehe store.py-Kommentar)
store._price_days()["2026-09-01"] = {"p": [25.0] * 96, "src": "tibber"}   # kein "lvl"-Key, wie vor dem Update
store._save_price_days(store._price_days())
rec_old = store.price_day("2026-09-01")
assert rec_old["lvl"] == [None] * 96, rec_old["lvl"][:3]
print("Alter Tag ohne lvl -> sauber mit None aufgefuellt OK")

# ---- Nachtraeglich einlaufende Tibber-Preise fuer DENSELBEN Tag ergaenzen/korrigieren lvl genau wie p
# (Merge-Logik: fehlende Slots werden ergaenzt, vorhandene nicht durch None ueberschrieben)
partial = entries("2026-09-29")[:50]      # nur die ersten 50 Slots kommen zuerst rein (z.B. Tibber noch nicht komplett)
assert store.record_prices(partial) == 1
rec_partial = store.price_day("2026-09-29")
assert rec_partial["lvl"][:50] == [LEVELS[i % 5] for i in range(50)]
assert rec_partial["lvl"][50] is None
assert store.record_prices(entries("2026-09-29")) == 1      # jetzt kommen alle 96 nach
rec_full = store.price_day("2026-09-29")
assert rec_full["lvl"] == [LEVELS[i % 5] for i in range(96)], rec_full["lvl"][48:54]
print("Nachtraegliche Ergaenzung (Merge) von p UND lvl OK")

# ---- Unveraendert -> kein erneutes Schreiben (0 geaenderte Tage)
assert store.record_prices(entries("2026-09-29")) == 0
print("Idempotenz (kein Schreiben bei unveraenderten Daten) OK")

print("PRICEHIST LEVEL OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
