"""
Geschwindigkeits-Messung (Fehlersuche "warum ist die App traege?"): nur im Speicher, kostet praktisch nichts.

* Seitenabrufe: je Endpunkt Anzahl, Durchschnitt, Maximum; dazu die letzten langsamen Abrufe (ab SLOW_REQ_MS).
* Gegenstellen: jeder ausgehende HTTP-Aufruf der App (Geraete, CCU, Cloud, andere BlueNexus-Anlagen ...) wird nach Adresse (Host) gezaehlt:
  Anzahl, Durchschnitt, Maximum, Fehler/Zeitueberschreitungen. Die Anzeige steht unter Smart Home -> Sonstiges (nur Administratoren).
Ein Zaehler wird beim Neustart der App leer.
"""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import urlparse

log = logging.getLogger("perf")

SLOW_REQ_MS = 1000.0
SLOW_OUT_MS = 1500.0
KEEP_SLOW = 80

_lock = threading.Lock()
_since = time.time()
_eps: dict = {}                 # Endpunkt -> [Anzahl, Summe_ms, Max_ms, Anzahl_langsam]
_out: dict = {}                 # Host -> [Anzahl, Summe_ms, Max_ms, Fehler, Anzahl_langsam]
_slow: list = []                # [{ts, kind, what, ms, ok}] neueste zuletzt


def _note_slow(kind: str, what: str, ms: float, ok: bool = True) -> None:
    _slow.append({"ts": time.time(), "kind": kind, "what": what, "ms": round(ms), "ok": ok})
    del _slow[:-KEEP_SLOW]


def note_request(endpoint: str, path: str, ms: float) -> None:
    with _lock:
        e = _eps.setdefault(endpoint or path, [0, 0.0, 0.0, 0])
        e[0] += 1
        e[1] += ms
        e[2] = max(e[2], ms)
        if ms >= SLOW_REQ_MS:
            e[3] += 1
            _note_slow("Seite", path, ms)
    if ms >= SLOW_REQ_MS * 3:
        log.warning("Langsamer Seitenabruf: %s dauerte %.1f s", path, ms / 1000)


def note_outbound(host: str, ms: float, ok: bool) -> None:
    with _lock:
        o = _out.setdefault(host or "?", [0, 0.0, 0.0, 0, 0])
        o[0] += 1
        o[1] += ms
        o[2] = max(o[2], ms)
        if not ok:
            o[3] += 1
        if ms >= SLOW_OUT_MS or not ok and ms >= 1000:
            o[4] += 1
            _note_slow("Gegenstelle", host, ms, ok)


def snapshot() -> dict:
    with _lock:
        eps = sorted(({"name": k, "count": v[0], "avg_ms": round(v[1] / v[0]) if v[0] else 0, "max_ms": round(v[2]), "slow": v[3]} for k, v in _eps.items()),
                     key=lambda x: (-x["slow"], -x["avg_ms"]))[:25]
        outs = sorted(({"host": k, "count": v[0], "avg_ms": round(v[1] / v[0]) if v[0] else 0, "max_ms": round(v[2]), "errors": v[3], "slow": v[4]} for k, v in _out.items()),
                      key=lambda x: (-x["avg_ms"], -x["errors"]))[:25]
        return {"since": _since, "endpoints": eps, "outbound": outs, "slow": list(reversed(_slow))[:40]}


def reset() -> None:
    global _since
    with _lock:
        _eps.clear()
        _out.clear()
        _slow.clear()
        _since = time.time()


def install() -> None:
    """Misst alle ausgehenden HTTP-Aufrufe (requests): Dauer je Host, Fehler und Zeitueberschreitungen."""
    import requests
    orig = requests.sessions.Session.request
    if getattr(orig, "_perf", False):
        return

    def timed(self, method, url, *a, **k):
        if "/getUpdates" in str(url):                       # Telegram-Long-Poll wartet planmaessig bis 20 s auf Nachrichten: keine Stoerung
            return orig(self, method, url, *a, **k)
        t0 = time.perf_counter()
        ok = True
        try:
            return orig(self, method, url, *a, **k)
        except Exception:                                   # noqa: BLE001
            ok = False
            raise
        finally:
            try:
                note_outbound(urlparse(str(url)).netloc, (time.perf_counter() - t0) * 1000, ok)
            except Exception:                               # noqa: BLE001
                pass
    timed._perf = True
    requests.sessions.Session.request = timed
