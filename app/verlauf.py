"""
Verlaufsgraphen: ausgewaehlte Messwerte (Energie: Netz/Verbrauch/Solar/Akku, Leistung und Zustand von Geraeten, Sensoren) fein aufzeichnen
und als Diagramme anzeigen - Ersatz fuer InfluxDB + Grafik-Adapter.

- Speicher: SQLite (`verlauf.db`, Standardbibliothek, keine Zusatzpakete). Rohwerte (`samples`) werden RAW_DAYS Tage behalten,
  dazu laeuft laufend eine Minuten-Zusammenfassung (`rollup`: Mittel/Min/Max) fuer ROLLUP_DAYS Tage - so bleiben Spitzen auch in langen Ansichten sichtbar.
- Aufgezeichnet wird nur, was der Administrator ausgewaehlt hat (`verlauf_series.json`). Die Reihen-ID ist die Quelle selbst
  (z. B. "energy:grid_w", "device_power:<id>", "sensor:<id>"): wird eine Reihe entfernt und spaeter neu angelegt, schliesst sie an die alten Daten an.
- Gelesen wird sparsam: Energiewerte aus dem Messwert des Energie-Samplers, Sensoren ueber den normalen Lese-Zwischenspeicher
  (Homematic mit Push: kein Funk), Geraete in einem Durchgang.
- Diagramme (Titel + Reihen) liegen in `verlauf_charts.json`.
"""
from __future__ import annotations

import logging
import math
import os
import re
import sqlite3
import threading
import time

log = logging.getLogger("verlauf")

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, "verlauf.db")
SERIES_PATH = os.path.join(_DIR, "verlauf_series.json")
CHARTS_PATH = os.path.join(_DIR, "verlauf_charts.json")

RAW_DAYS = 7
PRICE_BACKFILL_DAYS = 14                      # beim Anlegen der Preis-Reihe die schon bekannten Tibber-Preise der letzten Tage nachtragen
ROLLUP_DAYS = 400
INTERVALS = (5, 10, 30, 60, 300)             # erlaubte Abtastzeiten in Sekunden
DEFAULT_INTERVAL = {"energy": 10, "device_power": 10, "device_state": 30, "sensor": 60}
MAX_CHARTS, MAX_SERIES_PER_CHART, MAX_SERIES = 40, 12, 80
CHART_KINDS = ("line", "area", "bar", "step", "points", "stackarea", "stackbar")      # Darstellung: Linie, Flaeche, Balken, Stufen, Punkte, gestapelte Flaeche, gestapelte Balken

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


class VerlaufError(ValueError):
    pass


# ---------------------------------------------------------------- Datenbank
def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.execute("CREATE TABLE IF NOT EXISTS samples (series TEXT NOT NULL, ts INTEGER NOT NULL, v REAL NOT NULL, PRIMARY KEY (series, ts)) WITHOUT ROWID")
        c.execute("CREATE TABLE IF NOT EXISTS rollup (series TEXT NOT NULL, ts INTEGER NOT NULL, vsum REAL NOT NULL, n INTEGER NOT NULL, "
                  "vmin REAL NOT NULL, vmax REAL NOT NULL, PRIMARY KEY (series, ts)) WITHOUT ROWID")
        c.commit()
        _conn = c
    return _conn


def close():
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def add_samples(rows: list[tuple]) -> int:
    """rows = [(series, ts_sekunden, wert)]. Schreibt Rohwert und aktualisiert die Minuten-Zusammenfassung."""
    rows = [(s, int(t), float(v)) for s, t, v in rows if v is not None and math.isfinite(float(v))]
    if not rows:
        return 0
    with _lock:
        c = _db()
        c.executemany("INSERT OR REPLACE INTO samples (series, ts, v) VALUES (?, ?, ?)", rows)
        c.executemany("INSERT INTO rollup (series, ts, vsum, n, vmin, vmax) VALUES (?, ?, ?, 1, ?, ?) "
                      "ON CONFLICT(series, ts) DO UPDATE SET vsum = vsum + excluded.vsum, n = n + 1, vmin = MIN(vmin, excluded.vmin), vmax = MAX(vmax, excluded.vmax)",
                      [(s, t // 60 * 60, v, v, v) for s, t, v in rows])
        c.commit()
    return len(rows)


def prune(now: float | None = None) -> tuple[int, int]:
    """Alte Rohwerte und Zusammenfassungen loeschen. Rueckgabe: (Rohwerte, Zusammenfassungen)."""
    now = now or time.time()
    with _lock:
        c = _db()
        a = c.execute("DELETE FROM samples WHERE ts < ?", (int(now - RAW_DAYS * 86400),)).rowcount
        b = c.execute("DELETE FROM rollup WHERE ts < ?", (int(now - ROLLUP_DAYS * 86400),)).rowcount
        c.commit()
    return a, b


def stats() -> dict:
    with _lock:
        c = _db()
        n_raw = c.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        n_roll = c.execute("SELECT COUNT(*) FROM rollup").fetchone()[0]
        first = c.execute("SELECT MIN(ts) FROM rollup").fetchone()[0]
    size = 0
    for suffix in ("", "-wal"):                         # Hauptdatei + Schreibprotokoll (WAL)
        try:
            size += os.path.getsize(DB_PATH + suffix)
        except OSError:
            pass
    return {"raw": n_raw, "rollup": n_roll, "since": first, "bytes": size, "raw_days": RAW_DAYS, "rollup_days": ROLLUP_DAYS}


def delete_data(series_id: str) -> int:
    """Alle gespeicherten Werte einer Reihe loeschen (nur auf ausdruecklichen Wunsch)."""
    with _lock:
        c = _db()
        a = c.execute("DELETE FROM samples WHERE series = ?", (series_id,)).rowcount
        c.execute("DELETE FROM rollup WHERE series = ?", (series_id,))
        c.commit()
    return a


def query(series: dict, t0: float, t1: float, max_points: int = 1500) -> dict:
    """series = {id: {"label", "unit", "interval_s"}}; t0/t1 in Sekunden. Rueckgabe je Reihe Punkte [ms, Mittel, Min, Max] (None = Luecke)
    und die Bucket-Groesse. Kurze Zeitraeume kommen aus den Rohwerten, lange aus der Minuten-Zusammenfassung."""
    t0, t1 = int(t0), int(max(t1, t0 + 1))
    span = t1 - t0
    max_points = max(100, min(int(max_points), 5000))
    use_raw = t0 >= time.time() - RAW_DAYS * 86400 + 3600
    out = {}
    with _lock:
        c = _db()
        for sid, meta in series.items():
            base = max(1, int(meta.get("interval_s") or 10)) if use_raw else 60
            bucket = max(base, math.ceil(span / max_points))
            if not use_raw:
                bucket = max(60, bucket // 60 * 60)
            if use_raw:
                cur = c.execute("SELECT (ts / ?) * ?, AVG(v), MIN(v), MAX(v) FROM samples WHERE series = ? AND ts BETWEEN ? AND ? GROUP BY 1 ORDER BY 1",
                                (bucket, bucket, sid, t0, t1))
            else:
                cur = c.execute("SELECT (ts / ?) * ?, SUM(vsum) / SUM(n), MIN(vmin), MAX(vmax) FROM rollup WHERE series = ? AND ts BETWEEN ? AND ? GROUP BY 1 ORDER BY 1",
                                (bucket, bucket, sid, t0 - bucket, t1))
            gap = max(bucket * 3, int(meta.get("interval_s") or 10) * 3, 180)
            pts, prev = [], None
            for b, avg, mn, mx in cur.fetchall():
                if prev is not None and b - prev > gap:
                    pts.append([(prev + bucket) * 1000, None, None, None])            # Luecke: Linie unterbrechen
                pts.append([b * 1000, round(avg, 2), round(mn, 2), round(mx, 2)])
                prev = b
            out[sid] = {"label": meta.get("label", sid), "unit": meta.get("unit", ""), "points": pts, "bucket_s": bucket,
                        "interval_s": int(meta.get("interval_s") or 10), "source": "raw" if use_raw else "rollup"}
    return out


# ---------------------------------------------------------------- Register: Reihen und Diagramme
def _store():
    import store
    return store


def load_series() -> list[dict]:
    d = _store()._load_json_recovering(SERIES_PATH, lambda: [])
    return [x for x in d if isinstance(x, dict) and x.get("id") and x.get("source")] if isinstance(d, list) else []


def _save_series(items: list[dict]):
    _store()._dump_json(SERIES_PATH, items, indent=2)


def load_charts() -> list[dict]:
    d = _store()._load_json_recovering(CHARTS_PATH, lambda: [])
    return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []


def save_charts(items) -> list[dict]:
    """Diagramme pruefen und speichern: [{id, title, series: [ids]}]."""
    if not isinstance(items, list) or len(items) > MAX_CHARTS:
        raise VerlaufError(f"Höchstens {MAX_CHARTS} Diagramme")
    known = {s["id"] for s in load_series()}
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            raise VerlaufError("Diagramm ungültig")
        cid = str(it.get("id") or "").strip()[:40] or f"c{int(time.time() * 1000)}{len(out)}"
        if cid in seen:
            continue
        seen.add(cid)
        title = str(it.get("title") or "").strip()[:60] or "Diagramm"
        ids = [str(i) for i in (it.get("series") or []) if str(i) in known][:MAX_SERIES_PER_CHART]
        raw = it.get("colors") if isinstance(it.get("colors"), dict) else {}
        colors = {k: str(v).lower() for k, v in raw.items() if k in ids and re.fullmatch(r"#[0-9a-fA-F]{6}", str(v))}      # frei gewaehlte Farben je Reihe (#rrggbb)
        out.append({"id": cid, "title": title, "series": ids, "colors": colors, "dashboard": bool(it.get("dashboard")),
                    "kind": it.get("kind") if it.get("kind") in CHART_KINDS else "line"})
    _store()._dump_json(CHARTS_PATH, out, indent=2)
    return out


def add_series(source: str, interval_s=None, label: str = "") -> dict:
    cat = {c["id"]: c for c in catalog()}
    if source not in cat:
        raise VerlaufError("Quelle nicht verfügbar (Gerät/Sensor entfernt oder Modul aus?)")
    items = load_series()
    if any(x["id"] == source for x in items):
        raise VerlaufError("Diese Reihe wird schon aufgezeichnet")
    if len(items) >= MAX_SERIES:
        raise VerlaufError(f"Höchstens {MAX_SERIES} Reihen")
    c = cat[source]
    iv = check_interval(interval_s, c.get("interval") or DEFAULT_INTERVAL.get(c["type"], 60))
    item = {"id": source, "source": source, "label": (str(label).strip()[:60] or c["label"]), "unit": c["unit"], "interval_s": iv, "binary": bool(c.get("binary")),
            "step": bool(c.get("step"))}
    items.append(item)
    _save_series(items)
    if source == "energy:price_ct":
        try:
            backfill_prices()
        except Exception as e:                           # noqa: BLE001 - Nachtragen ist nur ein Bonus
            log.warning("Verlauf: Preise nachtragen fehlgeschlagen: %s", e)
    return item


def backfill_prices(days: int = PRICE_BACKFILL_DAYS) -> int:
    """Bekannte Tibber-Viertelstundenpreise der letzten Tage in die Preis-Reihe nachtragen (nur wo noch nichts steht). Rueckgabe: Anzahl Werte."""
    from datetime import datetime, timedelta
    st = _store()
    if st.load_config().get("tariff_mode") == "fixed":
        return 0
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    with _lock:
        have = {r[0] for r in _db().execute("SELECT ts FROM samples WHERE series = 'energy:price_ct'")}
    for back in range(days, -1, -1):
        day = today - timedelta(days=back)
        slots = st.price_slots(day.date().isoformat())
        for i, p in enumerate(slots or []):
            ts = int((day + timedelta(minutes=15 * i)).timestamp())
            if p is not None and ts <= time.time() and ts not in have:
                rows.append(("energy:price_ct", ts, float(p)))
    return add_samples(rows)


def check_interval(v, default: int) -> int:
    if v in (None, ""):
        return default
    try:
        iv = int(v)
    except (TypeError, ValueError):
        raise VerlaufError("Abtastzeit ungültig")
    if iv not in INTERVALS:
        raise VerlaufError("Abtastzeit: " + ", ".join(f"{i} s" for i in INTERVALS))
    return iv


def update_series(sid: str, label=None, interval_s=None) -> bool:
    items = load_series()
    for x in items:
        if x["id"] == sid:
            if label is not None and str(label).strip():
                x["label"] = str(label).strip()[:60]
            if interval_s not in (None, ""):
                x["interval_s"] = check_interval(interval_s, x.get("interval_s", 60))
            _save_series(items)
            return True
    return False


def remove_series(sid: str) -> bool:
    """Reihe aus der Aufzeichnung nehmen (die gespeicherten Werte bleiben bis zum Ablauf der Aufbewahrung) und aus den Diagrammen streichen."""
    items = load_series()
    keep = [x for x in items if x["id"] != sid]
    if len(keep) == len(items):
        return False
    _save_series(keep)
    charts = load_charts()
    if any(sid in c.get("series", []) for c in charts):
        for c in charts:
            c["series"] = [i for i in c.get("series", []) if i != sid]
        _store()._dump_json(CHARTS_PATH, charts, indent=2)
    return True


# ---------------------------------------------------------------- Quellen
ENERGY_KEYS = {
    "grid_w": ("Netz (Bezug +, Einspeisung −)", "W", lambda s: s["grid"]["total"]),
    "load_w": ("Verbrauch Haus", "W", lambda s: s["loads"]["total"]),
    "solar_w": ("Solar gesamt", "W", lambda s: s["solar_total"]),
    "batt_w": ("Batterie (Laden +, Entladen −)", "W", lambda s: s["battery"]["power"]),
    "soc": ("Akkustand", "%", lambda s: s["battery"]["soc"]),
    "cost_ct_h": ("Kosten Netzbezug", "ct/h", None),                 # Netzbezug (W) x Strompreis: was der Bezug gerade pro Stunde kostet (Einspeisung zaehlt 0)
    "price_ct": ("Strompreis (Bezug)", "ct/kWh", None),             # kommt nicht vom Cerbo, sondern aus dem Tarif (Tibber-Viertelstundenpreis bzw. Festpreis)
}


def catalog() -> list[dict]:
    """Alle aktuell aufzeichenbaren Quellen: {id, type, label, unit, group, binary}."""
    st = _store()
    cfg = st.load_config()
    out = []
    if st.module_on("energy", cfg):
        for k, (label, unit, _fn) in ENERGY_KEYS.items():
            item = {"id": f"energy:{k}", "type": "energy", "label": label, "unit": unit, "group": "Energie (Cerbo)"}
            if k in ("price_ct", "cost_ct_h"):
                item.update(group="Energie (Tarif)", **({"step": True, "interval": 60} if k == "price_ct" else {}))         # Preis: Stufenlinie, 1 Minute reicht (wechselt alle 15 Minuten)
            out.append(item)
    if st.module_on("smarthome", cfg):
        import homematic
        import shelly
        for d in shelly.load_devices():
            name = d.get("name") or d["id"]
            if d.get("kind", "shelly") in ("shelly", "tasmota") or (d.get("kind") == "homematic" and d.get("power_addr")):
                out.append({"id": f"device_power:{d['id']}", "type": "device_power", "label": f"{name} – Leistung", "unit": "W", "group": "Geräte"})
            out.append({"id": f"device_state:{d['id']}", "type": "device_state", "label": f"{name} – an/aus", "unit": "", "group": "Geräte", "binary": True})
            if d.get("kind") == "midea":                 # Klimaanlage: Innen-, Aussen- und Solltemperatur
                for k, lab in (("indoor", "Innentemperatur"), ("outdoor", "Außentemperatur"), ("target", "Solltemperatur")):
                    out.append({"id": f"device_{k}:{d['id']}", "type": "device_temp", "label": f"{name} – {lab}", "unit": "°C", "group": "Geräte", "interval": 60})
        for s in homematic.load_sensors():
            out.append({"id": f"sensor:{s['id']}", "type": "sensor", "label": s.get("name") or s["id"], "unit": s.get("unit") or "", "group": "Sensoren", "binary": bool(s.get("binary"))})
    return out


def read_sources(ids: list[str], system: dict | None, extras: dict | None = None) -> dict:
    """{reihen-id: Wert|None} fuer die genannten Reihen. Mehrere Geraete/Sensoren werden jeweils in einem Durchgang gelesen."""
    out: dict = {}
    dev_ids, sen_ids = set(), set()
    for sid in ids:
        kind, _, ref = sid.partition(":")
        if kind == "energy" and ref == "price_ct":
            v = (extras or {}).get("price_ct")
            out[sid] = None if v is None else float(v)
        elif kind == "energy" and ref == "cost_ct_h":
            try:
                price = (extras or {}).get("price_ct")
                out[sid] = None if price is None or not system else round(max(float(system["grid"]["total"]), 0.0) / 1000.0 * float(price), 3)
            except (KeyError, TypeError, ValueError):
                out[sid] = None
        elif kind == "energy":
            try:
                out[sid] = float(ENERGY_KEYS[ref][2](system)) if system else None
            except (KeyError, TypeError, ValueError):
                out[sid] = None
        elif kind in ("device_power", "device_state", "device_indoor", "device_outdoor", "device_target"):
            dev_ids.add(ref)
        elif kind == "sensor":
            sen_ids.add(ref)
    if dev_ids:
        import shelly
        try:
            live = {d["id"]: d for d in shelly.list_with_status(ids=dev_ids)}
        except Exception as e:                           # noqa: BLE001
            log.warning("Verlauf: Geräte nicht lesbar: %s", e)
            live = {}
        for sid in ids:
            kind, _, ref = sid.partition(":")
            d = live.get(ref)
            if kind == "device_power":
                out[sid] = None if not d or not d.get("online") or d.get("power") is None else float(d["power"])
            elif kind == "device_state":
                out[sid] = None if not d or not d.get("online") or d.get("on") is None else (1.0 if d["on"] else 0.0)
            elif kind in ("device_indoor", "device_outdoor", "device_target"):
                v = d.get({"device_indoor": "indoor_c", "device_outdoor": "outdoor_c", "device_target": "target_c"}[kind]) if d and d.get("online") else None
                out[sid] = None if v is None else float(v)
    if sen_ids:
        import homematic
        try:
            vals = homematic.read_values([s for s in homematic.load_sensors() if s["id"] in sen_ids])
        except Exception as e:                           # noqa: BLE001
            log.warning("Verlauf: Sensoren nicht lesbar: %s", e)
            vals = {}
        for ref in sen_ids:
            v = vals.get(ref)
            out[f"sensor:{ref}"] = None if v is None else (1.0 if v is True else 0.0 if v is False else float(v))
    return out


# ---------------------------------------------------------------- Aufzeichnung
class Sampler:
    """Liest alle faelligen Reihen und schreibt sie in die Datenbank (jede Reihe in ihrer eigenen Abtastzeit)."""

    def __init__(self, get_system=lambda: None, get_extra=lambda: {}):
        self.get_system = get_system
        self.get_extra = get_extra                  # weitere Messwerte ausserhalb des Cerbo, z. B. {"price_ct": ...}
        self._last: dict[str, float] = {}
        self._pruned = 0.0
        self._stop = threading.Event()
        self.errors = 0

    def tick(self, now: float | None = None) -> int:
        now = now or time.time()
        st = _store()
        cfg = st.load_config()
        if not st.module_on("verlauf", cfg):
            return 0                                           # Modul Verlaeufe aus: nichts aufzeichnen (Daten bleiben erhalten)
        due = []
        for s in load_series():
            kind = s["source"].partition(":")[0]
            if kind == "energy" and not st.module_on("energy", cfg):
                continue
            if kind != "energy" and not st.module_on("smarthome", cfg):
                continue
            if now - self._last.get(s["id"], 0) >= int(s.get("interval_s") or 60) - 0.5:
                due.append(s["id"])
        n = 0
        if due:
            extras = {}
            if "energy:price_ct" in due or "energy:cost_ct_h" in due:
                try:
                    extras = self.get_extra() or {}
                except Exception as e:                   # noqa: BLE001
                    log.warning("Verlauf: Zusatzwerte nicht lesbar: %s", e)
            vals = read_sources(due, self.get_system(), extras)
            for sid in due:
                self._last[sid] = now
            n = add_samples([(sid, now, v) for sid, v in vals.items() if v is not None])
        if now - self._pruned > 3600:
            self._pruned = now
            try:
                prune(now)
            except sqlite3.Error as e:
                log.warning("Verlauf: Aufräumen fehlgeschlagen: %s", e)
        return n

    def run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:                       # noqa: BLE001
                self.errors += 1
                log.warning("Verlauf-Aufzeichnung: %s", e)
            self._stop.wait(2.0)

    def stop(self):
        self._stop.set()
