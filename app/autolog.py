"""
Logbuch der Automatik: Ueberschuss-Automatik ("surplus") und Regeln ("rules") schreiben in je eine EIGENE Datei.

Jede Zeile: {"ts": ISO-Zeit, "dev": Geraetename, "action": "on"|"off"|"fail", "text": Klartext, "dry": Trockenlauf?, "rule": Regel-ID|None}
Die Dateien werden bei ca. MAX_BYTES gekuerzt (aelteste 40 % fallen weg), damit sie nie unbegrenzt wachsen.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
MODULES = ("surplus", "rules")
PATHS = {m: os.path.join(_DIR, f"{m}_log.jsonl") for m in MODULES}
READ_PATH = os.path.join(_DIR, "automation_log_read.json")      # {"surplus": ISO-Zeit, "rules": ISO-Zeit} - bis wann das Logbuch gelesen wurde
MAX_BYTES = 1_500_000
_lock = threading.Lock()


def log(module: str, text: str, dev: str = "", action: str = "", dry: bool = False, rule: str | None = None, now: datetime | None = None):
    if module not in PATHS:
        raise ValueError(module)
    row = {"ts": (now or datetime.now()).isoformat(timespec="milliseconds"), "dev": dev, "action": action, "text": text, "dry": bool(dry), "rule": rule}
    if module == "rules":                                   # Regeln haben kein eigenes Logbuch mehr: ihre Ereignisse stehen im allgemeinen Geraete-Logbuch (Kategorie "Regeln")
        try:
            import devicelog
            devicelog.log("regel", "rule:" + str(rule or ""), dev or "Regel", text, action != "fail", by="Regel (Trockenlauf)" if dry else "Regel")
        except Exception:                                  # noqa: BLE001 - das Logbuch darf die Steuerung nie stoeren
            pass
    with _lock:
        path = PATHS[module]
        try:
            if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                with open(path, "w", encoding="utf-8") as f:
                    f.writelines(lines[int(len(lines) * 0.4):])
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass                                   # das Logbuch darf die Steuerung nie stoeren


def recent(module: str, limit: int = 200, days: int | None = None, now: datetime | None = None) -> list[dict]:
    """Neueste zuerst. days: nur die letzten N Tage (None = alles)."""
    path = PATHS[module]
    if not os.path.exists(path):
        return []
    since = ((now or datetime.now()) - timedelta(days=days)).isoformat(timespec="seconds") if days else None
    out = []
    with _lock:
        try:
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
    for line in reversed(lines):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if since and e.get("ts", "") < since:
            continue                                    # nicht abbrechen: nach einem Uhrensprung (z. B. Neustart ohne Uhr) sind die Zeilen nicht der Zeit nach geordnet
        out.append(e)
        if len(out) >= limit:
            break
    return out


def counts(module: str, days: int = 7, now: datetime | None = None) -> dict:
    """Kurzstatistik fuer den Betriebsbericht: Aktionen gesamt und davon echt (nicht Trockenlauf)."""
    rows = recent(module, 5000, days, now)
    return {"total": len(rows), "real": sum(1 for r in rows if not r.get("dry")), "failed": sum(1 for r in rows if r.get("action") == "fail")}


def clear(module: str) -> int:
    """Logbuch leeren. Rueckgabe: Anzahl geloeschter Eintraege. Kann die Datei nicht beschrieben werden (Rechte, Datentraeger voll), kommt OSError."""
    if module not in PATHS:
        raise ValueError(module)
    with _lock:
        path = PATHS[module]
        n = 0
        try:
            if os.path.exists(path):
                with open(path, encoding="utf-8") as f:
                    n = sum(1 for line in f if line.strip())
                open(path, "w", encoding="utf-8").close()
        finally:
            _unread_cache.pop(module, None)
    return n


def _read_marks() -> dict:
    try:
        with open(READ_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_read(module: str, now: datetime | None = None) -> bool:
    """Logbuch gilt als gelesen (alles bis jetzt). False, wenn die Lesemarke nicht gespeichert werden konnte (dann bleibt der Zaehler stehen)."""
    if module not in PATHS:
        raise ValueError(module)
    with _lock:
        d = _read_marks()
        d[module] = (now or datetime.now()).isoformat(timespec="milliseconds")
        try:
            with open(READ_PATH, "w", encoding="utf-8") as f:
                json.dump(d, f)
        except OSError:
            return False
    _unread_cache.pop(module, None)
    return True


_unread_cache: dict = {}


def unread(module: str, now: datetime | None = None) -> int:
    """Anzahl Eintraege, die neuer sind als die letzte Lesemarke (ohne Marke: alle). Wird nur neu gezaehlt, wenn sich Datei oder Marke geaendert haben."""
    since = _read_marks().get(module, "")
    try:
        st = os.stat(PATHS[module])
        key = (st.st_mtime_ns, st.st_size, since)
    except OSError:
        return 0
    hit = _unread_cache.get(module)
    if hit and hit[0] == key:
        return hit[1]
    n = sum(1 for e in recent(module, 1000, None, now) if e.get("ts", "") > since)         # alle zaehlen (kein Abbruch: nach einem Uhrensprung sind die Zeilen nicht der Zeit nach geordnet)
    _unread_cache[module] = (key, n)
    return n
