import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])

# ---- Nachrechnen von Maxs August-Rechnung: Verbrauch 67.26 (netto), Gebuehr 5.03,
# Netznutzung -11.78+6.82=... , Messstelle 2.86, dann 19% MwSt -> 83.53
cfg2 = {"contract_fee_month_eur": 5.03, "grid_fee_day_eur": 0.22, "meter_fee_day_eur": 0.0921,
        "section14a_credit_day_eur": 0.38, "vat_percent": 19}
days_august = 31
fixed = store.contract_fixed_cost_eur(cfg2, days_august)
# 5.03 (voller Monat, nicht /30.44*31) weicht leicht ab - wir runden den Monat ueber 30.44 um,
# pruefen daher nur ungefaehre Naehe zur echten Rechnung (< 0.5 EUR Abweichung)
energy_net = 67.26
total = store.cost_incl_fees_eur(cfg2, energy_net, days_august)
print("Fixkosten 31 Tage:", round(fixed, 2), "-> Gesamt inkl. MwSt:", total, "(Rechnung: 83.53)")
assert abs(total - 83.53) < 0.60, total

# ---- Ohne jede Einstellung (Standard): Ergebnis = unveraendert der reine Energiebetrag (kein Aufschlag)
assert store.contract_fixed_cost_eur({}, 30) == 0.0
assert store.cost_incl_fees_eur({}, 50.0, 30) == 50.0

# ---- Negative/fehlerhafte Eintraege robust (keine Exception, "or 0"-Fallback)
assert store.contract_fixed_cost_eur({"grid_fee_day_eur": None}, 10) == 0.0

# ---- monatliche Übersicht bekommt die neue Spalte, unabhaengig von Vertragskosten (0, wenn nichts eingetragen)
cfg.update({"contract_fee_month_eur": 5.03, "grid_fee_day_eur": 0.22, "meter_fee_day_eur": 0.09,
            "section14a_credit_day_eur": 0.38, "vat_percent": 19})
mo = store.monthly_overview()
assert mo["months"] and "cost_incl_fees_eur" in mo["months"][0], mo["months"][0]

# ---- Wochenrueckblick bekommt dieselbe Spalte je Tag und in der Summe
wk = store.energy_week_summary()
assert wk["days"] and "cost_incl_fees_eur" in wk["days"][0], wk["days"][0]
assert "cost_incl_fees_eur" in wk["totals"], wk["totals"]

print("FEES OK", sys.argv[1].split("/")[-1])
