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
INTERVALS = (5, 10, 30, 60, 300, 600, 900, 1800, 3600)             # erlaubte Abtastzeiten in Sekunden
CHANGE_HEARTBEAT_S = 3600                    # Reihen "bei Aenderung": ohne Aenderung mindestens einmal pro Stunde den aktuellen Wert nachtragen (Linie reisst nicht ab, Ausfall bleibt sichtbar)
CHANGE_POLL_S = 10                           # so oft wird eine Reihe "bei Aenderung" hoechstens gelesen (Mindestabstand, schont Geraete und Datenbank)
POWER_UNITS = {"W", "kW", "A", "mA", "VA", "kVA", "var", "Wh", "kWh"}      # Strom-/Leistungswerte schwanken staendig: dort gibt es kein "bei Aenderung"
CHANGE_BAND = {"°C": 0.1, "%": 0.5, "hPa": 0.5}                             # Schwelle je Einheit; sonst 1 % des letzten Werts
EVENT_GAP_S = 7200                           # Reihen "bei jeder Meldung" (Funkthermometer): laenger als 2 Stunden ohne Wert = Luecke im Diagramm
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


def is_event_source(source: str) -> bool:
    """Reihen, die nicht abgefragt, sondern bei jeder Meldung des Geraets aufgezeichnet werden koennen (Funkthermometer)."""
    return str(source).startswith("sensor:thermo-")


def change_ok(source: str, unit: str = "", binary: bool = False) -> bool:
    """Darf diese Quelle "bei Aenderung" aufgezeichnet werden? Nicht: Energie (Cerbo/Tarif), Geraete-Leistung und alles in W/kW/A/kWh (zu viele Aenderungen)."""
    kind = str(source).partition(":")[0]
    if kind in ("energy", "device_power") or is_event_source(source):
        return False
    return str(unit or "") not in POWER_UNITS


def changed_enough(last, new, unit: str = "", binary: bool = False) -> bool:
    if last is None:
        return True
    if binary:
        return (last > 0.5) != (new > 0.5)
    band = CHANGE_BAND.get(unit)
    if band is None:
        band = max(0.01, abs(last) * 0.01)
    return abs(new - last) >= band - 1e-9


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
            iv0 = int(meta.get("interval_s") or 0)
            ev = iv0 <= 0                                                    # 0 = bei jeder Meldung, -1 = bei Aenderung
            ivq = iv0 if iv0 > 0 else 10
            base = max(1, ivq) if use_raw else 60
            bucket = max(base, math.ceil(span / max_points))
            if not use_raw:
                bucket = max(60, bucket // 60 * 60)
            if use_raw:
                cur = c.execute("SELECT (ts / ?) * ?, AVG(v), MIN(v), MAX(v) FROM samples WHERE series = ? AND ts BETWEEN ? AND ? GROUP BY 1 ORDER BY 1",
                                (bucket, bucket, sid, t0, t1))
            else:
                cur = c.execute("SELECT (ts / ?) * ?, SUM(vsum) / SUM(n), MIN(vmin), MAX(vmax) FROM rollup WHERE series = ? AND ts BETWEEN ? AND ? GROUP BY 1 ORDER BY 1",
                                (bucket, bucket, sid, t0 - bucket, t1))
            gap = max(bucket * 3, EVENT_GAP_S if ev else ivq * 3, 180)
            pts, prev = [], None
            for b, avg, mn, mx in cur.fetchall():
                if prev is not None and b - prev > gap:
                    pts.append([(prev + bucket) * 1000, None, None, None])            # Luecke: Linie unterbrechen
                pts.append([b * 1000, round(avg, 2), round(mn, 2), round(mx, 2)])
                prev = b
            out[sid] = {"label": meta.get("label", sid), "unit": meta.get("unit", ""), "points": pts, "bucket_s": bucket,
                        "interval_s": ivq, "source": "raw" if use_raw else "rollup"}
    return out


# ---------------------------------------------------------------- Register: Reihen und Diagramme
def _store():
    import store
    return store


def load_series() -> list[dict]:
    d = _store()._load_json_recovering(SERIES_PATH, lambda: [])
    items = [x for x in d if isinstance(x, dict) and x.get("id") and x.get("source")] if isinstance(d, list) else []
    for x in items:
        x["change"] = change_ok(x["source"], x.get("unit"), bool(x.get("binary")))             # darf "bei Aenderung" gewaehlt werden
    return items


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
        out.append({"id": cid, "title": title, "series": ids, "colors": colors, "dashboard": bool(it.get("dashboard")), "stats": bool(it.get("stats")),
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
    iv = check_interval(interval_s, c["interval"] if "interval" in c else DEFAULT_INTERVAL.get(c["type"], 60), event_ok=is_event_source(source), change_ok_=change_ok(source, c["unit"], bool(c.get("binary"))))
    item = {"id": source, "source": source, "label": (str(label).strip()[:60] or c["label"]), "unit": c["unit"], "interval_s": iv, "binary": bool(c.get("binary")),
            "step": bool(c.get("step")), "event": is_event_source(source)}
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


def check_interval(v, default: int, event_ok: bool = False, change_ok_: bool = False) -> int:
    if v in (None, ""):
        return default
    try:
        iv = int(v)
    except (TypeError, ValueError):
        raise VerlaufError("Abtastzeit ungültig")
    if iv == 0 and event_ok:
        return 0                                                  # bei jeder Meldung des Geraets (nur Funkthermometer)
    if iv == -1 and change_ok_:
        return -1                                                 # nur bei Aenderung (nicht bei Strom-/Leistungswerten)
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
                x["interval_s"] = check_interval(interval_s, x.get("interval_s", 60), event_ok=is_event_source(x["source"]), change_ok_=change_ok(x["source"], x.get("unit"), bool(x.get("binary"))))
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
            out.append({"id": f"sensor:{s['id']}", "type": "sensor", "label": s.get("name") or s["id"], "unit": s.get("unit") or "", "group": "Sensoren", "binary": bool(s.get("binary")),
                        **({"interval": 0, "event": True} if s.get("source") == "thermo" else {})})                  # Funkthermometer: Standard = bei jeder Meldung (kein Abfragen)
    for c in out:
        c["change"] = change_ok(c["id"], c.get("unit"), bool(c.get("binary")))
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


def record_event(sensor_ids: list, ts: float | None = None) -> int:
    """Funkthermometer hat gemeldet: die Werte der Reihen "bei jeder Meldung" (interval_s == 0) genau jetzt aufzeichnen - der echte Wert, kein Abtasten."""
    import homematic
    st = _store()
    cfg = st.load_config()
    if not st.module_on("verlauf", cfg) or not st.module_on("smarthome", cfg):
        return 0
    want = {f"sensor:{i}" for i in sensor_ids}
    mine = [x["id"] for x in load_series() if x["id"] in want and x.get("interval_s") == 0]
    if not mine:
        return 0
    vals = read_sources(mine, None)
    t = ts or time.time()
    return add_samples([(sid, t, v) for sid, v in vals.items() if v is not None])


def migrate_event_series() -> int:
    """Bestehende Thermometer-Reihen (bisher abgefragt, dadurch alte Werte mehrfach) einmalig auf "bei jeder Meldung" umstellen."""
    items = load_series(); n = 0
    for x in items:
        if is_event_source(x["source"]) and not x.get("event"):
            x["event"] = True
            x["interval_s"] = 0; n += 1
    if n:
        _save_series(items)
    return n


# ---------------------------------------------------------------- Aufzeichnung
class Sampler:
    """Liest alle faelligen Reihen und schreibt sie in die Datenbank (jede Reihe in ihrer eigenen Abtastzeit)."""

    def __init__(self, get_system=lambda: None, get_extra=lambda: {}):
        self.get_system = get_system
        self.get_extra = get_extra                  # weitere Messwerte ausserhalb des Cerbo, z. B. {"price_ct": ...}
        self._last: dict[str, float] = {}
        self._lastv: dict[str, tuple] = {}                   # "bei Aenderung": id -> (zuletzt gespeicherter Wert, Zeit)
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
            if s.get("interval_s") == 0:
                continue                                       # "bei jeder Meldung": wird von record_event() beim Eintreffen der Meldung geschrieben
            iv = s.get("interval_s")
            poll = CHANGE_POLL_S if iv == -1 else int(iv or 60)
            if now - self._last.get(s["id"], 0) >= poll - 0.5:
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
            meta = {x["id"]: x for x in load_series()}
            rows = []
            for sid, v in vals.items():
                if v is None:
                    continue
                m = meta.get(sid) or {}
                if m.get("interval_s") == -1:                 # nur bei Aenderung (oder stuendlicher Nachtrag)
                    lv = self._lastv.get(sid)
                    if lv is not None and not changed_enough(lv[0], v, m.get("unit") or "", bool(m.get("binary"))) and now - lv[1] < CHANGE_HEARTBEAT_S:
                        continue
                    self._lastv[sid] = (v, now)
                rows.append((sid, now, v))
            n = add_samples(rows)
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
