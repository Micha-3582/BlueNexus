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


# Nur fuer Werbebilder: BLUENEXUS_DEMO_SNAPSHOT=1 zeigt einen festen, sonnigen Moment statt der Tageszeit (sonst viele Nullen am Abend).
# Wird auf der oeffentlichen Demo nicht gesetzt.
SNAPSHOT = os.environ.get("BLUENEXUS_DEMO_SNAPSHOT") == "1"


def _now() -> datetime:
    """Jetzt - im Snapshot-Modus (nur Werbebilder) immer 12:40 Uhr des heutigen Tages (sonnig, Akku mittel; ohne Nullen am Abend)."""
    n = datetime.now()
    return n.replace(hour=12, minute=40, second=n.second % 30, microsecond=0) if SNAPSHOT else n


def _h(n: int, seed: int) -> float:
    """Deterministische Zufallszahl in [0, 1) aus Ganzzahl und Seed (kein random: gleiche Zeit = gleicher Wert, auch fuer die Auffuellung der Historie)."""
    x = (n * 374761393 + seed * 668265263) & 0xFFFFFFFF
    x = ((x ^ (x >> 13)) * 1274126177) & 0xFFFFFFFF
    x ^= x >> 16
    return x / 4294967296.0


def _vn(t: float, period: float, seed: int) -> float:
    """Weiches Wertrauschen in [-1, 1] mit der Strukturlaenge 'period' Sekunden."""
    n = int(math.floor(t / period))
    f = t / period - n
    f = f * f * (3.0 - 2.0 * f)
    a, b = _h(n, seed), _h(n + 1, seed)
    return (a + (b - a) * f) * 2.0 - 1.0


def _events(t: float, cell: float, p: float, seed: int, dmin: float, dmax: float):
    """Zufaellige Ereignisse (Wolke, Geraet, Spitze): je Zelle mit Wahrscheinlichkeit p ein Ereignis. Liefert (Anteil 0..1 im Ereignis, Staerke 0..1) fuer alle gerade laufenden."""
    k = int(math.floor(t / cell))
    out = []
    for c in (k - 1, k):
        if _h(c, seed) < p:
            start = c * cell + _h(c, seed + 1) * cell
            dur = dmin + _h(c, seed + 2) * (dmax - dmin)
            if start <= t < start + dur:
                out.append(((t - start) / dur, _h(c, seed + 3), _h(c, seed + 4)))
    return out


def _live_pv(w: float, t: float) -> float:
    """PV mit Wolken: kurze, tiefe Einbrueche, dazu feines Flimmern und langsames Auf und Ab."""
    if w <= 0:
        return 0.0
    day = datetime.fromtimestamp(t).date()
    p = 0.18 + 0.45 * (1.0 - _day_factor(day))                       # schwacher Tag = mehr Wolken
    dip = 0.0
    for x, depth, _r in _events(t, 600.0, p, 11, 25.0, 330.0):
        dip = max(dip, (0.2 + 0.7 * depth) * math.sin(math.pi * x) ** 0.4)
    fine = 1.0 + 0.045 * _vn(t, 13, 3) + 0.02 * _vn(t, 4, 4) + 0.06 * _vn(t, 240, 5)
    return max(0.0, w * fine * (1.0 - dip))


def _live_load(w: float, t: float) -> float:
    """Verbrauch mit Stufen (Geraete schalten), seltenen Grosslasten (Wasserkocher, Herd) und feinem Rauschen."""
    v = w + 35.0 * _vn(t, 22, 8) + 14.0 * _vn(t, 5, 9) + 120.0 * _vn(t, 540, 10)
    for x, a, b in _events(t, 600.0, 0.10, 31, 120.0, 720.0):
        v += 500.0 + 1500.0 * a
    return max(110.0, v)


def _grid_noise(t: float) -> float:
    """Abweichung des Netzwerts von der Rechnung: die Regelung haelt ihn nahe null, mit kleinen Spitzen."""
    v = 11.0 * _vn(t, 9, 21) + 6.0 * _vn(t, 3, 22)
    for x, a, b in _events(t, 120.0, 0.08, 41, 12.0, 70.0):
        v += (140.0 + 800.0 * a) * (1.0 if b > 0.45 else -1.0) * (1.0 - x)
    return v


def _phase_w(t: float, base, seed: float):
    return [max(0.05, b + 0.06 * _vn(t, 90, int(seed * 10) + i)) for i, b in enumerate(base)]


def _split(x: float, weights):
    """Ganzzahlig auf drei Phasen aufteilen, die Summe ist genau round(x)."""
    total = int(round(x))
    sw = float(sum(weights))
    parts = [int(math.floor(total * w / sw)) for w in weights]
    rest = total - sum(parts)
    order = sorted(range(3), key=lambda i: -(total * weights[i] / sw - parts[i]))
    for i in range(abs(rest)):
        parts[order[i % 3]] += 1 if rest > 0 else -1
    return parts


def _states(day_start: datetime) -> list:
    """Zustand (soc, pv, load, batt) der Simulation fuer alle 288 Fuenf-Minuten-Schritte eines Tages (gleiche Rechnung wie _simulate)."""
    soc = 24.0 + 6.0 * _day_factor((day_start - timedelta(days=1)).date())
    t = day_start
    step = timedelta(minutes=5)
    out = []
    for _ in range(288):
        pv, load = _solar_w(t), _load_w(t)
        batt = pv - load
        if _grid_charge_window(t) and soc < 60.0:
            batt = CHARGE_W
        batt = max(-3500.0, min(batt, CHARGE_W if _grid_charge_window(t) else 5000.0))
        if soc >= MAX_SOC and batt > 0:
            batt = 0.0
        if soc <= MIN_SOC and batt < 0:
            batt = 0.0
        out.append((soc, pv, load, batt))
        soc = min(MAX_SOC, max(MIN_SOC, soc + batt * (5 / 60) / (BATT_KWH * 1000) * 100))
        t += step
    return out


def _snap(state, t: float, has_pv_inverter: bool = True, has_mppt: bool = True) -> dict:
    """Alle Werte der Live-Anzeige zu einer Zeit t (Unix) aus einem Zustand der Simulation: Summen, Phasen, Preis.
    Rechnerisch geschlossen: Netz = Verbrauch - Solar + Batterie (in Watt, auch je Phase). Die Batterie gleicht Wolken und Verbraucher aus,
    so haelt sich das Netz nahe der Rechnung (wie bei einer geregelten Anlage); der Ladestand folgt der glatten Simulation."""
    soc, pv, load, batt = state
    pv_ac0 = pv * 0.8 if has_pv_inverter else 0.0
    pv_dc0 = pv * 0.2 if has_mppt else (0.0 if has_pv_inverter else pv)
    if not has_pv_inverter and not has_mppt:
        pv_ac0 = pv_dc0 = 0.0
    batt_eff = batt if (has_pv_inverter or has_mppt or batt <= 0) else 0.0
    pv_ac, pv_dc = _live_pv(pv_ac0, t), _live_pv(pv_dc0, t + 5.0)
    load_j = _live_load(load, t)
    ld = _split(load_j, _phase_w(t, (0.30, 0.39, 0.31), 1.0))
    pa = _split(pv_ac, _phase_w(t, (0.31, 0.35, 0.34), 2.0)) if pv_ac > 0 else [0, 0, 0]
    dc = int(round(pv_dc))
    batt_j = batt_eff + (sum(pa) + dc - (pv_ac0 + pv_dc0)) - (sum(ld) - load) + _grid_noise(t)         # Batterie gleicht die Abweichungen aus
    bts = _split(int(round(batt_j)), (1, 1, 1))
    dcs = _split(dc, (1, 1, 1))
    g = [ld[i] - pa[i] - dcs[i] + bts[i] for i in range(3)]
    price = _price_ct(datetime.fromtimestamp(t))
    out = {"soc": soc, "pv": sum(pa) + dc, "load": sum(ld), "batt": sum(bts), "grid": sum(g), "price": price,
           "cost": max(0.0, sum(g)) * price / 1000.0, "ld": ld, "pa": pa, "dc": dc, "g": g, "pv_dc": pv_dc}
    for i in range(3):
        out["grid_l%d" % (i + 1)] = g[i]
        out["load_l%d" % (i + 1)] = ld[i]
    return out


def snapshot(now: datetime) -> dict:
    """Gleiche Werte wie die Live-Anzeige zu einem Zeitpunkt: soc, pv (Watt gesamt), load, grid (+ = Bezug), batt (+ = laden), je Phase, Preis."""
    return _snap(_simulate(now), now.timestamp())


def day_snapshots(day_start: datetime, until: float) -> dict:
    """Minute (Unix) -> snapshot fuer einen ganzen Tag (bis 'until'), ohne die Simulation je Minute neu zu rechnen."""
    states = _states(day_start)
    t0 = int(day_start.timestamp())
    out = {}
    m = t0
    while m + 60 <= until and m < t0 + 86400:
        out[m] = _snap(states[min(287, (m + 30 - t0) // 300)], m + 30)
        m += 60
    return out


class _Mode:
    value = 10


def _make_cerbo():
    from victron import Cerbo as _Real

    class DemoCerbo(_Real):
        def read_soc(self):
            return round(_simulate(_now())[0], 1)

        def read_system(self, has_pv_inverter=True, has_mppt=True):
            now = _now()
            state = _simulate(now)
            sn = _snap(state, now.timestamp(), has_pv_inverter, has_mppt)
            soc, ld, pa, dc, g, pv_dc, batt = state[0], sn["ld"], sn["pa"], sn["dc"], sn["g"], sn["pv_dc"], sn["batt"]
            days = now.toordinal() - 739800
            frac = (now.hour * 3600 + now.minute * 60 + now.second) / 86400.0
            volt = 50.0 + soc * 0.045
            return {
                "grid": {"l1": g[0], "l2": g[1], "l3": g[2], "total": sum(g)},
                "loads": {"l1": ld[0], "l2": ld[1], "l3": ld[2], "total": sum(ld)},
                "pv_inverter": {"l1": pa[0], "l2": pa[1], "l3": pa[2], "total": sum(pa)},
                "pv_charger": dc,
                "pv_charger_current": round(pv_dc / volt, 1),
                "solar_total": sum(pa) + dc,
                "grid_energy_total": {"import": round(4200 + (days + frac) * 9.0, 2),
                                      "export": round(5100 + (days + frac) * 11.0, 2)},
                "battery": {"voltage": round(volt, 1), "current": round(batt / volt, 1), "power": int(round(batt)),
                            "soc": int(round(soc)), "state": 1 if batt > 20 else (2 if batt < -20 else 0)},
            }

        def read_pvinverter_power(self, unit):
            n = _now()
            return int(round(_live_pv(_solar_w(n) * 0.8, n.timestamp())))

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
    for area in ("smarthome_teilen", "user_management", "smarthome_logbuch", "account"):
        if out.get(area, "none") == "none":
            out[area] = "read"
    return out
