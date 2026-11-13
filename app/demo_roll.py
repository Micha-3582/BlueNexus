"""Demo-Modus: laesst die Historie mitrutschen, damit sie nie veraltet.

Beim Start der Demo (BLUENEXUS_DEMO=1) wird geprueft, wie viele volle Wochen der letzte "echte" Datentag hinter gestern liegt.
Ist das mindestens eine, werden alle Datumsangaben der Historie um dieses Vielfache von 7 Tagen nach vorn geschoben
(Wochentage bleiben erhalten). Der Stand steht in demo_roll.json ({"anchor": "YYYY-MM-DD"}).
Betroffen: history.json, history_archive/, price_history.json, solar_log.json, savings_days.json, forecast_hours.json, verlauf.db.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
from datetime import date, datetime, timedelta

log = logging.getLogger("demo_roll")

DEFAULT_ANCHOR = "2026-10-08"      # letzter Tag der uebernommenen Daten (Auslieferstand der Demo)


def _sd(s: str, n: int) -> str:
    """Datum am Anfang einer Zeichenkette ('YYYY-MM-DD...') um n Tage verschieben."""
    return (date.fromisoformat(s[:10]) + timedelta(days=n)).isoformat() + s[10:]


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(obj, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def _shift_days_file(path: str, n: int, extra_keys=()) -> None:
    if not os.path.exists(path):
        return
    d = _load(path)
    d["days"] = {_sd(k, n): v for k, v in (d.get("days") or {}).items()}
    for k in extra_keys:
        if isinstance(d.get(k), str) and len(d[k]) >= 10:
            d[k] = _sd(d[k], n)
    _dump(d, path)


def _shift_history(app_dir: str, n: int) -> None:
    hot = os.path.join(app_dir, "history.json")
    if os.path.exists(hot):
        h = _load(hot)
        h["hours"] = {_sd(k, n): v for k, v in (h.get("hours") or {}).items()}
        last = h.get("last")
        if isinstance(last, dict) and isinstance(last.get("ts"), str):
            last["ts"] = _sd(last["ts"], n)
        _dump(h, hot)
    arc = os.path.join(app_dir, "history_archive")
    if not os.path.isdir(arc):
        return
    months: dict = {}
    for fn in sorted(os.listdir(arc)):
        if not fn.endswith(".json"):
            continue
        for day, slots in (_load(os.path.join(arc, fn)).get("days") or {}).items():
            nd = _sd(day, n)
            months.setdefault(nd[:7], {})[nd] = {_sd(k, n): v for k, v in slots.items()}
    new = arc + ".new"
    shutil.rmtree(new, ignore_errors=True)
    os.makedirs(new)
    for m, days in months.items():
        _dump({"days": days}, os.path.join(new, m + ".json"))
    shutil.rmtree(arc)
    os.replace(new, arc)


def _shift_db(app_dir: str, n: int) -> None:
    path = os.path.join(app_dir, "verlauf.db")
    if not os.path.exists(path):
        return
    secs = n * 86400
    con = sqlite3.connect(path)
    try:
        con.execute("BEGIN")
        con.execute("CREATE TABLE samples_new (series TEXT NOT NULL, ts INTEGER NOT NULL, v REAL NOT NULL, PRIMARY KEY (series, ts)) WITHOUT ROWID")
        con.execute("INSERT INTO samples_new SELECT series, ts + ?, v FROM samples", (secs,))
        con.execute("DROP TABLE samples")
        con.execute("ALTER TABLE samples_new RENAME TO samples")
        con.execute("CREATE TABLE rollup_new (series TEXT NOT NULL, ts INTEGER NOT NULL, vsum REAL NOT NULL, n INTEGER NOT NULL, "
                    "vmin REAL NOT NULL, vmax REAL NOT NULL, PRIMARY KEY (series, ts)) WITHOUT ROWID")
        con.execute("INSERT INTO rollup_new SELECT series, ts + ?, vsum, n, vmin, vmax FROM rollup", (secs,))
        con.execute("DROP TABLE rollup")
        con.execute("ALTER TABLE rollup_new RENAME TO rollup")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


ENERGY_SERIES = {"energy:load_w": "load", "energy:solar_w": "pv", "energy:grid_w": "grid", "energy:soc": "soc"}


def _slot(vals, price_ct: float) -> dict:
    """Ein 15-Minuten-Eintrag der Energie-Historie aus Minutenwerten (je Minute dict aus demo.snapshot)."""
    n = len(vals)
    k = 1.0 / 60.0 / 1000.0                                  # Watt-Minute -> kWh
    out = {"verbrauch": 0.0, "solar": 0.0, "s_load": 0.0, "s_batt": 0.0, "s_grid": 0.0, "b_load": 0.0, "b_grid": 0.0, "g_load": 0.0, "g_batt": 0.0}
    for v in vals:
        pv, load, batt = float(v["pv"]), float(v["load"]), float(v["batt"])
        s_load = min(pv, load)
        pv_rest, load_rest = pv - s_load, load - s_load
        s_batt = min(pv_rest, max(batt, 0.0))
        b_load = min(load_rest, max(-batt, 0.0))
        out["verbrauch"] += load * k
        out["solar"] += pv * k
        out["s_load"] += s_load * k
        out["s_batt"] += s_batt * k
        out["s_grid"] += (pv_rest - s_batt) * k
        out["b_load"] += b_load * k
        out["g_load"] += (load_rest - b_load) * k
        out["g_batt"] += (max(batt, 0.0) - s_batt) * k
    socs = [float(v["soc"]) for v in vals]
    out.update({"soc_min": min(socs), "soc_max": max(socs), "soc_sum": sum(socs), "soc_n": n,
                "grid_cost_ct": (out["g_load"] + out["g_batt"]) * price_ct})
    return out


def fill_today(app_dir: str, now: datetime | None = None) -> None:
    """Fuellt die Luecke von heute 00:00 bis zur ersten echten Aufzeichnung mit den Werten der Simulation (gleiche Rechnung wie die Live-Anzeige,
    damit Akku-Ladestand und Leistungen nahtlos in die laufende Aufzeichnung uebergehen). Andere Reihen (z.B. Sensoren) kommen von einem frueheren Tag.

    Ohne das waere "Heute" nach jedem Neustart der Demo leer (die Historie reicht nur bis gestern)."""
    import demo
    now = now or datetime.now()
    midnight = datetime(now.year, now.month, now.day)
    t0, t1 = int(midnight.timestamp()), int(now.timestamp())
    minutes = {}                                             # Minute (Unix) -> Momentaufnahme, nur bis jetzt
    m = t0
    while m + 60 <= t1:
        minutes[m] = demo.snapshot(datetime.fromtimestamp(m + 30))
        m += 60
    # Energie-Verlauf (history.json, 15-Minuten-Slots)
    try:
        hot_p = os.path.join(app_dir, "history.json")
        h = _load(hot_p) if os.path.exists(hot_p) else {"hours": {}}
        hours = h.setdefault("hours", {})
        for k in [k for k in hours if k.startswith(midnight.date().isoformat())]:      # heute komplett neu aus der Simulation (aeltere Staende der Auffuellung koennen abweichen)
            del hours[k]
        added = 1
        for q in range(96):
            st = midnight + timedelta(minutes=15 * q)
            key = st.strftime("%Y-%m-%dT%H:%M")
            if st + timedelta(minutes=15) > now:
                break
            if key in hours:                                 # schon aufgezeichnet (auch Luecken waehrend eines Neustarts werden gefuellt)
                continue
            vals = [minutes[x] for x in range(int(st.timestamp()), int(st.timestamp()) + 900, 60) if x in minutes]
            if vals:
                hours[key] = _slot(vals, demo._price_ct(st))
                added += 1
        if added:
            _dump(h, hot_p)
    except Exception:                                       # noqa: BLE001
        log.exception("Demo: heutige Energiewerte konnten nicht aufgefuellt werden")
    # Verlaeufe (verlauf.db)
    path = os.path.join(app_dir, "verlauf.db")
    if not os.path.exists(path):
        return
    con = sqlite3.connect(path)
    try:
        con.execute("BEGIN")
        for tab in ("samples", "rollup"):
            for ser in ENERGY_SERIES:
                con.execute(f"DELETE FROM {tab} WHERE series=? AND ts>=?", (ser, t0))
        for tab, cols in (("samples", "v"), ("rollup", "vsum, n, vmin, vmax")):
            for (series,) in con.execute(f"SELECT DISTINCT series FROM {tab}").fetchall():
                key = ENERGY_SERIES.get(series)
                first = con.execute(f"SELECT MIN(ts) FROM {tab} WHERE series=? AND ts>=?", (series, t0)).fetchone()[0]
                lim = first if first is not None else t1
                if lim <= t0 and not key:
                    continue
                if key:                                      # Energie-Reihen: direkt aus der Simulation, fehlende Minuten (eine Minute = ein Wert)
                    for ts, v in minutes.items():
                        if tab == "samples" and con.execute("SELECT 1 FROM samples WHERE series=? AND ts>=? AND ts<?", (series, ts, ts + 60)).fetchone():
                            continue
                        val = float(v[key])
                        con.execute("INSERT OR IGNORE INTO samples (series, ts, v) VALUES (?,?,?)" if tab == "samples" else
                                    "INSERT OR IGNORE INTO rollup (series, ts, vsum, n, vmin, vmax) VALUES (?,?,?,1,?,?)",
                                    (series, ts, val) if tab == "samples" else (series, ts, val, val, val))
                    continue
                for k in (7, 14, 21, 28, 1, 2, 3, 4, 5, 6):  # sonst: erst ganze Wochen zurueck, dann die letzten Tage (Rohwerte werden nur kurz gehalten)
                    s = k * 86400
                    cur = con.execute(f"INSERT OR IGNORE INTO {tab} (series, ts, {cols}) SELECT series, ts+?, {cols} FROM {tab} "
                                      f"WHERE series=? AND ts>=? AND ts<?", (s, series, t0 - s, lim - s))
                    if cur.rowcount > 0:
                        break
        con.commit()
    except Exception:                                       # noqa: BLE001
        con.rollback()
        log.exception("Demo: heutige Verlaufswerte konnten nicht aufgefuellt werden")
    finally:
        con.close()


def roll(app_dir: str | None = None, today: date | None = None) -> int:
    """Verschiebt die Historie, wenn sie mindestens eine volle Woche hinter gestern zurueckliegt. Rueckgabe: Verschiebung in Tagen (0 = nichts)."""
    app_dir = app_dir or os.path.dirname(os.path.abspath(__file__))
    marker = os.path.join(app_dir, "demo_roll.json")
    try:
        anchor = date.fromisoformat(_load(marker)["anchor"])
    except (OSError, ValueError, KeyError):
        anchor = date.fromisoformat(DEFAULT_ANCHOR)
    yesterday = (today or date.today()) - timedelta(days=1)
    n = ((yesterday - anchor).days // 7) * 7
    if n <= 0:
        return 0
    log.warning("Demo: Historie wird um %d Tage nach vorn verschoben (Anker %s -> %s)", n, anchor, anchor + timedelta(days=n))
    _shift_history(app_dir, n)
    _shift_days_file(os.path.join(app_dir, "price_history.json"), n)
    _shift_days_file(os.path.join(app_dir, "solar_log.json"), n, ("auto_pr_date", "auto_bucket_date"))
    _shift_days_file(os.path.join(app_dir, "savings_days.json"), n)
    _shift_days_file(os.path.join(app_dir, "forecast_hours.json"), n)          # gemerkte VRM-Stundenprognose je Tag
    _shift_db(app_dir, n)
    _dump({"anchor": (anchor + timedelta(days=n)).isoformat(), "rolled": datetime.now().isoformat(timespec="seconds")}, marker)
    return n
