import sys, os, tempfile, shutil
root = sys.argv[1]
sys.path.insert(0, root + "/app")
import store

tmp = tempfile.mkdtemp()
store.HISTORY_PATH = os.path.join(tmp, "history.json")
store.MONTHLY_PATH = os.path.join(tmp, "monthly_summary.json")
store.HISTORY_ARCHIVE_DIR = os.path.join(tmp, "history_archive")
store.SAVINGS_PATH = os.path.join(tmp, "savings_days.json")
store.PRICE_HISTORY_PATH = os.path.join(tmp, "price_history.json")
store._price_cache = None
store.BACKUP_DIR = os.path.join(tmp, "backups")

import datetime as dt

# ---- Hilfsfunktion: einen Tag lang alle 15 Min ein Sample schreiben (feste, bekannte Werte,
# damit wir hinterher exakt nachrechnen koennen wieviel reingesteckt wurde -> Datenverlust-Check).
# WICHTIG: prev/TOTAL laufen durchgehend UEBER Tagesgrenzen hinweg weiter (genau wie die App das
# echte Trapez auch ueber Mitternacht hinweg bildet) - sonst faellt hier faelschlich pro Tag eine
# Viertelstunde "unter den Tisch" und es sieht wie Datenverlust aus, obwohl nur der Test falsch zaehlt.
TOTAL_SOLAR_FED = 0.0
TOTAL_VERBRAUCH_FED = 0.0
_prev_t = None

def feed_day(day: dt.date, pv_w=1000.0, load_w=500.0, soc=55.0):
    global TOTAL_SOLAR_FED, TOTAL_VERBRAUCH_FED, _prev_t
    t = dt.datetime(day.year, day.month, day.day, 0, 0)
    end = t + dt.timedelta(days=1)
    while t < end:
        system = {"solar_total": pv_w, "grid": {"total": 0.0}, "loads": {"total": load_w},
                   "battery": {"soc": soc}}
        store.log_energy_sample(system, now=t, price_ct=30.0)
        if _prev_t is not None:
            h = (t - _prev_t).total_seconds() / 3600.0
            TOTAL_SOLAR_FED += pv_w / 1000.0 * h
            TOTAL_VERBRAUCH_FED += load_w / 1000.0 * h
        _prev_t = t
        t += dt.timedelta(minutes=15)

d0 = dt.date(2026, 1, 1)
for i in range(5):                      # 5 volle Tage durchlaufen lassen (ueber mehrere Mitternaechte hinweg)
    feed_day(d0 + dt.timedelta(days=i))

# Nach 5 Tagen: "heute" ist der Tag NACH dem letzten gefuetterten Tag noch nicht angebrochen -
# der letzte gefuetterte Tag (Tag 5) ist noch "heute" aus Sicht der Simulation (kein Tick danach).
last_day = d0 + dt.timedelta(days=4)
now_after = dt.datetime(last_day.year, last_day.month, last_day.day, 23, 59)

hot = store._load_history().get("hours", {})
hot_days = sorted({k[:10] for k in hot.keys()})
print("Tage noch in der heissen Datei:", hot_days)
assert hot_days == [last_day.isoformat()], f"Nur der letzte (laufende) Tag sollte noch heiss sein, ist aber {hot_days}"

# ---- Archiv pruefen: alle 4 vorherigen Tage muessen mit voller Aufloesung da sein
for i in range(4):
    day = (d0 + dt.timedelta(days=i)).isoformat()
    buckets = store._day_buckets(day)
    assert len(buckets) == 96, f"{day}: erwarte 96 Viertelstunden-Slots im Archiv, habe {len(buckets)}"

# ---- Kein Datenverlust: Summe ueber ALLE Tage (heiss + archiviert) muss exakt der Einspeisung entsprechen
total_solar_seen = 0.0
total_verbrauch_seen = 0.0
for i in range(5):
    day = (d0 + dt.timedelta(days=i)).isoformat()
    for b in store._day_buckets(day).values():
        total_solar_seen += b.get("solar", 0.0)
        total_verbrauch_seen += b.get("verbrauch", 0.0)
print(f"Solar gefuettert={TOTAL_SOLAR_FED:.3f} gesehen={total_solar_seen:.3f}")
print(f"Verbrauch gefuettert={TOTAL_VERBRAUCH_FED:.3f} gesehen={total_verbrauch_seen:.3f}")
assert abs(total_solar_seen - TOTAL_SOLAR_FED) < 0.01, "Solar-Datenverlust!"
assert abs(total_verbrauch_seen - TOTAL_VERBRAUCH_FED) < 0.01, "Verbrauch-Datenverlust!"

# ---- energy_history_for_day fuer einen laengst archivierten Tag liefert die vollen 96 Slots zurueck
hist = store.energy_history_for_day(d0.isoformat(), now=now_after)
assert len(hist) == 96
assert sum(row["solar"] for row in hist) > 20, "archivierter Tag sollte ueberall Solar-Werte haben"
assert all(row["solar"] > 0 for row in hist[1:]), "ausser dem allerersten (kein Vorgaenger fuers Trapez) sollte jeder Slot Solar haben"

# ---- energy_min_day findet den aeltesten archivierten Tag
assert store.energy_min_day() == d0.isoformat(), store.energy_min_day()

# ---- energy_week_summary ueber archivierte + heisse Tage hinweg
week = store.energy_week_summary(now=now_after, days=5, offset_weeks=0)
days_out = {r["day"]: r for r in week["days"]}
for i in range(5):
    day = (d0 + dt.timedelta(days=i)).isoformat()
    assert days_out[day]["solar"] > 0, f"{day} fehlt in der Wochenuebersicht (Archiv nicht eingebunden?)"

# ---- history_keys() sieht auch archivierte Slots (fuer den VRM-Nachhol-Import)
keys = store.history_keys()
assert f"{d0.isoformat()}T12:00" in keys, "archivierter Slot fehlt in history_keys()"

# ---- Monatssummen (Monatsueberblick) unveraendert korrekt
mo = store.monthly_overview(now=now_after)
jan = next(m for m in mo["months"] if m["month"] == "2026-01")
assert jan["solar"] > 0 and abs(jan["solar"] - total_solar_seen) < 0.05, jan

# ---- savings(): ein Tag, der nur noch im Archiv liegt (nie vorher "gesehen"), wird trotzdem einmalig eingefroren
cfg = {"tariff_mode": "fixed", "fixed_price_ct": 30.0}
res = store.savings(cfg, now=now_after)
assert res["available"], res
saved_days = {r["date"] for r in res["days"]}
assert d0.isoformat() in saved_days, f"archivierter Tag {d0} wurde von savings() nicht nachgeholt: {saved_days}"

print("ARCHIVE NO-DATA-LOSS OK", root.split("/")[-1])

# ---- Sicherheitsnetz: schlaegt das Archiv-Schreiben fehl (z.B. Platte voll), bleibt der Slot in
# der heissen Datei (kein Datenverlust), statt einfach zu verschwinden. Dazu VOR dem naechsten
# Tageswechsel kaputt machen, damit der automatische Archivierungsversuch beim ersten Tick des
# neuen Tages fehlschlaegt (archive_finished_days() selbst faende zu diesem Zeitpunkt nichts mehr
# zu tun, weil log_energy_sample schon bei jedem Tick automatisch archiviert).
d6 = d0 + dt.timedelta(days=5)
_orig_append = store._append_full_days_to_archive
def _boom(per_day_full):
    raise OSError("Platte simuliert voll")
store._append_full_days_to_archive = _boom
try:
    feed_day(d6)                     # erster Tick von Tag 6 versucht, Tag 5 zu archivieren -> schlaegt fehl
    assert False, "haette die Exception durchreichen sollen"
except OSError:
    pass
store._append_full_days_to_archive = _orig_append
# Trotz Fehlschlag: Tag 5 (2026-01-05) darf NICHT verloren sein - muss noch in der heissen Datei stehen
hot_after_fail = store._load_history().get("hours", {})
assert any(k.startswith("2026-01-05") for k in hot_after_fail), "Tag nach fehlgeschlagenem Archivieren verloren gegangen!"
print("SAFETY NET OK (Fehler beim Archivieren verliert keine Daten)")

# jetzt ohne Fehler zu Ende fuettern - der naechste Tick archiviert Tag 5 (und ggf. weitere) nach
now2 = dt.datetime(d6.year, d6.month, d6.day, 23, 59)
store.log_energy_sample({"solar_total": 1000.0, "grid": {"total": 0.0}, "loads": {"total": 500.0},
                          "battery": {"soc": 55.0}}, now=now2, price_ct=30.0)
hot_final = store._load_history().get("hours", {})
hot_days_final = sorted({k[:10] for k in hot_final.keys()})
assert hot_days_final == [d6.isoformat()], hot_days_final
buckets_05 = store._day_buckets("2026-01-05")
assert len(buckets_05) == 96, len(buckets_05)

# ---- Idempotenz: archive_finished_days zweimal hintereinander aufrufen darf nichts doppelt zaehlen
mo_before = store.monthly_overview(now=now2)
jan_before = next(m for m in mo_before["months"] if m["month"] == "2026-01")["solar"]
store.archive_finished_days(now2)
store.archive_finished_days(now2)
mo_after = store.monthly_overview(now=now2)
jan_after = next(m for m in mo_after["months"] if m["month"] == "2026-01")["solar"]
assert abs(jan_before - jan_after) < 0.001, f"Mehrfachaufruf hat die Monatssumme veraendert: {jan_before} -> {jan_after}"
print("IDEMPOTENT OK")

print("ALL ARCHIVE TESTS OK", root.split("/")[-1])

# ---- Betriebsbericht (report.py) darf durch die Archivierung nicht falsch "0" zeigen
import report
rep = report.build(days=3, ctrl={}, now=now2)
msgdaten = next(c for c in rep["checks"] if c["title"] == "Messdaten gestern")
assert msgdaten["status"] == "ok" and int(msgdaten["detail"].split("/")[0]) >= 90, msgdaten
verlauf = next(c for c in rep["checks"] if c["title"] == "Verlauf vorhanden")
assert "2026-01-01" in verlauf["detail"], verlauf
row_d5 = next(r for r in rep["days"] if r["date"] == "2026-01-05")
assert row_d5["charged_kwh"] is not None  # nur pruefen, dass es nicht crasht / vorhanden ist
# der archivierte Vortag (2026-01-04) muss eine Geladen-Menge > 0 zeigen, nicht faelschlich 0.0,
# da unsere synthetische Ladung (g_batt) auf 0 steht - stattdessen pruefen wir hier den
# Nicht-Verlust der Tagesdaten generell:
day04 = store._day_buckets("2026-01-04")
assert len(day04) == 96, "Vortag muesste vollstaendig im Archiv liegen"
print("REPORT NO-FALSE-ALARM OK", root.split("/")[-1])
