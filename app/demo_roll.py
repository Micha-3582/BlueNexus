"""Demo-Modus: laesst die Historie mitrutschen, damit sie nie veraltet.

Beim Start der Demo (BLUENEXUS_DEMO=1) wird geprueft, wie viele volle Wochen der letzte "echte" Datentag hinter gestern liegt.
Ist das mindestens eine, werden alle Datumsangaben der Historie um dieses Vielfache von 7 Tagen nach vorn geschoben
(Wochentage bleiben erhalten). Der Stand steht in demo_roll.json ({"anchor": "YYYY-MM-DD"}).
Betroffen: history.json, history_archive/, price_history.json, solar_log.json, savings_days.json, verlauf.db.
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
    _shift_db(app_dir, n)
    _dump({"anchor": (anchor + timedelta(days=n)).isoformat(), "rolled": datetime.now().isoformat(timespec="seconds")}, marker)
    return n
