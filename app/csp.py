"""Content-Security-Policy im MELDEMODUS: Der Browser blockiert nichts, er meldet nur, was eine Schutzregel blockiert HAETTE.
Zwei Regeln laufen parallel:
  a = "Schutz": so, wie sie spaeter erzwungen werden koennte (Skripte/Verbindungen/Bilder nur von dieser Seite und dem Diagramm-CDN, keine Fremd-Formulare,
      keine Plugins). Inline-Skripte sind hier noch erlaubt, damit die Seiten wie bisher laufen - die Regel begrenzt aber schon, wohin ein eingeschleustes
      Skript Daten schicken koennte.
  b = "Streng": nur Skripte aus Dateien. Zeigt, wie viel Inline-Code (<script>-Bloecke und onclick-Handler) noch umzubauen waere.
Die Meldungen kommen gesammelt (gezaehlt, ohne Adressen mit Parametern, ohne Besucher-Adresse) in csp_reports.json und sind fuer Administratoren
unter Einstellungen -> System einsehbar."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from urllib.parse import urlsplit

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csp_reports.json")
MAX_KEYS = 300                     # verschiedene Meldungen, die gemerkt werden (aelteste fallen heraus)
MAX_BODY = 16 * 1024               # groessere Meldungen werden ignoriert
FLUSH_S = 30                       # hoechstens alle 30 s auf die Platte schreiben
RATE_PER_MIN = 1500                # Meldungen pro Besucher-Adresse und Minute (darueber wird ignoriert; eine Seite mit vielen Klick-Handlern meldet sehr viele)

CDN = "https://cdnjs.cloudflare.com"                      # Chart.js fuer die Diagramme
POLICIES = {
    "a": ("Schutz", "default-src 'self'; script-src 'self' 'unsafe-inline' %s 'report-sample'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                    "font-src 'self' data:; connect-src 'self'; media-src 'self' blob:; worker-src 'self' blob:; manifest-src 'self'; object-src 'none'; "
                    "base-uri 'self'; form-action 'self'" % CDN),
    "b": ("Streng", "script-src 'self' %s 'report-sample'" % CDN),
}

_lock = threading.Lock()
_data: dict | None = None
_last_flush = 0.0
_dirty = False
_rate: dict = {}


def header_values() -> list:
    """Werte fuer die Kopfzeile Content-Security-Policy-Report-Only (je Regel eine Zeile)."""
    return ["%s; report-uri /api/csp-report?p=%s" % (v, k) for k, (_, v) in POLICIES.items()]


def _load_locked() -> dict:
    global _data
    if _data is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                d = json.load(f)
            _data = d if isinstance(d, dict) and isinstance(d.get("entries"), dict) else {"entries": {}, "since": time.time()}
        except (OSError, ValueError):
            _data = {"entries": {}, "since": time.time()}
    return _data


def _flush_locked(force: bool = False) -> None:
    global _last_flush, _dirty
    if not _dirty or (not force and time.time() - _last_flush < FLUSH_S):
        return
    try:
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_data, f, ensure_ascii=False)
        os.replace(tmp, PATH)
        _dirty = False
    except OSError:
        pass
    _last_flush = time.time()


def _short(u, keep_host: bool = True) -> str:
    """Adresse ohne Parameter und Anker (dort koennten Schluessel stehen); Schluesselwoerter wie 'inline' bleiben."""
    u = str(u or "")[:300]
    if "://" not in u:
        return u[:60]
    p = urlsplit(u)
    return ((p.scheme + "://" + p.netloc if keep_host else "") + p.path)[:160]


def rate_limited(ip: str) -> bool:
    now = time.time()
    with _lock:
        tries = [t for t in _rate.get(ip, []) if now - t < 60]
        tries.append(now)
        _rate[ip] = tries
        if len(_rate) > 500:
            for k in [k for k, v in _rate.items() if not v or now - v[-1] > 60]:
                _rate.pop(k, None)
        return len(tries) > RATE_PER_MIN


def record(policy: str, rep) -> bool:
    """Eine Meldung des Browsers zaehlen. False, wenn sie nicht brauchbar war."""
    global _dirty
    if policy not in POLICIES or not isinstance(rep, dict):
        return False
    eff = str(rep.get("effective-directive") or rep.get("violated-directive") or "?").split(" ")[0][:40]
    blocked = _short(rep.get("blocked-uri") or rep.get("blockedURL"))
    page = urlsplit(str(rep.get("document-uri") or "")[:400]).path[:80] or "?"
    src = _short(rep.get("source-file"), keep_host=False)
    try:
        line = int(rep.get("line-number") or 0)
    except (TypeError, ValueError):
        line = 0
    raw = " ".join(str(rep.get("script-sample") or rep.get("sample") or "").split())
    m = re.match(r"([\w$.]+)", raw)                          # nur der Name (z. B. "showTab"), nie die Parameter: dort koennen Kennwoerter oder Schluessel stehen
    sample = (m.group(1)[:40] + ("(…)" if len(raw) > len(m.group(1)) else "")) if m else ("…" if raw else "")
    key = "|".join((policy, eff, blocked, page, src, str(line)))
    now = time.time()
    with _lock:
        d = _load_locked()
        ent = d["entries"].get(key)
        if ent:
            ent["n"] += 1
            ent["last"] = now
            if sample and not ent.get("sample"):
                ent["sample"] = sample
        else:
            if len(d["entries"]) >= MAX_KEYS:
                for k in sorted(d["entries"], key=lambda k: d["entries"][k]["last"])[: len(d["entries"]) - MAX_KEYS + 1]:
                    d["entries"].pop(k, None)
            d["entries"][key] = {"p": policy, "rule": eff, "blocked": blocked, "page": page, "src": src, "line": line, "sample": sample, "n": 1, "first": now, "last": now}
        _dirty = True
        _flush_locked()
    return True


def summary(limit: int = 150) -> dict:
    """Fuer die Anzeige: Zaehlung je Regel und die haeufigsten Meldungen."""
    with _lock:
        d = _load_locked()
        _flush_locked(force=True)
        ents = list(d["entries"].values())
        since = d.get("since")
    per = {}
    for k, (label, _) in POLICIES.items():
        mine = [e for e in ents if e["p"] == k]
        kinds = {}
        for e in mine:
            kinds[e["rule"]] = kinds.get(e["rule"], 0) + e["n"]
        per[k] = {"label": label, "reports": sum(e["n"] for e in mine), "places": len(mine), "by_rule": kinds}
    ents.sort(key=lambda e: (-e["n"], e["last"]))
    return {"since": since, "policies": per, "entries": ents[:limit]}


def clear() -> None:
    global _data, _dirty
    with _lock:
        _data = {"entries": {}, "since": time.time()}
        _dirty = True
        _flush_locked(force=True)
