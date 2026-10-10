"""Demo-Modus (Umgebungsvariable BLUENEXUS_DEMO=1): erfundene, aber plausible Werte statt echter Geraete und Dienste.

Gedacht fuer oeffentliche Demo-Instanzen (zusammen mit BLUENEXUS_SANDBOX=1). Ersetzt:
  - den Cerbo GX (Live-Werte, Akku, ESS-Mode) durch eine Tagesverlauf-Simulation,
  - die Tibber-Preise durch eine Viertelstunden-Preiskurve mit Morgen- und Abendspitze,
  - die Victron-VRM-PV-Prognose durch eine Prognosekurve.
Alles ist deterministisch aus Datum und Uhrzeit berechnet, es wird nichts gespeichert und nichts geschaltet.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timedelta

ACTIVE = os.environ.get("BLUENEXUS_DEMO") == "1"

PV_KWP_W = 7500.0            # simulierte Spitzenleistung der Anlage
BATT_KWH = 22.8
MIN_SOC, MAX_SOC = 15.0, 95.0
CHARGE_W = 3500.0
_DAY_FACTORS = [0.30, 0.55, 0.80, 1.00, 0.65, 0.45, 0.90]   # "Wetter" je Tag (reihum)


def _day_factor(d) -> float:
    return _DAY_FACTORS[d.toordinal() % len(_DAY_FACTORS)]


def _season(d) -> float:
    """0.3 (Winter) ... 1.0 (Sommer) aus dem Tag im Jahr."""
    doy = d.timetuple().tm_yday
    return 0.3 + 0.7 * (0.5 + 0.5 * math.cos(2 * math.pi * (doy - 172) / 365.0))


def _solar_w(dt: datetime) -> float:
    h = dt.hour + dt.minute / 60.0
    s = _season(dt.date())
    length = 7.5 + 9.0 * s                                         # Tageslaenge in Stunden (Herbst ~10 h, Sommer ~16 h)
    rise = 13.0 - length / 2.0
    if h <= rise or h >= rise + length:
        return 0.0
    x = (h - rise) / length
    wobble = 1.0 + 0.10 * math.sin(h * 3.1 + dt.toordinal())      # leichte Wolken
    return max(0.0, PV_KWP_W * s * _day_factor(dt.date()) * math.sin(math.pi * x) ** 1.6 * wobble)


def _load_w(dt: datetime) -> float:
    h = dt.hour + dt.minute / 60.0
    w = 320.0
    w += 650.0 * math.exp(-((h - 7.5) ** 2) / 1.2)                  # Morgen
    w += 350.0 * math.exp(-((h - 12.5) ** 2) / 1.5)                 # Mittag
    w += 1250.0 * math.exp(-((h - 19.0) ** 2) / 2.2)                # Abend
    w += 120.0 * math.sin(h * 5.3 + dt.toordinal())                 # Rauschen
    return max(150.0, w)


def _grid_charge_window(dt: datetime) -> bool:
    return 2 <= dt.hour < 5


def _simulate(now: datetime):
    """Integriert den Tag in 5-Minuten-Schritten ab 00:00 und liefert den Zustand fuer 'jetzt'."""
    soc = 24.0 + 6.0 * _day_factor((now - timedelta(days=1)).date())
    t = now.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=5)
    state = (soc, 0.0, 0.0, 0.0)
    while True:
        pv, load = _solar_w(t), _load_w(t)
        batt = pv - load                                              # + = laden
        if _grid_charge_window(t) and soc < 60.0:
            batt = CHARGE_W
        batt = max(-3500.0, min(batt, CHARGE_W if _grid_charge_window(t) else 5000.0))
        if soc >= MAX_SOC and batt > 0:
            batt = 0.0
        if soc <= MIN_SOC and batt < 0:
            batt = 0.0
        state = (soc, pv, load, batt)
        nxt = t + step
        if nxt > now:
            return state
        soc = min(MAX_SOC, max(MIN_SOC, soc + batt * (5 / 60) / (BATT_KWH * 1000) * 100))
        t = nxt


class _Mode:
    value = 10


def _make_cerbo():
    from victron import Cerbo as _Real

    class DemoCerbo(_Real):
        def read_soc(self):
            return round(_simulate(datetime.now())[0], 1)

        def read_system(self, has_pv_inverter=True, has_mppt=True):
            now = datetime.now()
            soc, pv, load, batt = _simulate(now)
            pv_ac = pv * 0.8 if has_pv_inverter else 0.0
            pv_dc = pv * 0.2 if has_mppt else (0.0 if has_pv_inverter else pv)
            if not has_pv_inverter and not has_mppt:
                pv_ac = pv_dc = 0.0
            pv_tot = pv_ac + pv_dc
            batt_eff = batt if (has_pv_inverter or has_mppt or batt <= 0) else 0.0
            grid = load - pv_tot + batt_eff
            sp = lambda x: [int(round(x / 3.0))] * 3
            g, ld, pa = sp(grid), sp(load), sp(pv_ac)
            days = now.toordinal() - 739800
            frac = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
            volt = 50.0 + soc * 0.045
            return {
                "grid": {"l1": g[0], "l2": g[1], "l3": g[2], "total": sum(g)},
                "loads": {"l1": ld[0], "l2": ld[1], "l3": ld[2], "total": sum(ld)},
                "pv_inverter": {"l1": pa[0], "l2": pa[1], "l3": pa[2], "total": sum(pa)},
                "pv_charger": int(round(pv_dc)),
                "pv_charger_current": round(pv_dc / volt, 1),
                "solar_total": sum(pa) + int(round(pv_dc)),
                "grid_energy_total": {"import": round(4200 + (days + frac) * 9.0, 2),
                                      "export": round(5100 + (days + frac) * 11.0, 2)},
                "battery": {"voltage": round(volt, 1), "current": round(batt / volt, 1), "power": int(round(batt)),
                            "soc": int(round(soc)), "state": 1 if batt > 20 else (2 if batt < -20 else 0)},
            }

        def read_pvinverter_power(self, unit):
            return int(round(_solar_w(datetime.now()) * 0.8))

        def read_ess_mode(self):
            return _Mode.value

        def read_soh(self):
            return 97.0

        def read_alarms(self):
            from victron import ALARM_REGS
            return {"values": {k: 0 for k in ALARM_REGS}, "errors": {}}

        def read_min_soc(self):
            return MIN_SOC

        def write_min_soc(self, pct, dry_run=True):
            return False

        def read_grid_setpoint(self):
            return 0

        def write_grid_setpoint(self, watt, dry_run=True):
            return False

        def write_ess_mode(self, mode, dry_run=True):
            if dry_run:
                return False
            _Mode.value = int(mode)
            return True

    return DemoCerbo


def _price_ct(dt: datetime) -> float:
    h = dt.hour + dt.minute / 60.0
    f = _day_factor(dt.date())
    p = 26.0
    p += 9.0 * math.exp(-((h - 8.0) ** 2) / 1.6)                    # Morgenspitze
    p += 14.0 * math.exp(-((h - 19.0) ** 2) / 2.4)                  # Abendspitze
    p -= (5.0 + 9.0 * f) * math.exp(-((h - 13.0) ** 2) / 6.0)       # Mittagssenke (viel Sonne = billiger)
    p -= 7.0 * math.exp(-((h - 3.5) ** 2) / 3.0)                    # Nacht
    p += 2.0 * math.sin(h * 2.3 + dt.toordinal())
    return max(4.0, p)


def demo_prices():
    """Gleiches Format wie datasources.fetch_tibber_prices: [{'startsAt','total'(EUR/kWh),'level'}], heute + morgen."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for i in range(96 * 2):
        ts = start + timedelta(minutes=15 * i)
        rows.append((ts, _price_ct(ts)))
    out = []
    for day in (start.date(), (start + timedelta(days=1)).date()):
        day_rows = [p for ts, p in rows if ts.date() == day]
        avg = sum(day_rows) / len(day_rows)
        for ts, p in rows:
            if ts.date() != day:
                continue
            r = p / avg
            level = ("VERY_CHEAP" if r < 0.70 else "CHEAP" if r < 0.90 else "NORMAL" if r < 1.15
                     else "EXPENSIVE" if r < 1.40 else "VERY_EXPENSIVE")
            out.append({"startsAt": ts.isoformat(), "total": round(p / 100.0, 4), "level": level})
    return out


def vrm_forecast():
    """Gleiches Format wie vrm.forecast(): stuendliche PV-Prognose heute und morgen."""
    import vrm
    now = datetime.now()
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pv_rows, cons_rows = [], []
    for i in range(48):
        t = day0 + timedelta(hours=i, minutes=30)
        # Prognose liegt wie beim VRM leicht ueber dem Ergebnis (unabhaengig vom Wolken-Rauschen)
        pv = _solar_w(t) * 1.08
        pv_rows.append({"ts": int(t.replace(minute=0).timestamp()), "wh": round(pv, 1)})
        cons_rows.append({"ts": int(t.replace(minute=0).timestamp()), "wh": round(_load_w(t), 1)})
    data = vrm._summarize(pv_rows, now)
    data.update(configured=True, error=None, updated=now.isoformat(timespec="seconds"))
    cons = vrm._summarize(cons_rows, now)
    if cons["hours"]:
        data["cons"] = cons
    return data


def view_perms(perms: dict) -> dict:
    """Demo-Konto ohne Schreibrecht: Teilen und Benutzerverwaltung sind lesbar (sonst gaebe es dort in der Demo nichts zu sehen).
    Gilt nur im Demo-Modus; Schreiben bleibt gesperrt (Server und Browser)."""
    if not ACTIVE or any(v == "write" for v in (perms or {}).values()):
        return perms
    out = dict(perms)
    for area in ("smarthome_teilen", "user_management"):
        if out.get(area, "none") == "none":
            out[area] = "read"
    return out
