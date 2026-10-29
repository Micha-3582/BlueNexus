"""Vertragskosten-Perioden: eine Aenderung an Grundgebuehr/Netznutzung/... wirkt sich nur ab dem
Gueltigkeitsdatum aus, nicht rueckwirkend auf die ganze Historie (Max, 28.09.2026)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])

cfg.update({"contract_fee_month_eur": 12.50, "grid_fee_day_eur": 0.08, "meter_fee_day_eur": 0.0,
            "section14a_credit_day_eur": 0.0, "vat_percent": 19})

# ---- Erste Speicherung ueberhaupt: legt rueckwirkend (ab 2000-01-01) die aktuellen Werte an,
# damit sich am bisherigen Verhalten (alte Monate rechnen mit den "aktuellen" Werten) nichts aendert,
# solange der Nutzer noch nie etwas geaendert hat.
changed1 = store.record_contract_period_if_changed(cfg, day="2027-01-10")
assert changed1 is False, "erste Speicherung soll KEINE neue Periode anlegen, nur die Basis-Periode"
p_jan = store.contract_period_for_day("2026-05-01")   # weit VOR der ersten Aenderung
assert p_jan["contract_fee_month_eur"] == 12.50
print("Basis-Periode (rueckwirkend) OK")

# ---- Unveraenderte erneute Speicherung -> keine neue Periode
assert store.record_contract_period_if_changed(cfg, day="2027-01-15") is False
print("Keine Aenderung -> keine neue Periode OK")

# ---- Anbieterwechsel am 01.03.2027: Grundgebuehr UND Netznutzung steigen
cfg2 = dict(cfg, contract_fee_month_eur=14.90, grid_fee_day_eur=0.09)
changed2 = store.record_contract_period_if_changed(cfg2, day="2027-03-01")
assert changed2 is True
print("Aenderung erkannt -> neue Periode angelegt OK")

# ---- Vergangene Tage (VOR dem Wechsel) rechnen weiterhin mit den ALTEN Werten
p_before = store.contract_period_for_day("2027-02-15")
assert p_before["contract_fee_month_eur"] == 12.50 and p_before["grid_fee_day_eur"] == 0.08, p_before
print("Tag vor dem Wechsel -> alte Werte OK")

# ---- Tage AB dem Wechsel rechnen mit den NEUEN Werten
p_after = store.contract_period_for_day("2027-03-01")
p_after2 = store.contract_period_for_day("2027-06-01")
assert p_after["contract_fee_month_eur"] == 14.90 and p_after2["contract_fee_month_eur"] == 14.90
print("Tag ab dem Wechsel -> neue Werte OK")

# ---- Zeitraum, der ueber den Wechsel hinweg geht (z.B. Februar/Maerz zusammen) - Fixkosten muessen
# sich GEMISCHT aus beiden Perioden ergeben, nicht komplett mit den neuen (oder alten) Werten
fee_feb_only = store.contract_fixed_cost_for_range("2027-02-01", "2027-02-28")
fee_mar_only = store.contract_fixed_cost_for_range("2027-03-01", "2027-03-31")
fee_straddle = store.contract_fixed_cost_for_range("2027-02-25", "2027-03-05")   # 4 Tage alt (25.-28.2) + 5 Tage neu (1.-5.3)
per_day_old = 12.50 / 30.44 + 0.08
per_day_new = 14.90 / 30.44 + 0.09
expected_straddle = 4 * per_day_old + 5 * per_day_new
assert abs(fee_straddle - expected_straddle) < 0.001, (fee_straddle, expected_straddle)
assert abs(fee_feb_only - per_day_old * 28) < 0.001
assert abs(fee_mar_only - per_day_new * 31) < 0.001
print("Zeitraum ueber den Wechsel hinweg -> korrekt gemischt OK")

# ---- cost_incl_fees_eur_for_range(): Februar (alte Periode) und Maerz (neue Periode) liefern unterschiedliche
# Gesamtkosten bei GLEICHEN Energiekosten - genau das war vorher der Bug (immer die aktuellen Werte ueberall)
incl_feb = store.cost_incl_fees_eur_for_range(100.0, "2027-02-01", "2027-02-28")
incl_mar = store.cost_incl_fees_eur_for_range(100.0, "2027-03-01", "2027-03-31")
assert incl_feb != incl_mar, "Januar und Maerz duerfen bei unterschiedlichen Vertragskosten nicht gleich sein"
expected_feb = round((100.0 + per_day_old * 28) * 1.19, 2)
expected_mar = round((100.0 + per_day_new * 31) * 1.19, 2)
assert incl_feb == expected_feb, (incl_feb, expected_feb)
assert incl_mar == expected_mar, (incl_mar, expected_mar)
print("cost_incl_fees_eur_for_range() unterscheidet Perioden korrekt OK")

# ---- Zweite Aenderung AM SELBEN TAG ueberschreibt die Periode statt sie zu duplizieren
cfg3 = dict(cfg2, vat_percent=7)
store.record_contract_period_if_changed(cfg3, day="2027-03-01")
periods = store._load_contract_periods()
assert len(periods) == 2, f"sollte weiterhin nur 2 Perioden geben (nicht dupliziert), hat aber {len(periods)}"
assert periods[-1]["vat_percent"] == 7
print("Zweite Aenderung am selben Tag -> ueberschreibt statt zu duplizieren OK")

# ---- Rueckwaertskompatibilitaet: OHNE je eine Periode gespeichert zu haben (frische Installation) faellt
# contract_period_for_day() sauber auf die aktuelle Config zurueck, kein Crash
os.remove(store.CONTRACT_PERIODS_PATH)
cfg.update(cfg3)     # store.load_config() (in ps_common gemockt) liest aus DIESEM dict - muss fuer den Fallback-Vergleich mitziehen
p_fresh = store.contract_period_for_day("2020-01-01")
assert p_fresh["contract_fee_month_eur"] == cfg["contract_fee_month_eur"], (p_fresh, cfg)
print("Rueckwaertskompatibilitaet ohne gespeicherte Periode OK")

print("CONTRACT PERIODS OK", sys.argv[1].split("/")[-1] if "/" in sys.argv[1] else sys.argv[1])
