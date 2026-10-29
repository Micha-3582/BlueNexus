import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import vrm, vrm_import
from datetime import datetime, timedelta

# ---- vrm.load_credentials so faelschen, dass run() ueberhaupt startet
vrm.load_credentials = lambda: {"token": "t", "installation_id": "123"}

now = datetime(2026, 9, 28, 10, 7)
DAYS = 388                      # seit Installation ca. 06.09.2025 bis heute
start_expected = (now - timedelta(days=DAYS - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

# ---- Fake-VRM: liefert fuer den GESAMTEN angefragten Zeitraum synthetische 15-Min-Slots,
# genau wie das echte vrm.py es (in 7-Tage-Haeppchen, CHUNK_DAYS=7) tun wuerde. Wir pruefen hier
# NICHT das Chunking selbst (das ist reiner HTTP-Batching-Code in vrm.py, CHUNK_DAYS=7 bereits
# verifiziert weit unter dem 365-Tage-VRM-Limit), sondern dass vrm_import.run(days=DAYS) den
# kompletten Zeitraum anfragt und store.import_history_slots() alles verlustfrei uebernimmt.
calls = []
def fake_fetch_flow(c, start, end):
    calls.append((start, end))
    assert start == start_expected, f"vrm_import haette ab {start_expected} anfragen sollen, hat aber {start}"
    out = {}
    t = start
    while t < end:
        k = f"{t:%Y-%m-%dT%H:%M}"
        out[k] = {"s_load": 0.05, "s_batt": 0.02, "s_grid": 0.01, "b_load": 0.01, "g_load": 0.03, "g_batt": 0.0, "b_grid": 0.0}
        t += timedelta(minutes=15)
    return out, {"15mins"}

def fake_fetch_soc(c, start, end):
    out = {}
    t = start
    while t < end:
        out[f"{t:%Y-%m-%dT%H:%M}"] = 55.0
        t += timedelta(minutes=15)
    return out

vrm.fetch_flow_slots = fake_fetch_flow
vrm.fetch_soc_slots = fake_fetch_soc

# ---- Vorschau (apply=False): darf NICHTS schreiben
res_preview = vrm_import.run(apply=False, now=now, days=DAYS)
assert res_preview["applied"] is False
expected_slots = DAYS * 96 - 1        # letzter laufender Slot (== end) wird bewusst ausgeschlossen
# der `end`-Slot selbst (10:00) wird per end_key-Filter ausgeschlossen -> DAYS*96 minus die Slots ab 10:00 exklusive... einfacher: pruefen ueber history_keys()
assert store.history_keys() == set(), "Vorschau darf noch nichts in die History geschrieben haben"
print("Vorschau meldet", res_preview["slots"], "fehlende Viertelstunden ueber", DAYS, "Tage")
assert res_preview["slots"] > DAYS * 90, "erwarte fast 96 Slots/Tag ueber den ganzen Zeitraum"

# ---- Uebernehmen (apply=True): schreibt in history.json -> beim naechsten Tick wandert Vergangenes automatisch ins Archiv
res_apply = vrm_import.run(apply=True, now=now, days=DAYS)
assert res_apply["applied"] is True
print("Uebernommen:", res_apply["added"], "Slots")
assert res_apply["added"] == res_preview["slots"]

# ---- alter Tag (ganz am Anfang des Backfills) muss vollstaendig lesbar sein - Datenverlust-Check
oldest_day = start_expected.date().isoformat()
hist = store.energy_history_for_day(oldest_day, now=now)
assert len(hist) == 96, f"aeltester Backfill-Tag {oldest_day} hat nicht alle 96 Slots: {len(hist)}"
assert all(row["solar"] > 0 for row in hist), "Backfill-Slots sollten ueberall Werte haben (kein Leerwert)"
print("Aeltester Tag", oldest_day, "vollstaendig mit", len(hist), "Slots")

# ---- WICHTIG: erneuter Import (z.B. versehentlich zweimal geklickt) darf NICHTS ueberschreiben/duplizieren
res_again = vrm_import.run(apply=True, now=now, days=DAYS)
assert res_again["slots"] == 0 and res_again.get("added", 0) in (0, None), \
    f"zweiter Lauf haette nichts mehr finden duerfen (kein Ueberschreiben vorhandener Daten), fand aber {res_again}"
print("Zweiter Lauf (Idempotenz) OK: nichts mehr zu tun,", res_again["slots"], "Slots")

# ---- Archivierung nach einem "Tages-Tick" faengt den Backfill korrekt ein (kein Datenverlust beim Uebergang heiss->Archiv)
store.archive_finished_days(now)
buckets = store._day_buckets(oldest_day)
assert len(buckets) == 96, f"nach dem Archivieren fehlen Slots am aeltesten Tag: {len(buckets)}"
print("Nach Archivierung weiterhin 96 Slots am aeltesten Tag:", oldest_day)

print("VRM BACKFILL (LANGER ZEITRAUM) OK")
