"""
Geraete-Logbuch: wer hat wann welches Smart-Home-Geraet bedient (Aktoren, Thermostate, Sicherheit) und was haben Sensoren gemeldet.

Eigene Datei `devicelog.jsonl` (eine JSON-Zeile je Ereignis, aelteste Zeilen werden bei ~2 MB verworfen) - getrennt vom Betriebsprotokoll (`opslog`),
in dem die Regeln ihr eigenes Logbuch haben. Nichts hier darf die Steuerung stoeren: alle Aufrufe fangen ihre Fehler selbst ab.

Wer es war ("by"): Ein Aufrufer setzt vorher `actor("Regel „X“")`; ohne Angabe gilt das angemeldete Konto (Browser-Anfrage) bzw. "System".
Erfasst wird an den Stellen, wo wirklich geschaltet wird (`install()` umhuellt die Funktionen), also egal ob von Hand, per Regel,
Ueberschuss-Automatik, Alexa, Telegram/NFC (laeuft ueber Regeln) oder Freigabe an eine andere Anlage. Trockenlauf-Schritte schalten nichts und stehen hier nicht.

Kategorien: aktor (Geraete, Schalter/Knoepfe, Rollladen, Soundmodule, Wake-on-LAN), thermostat, sicherheit (Tuerschloesser), sensor (Zustandswechsel).
"""
from __future__ import annotations

import functools
import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime

log_ = logging.getLogger("devicelog")

_DIR = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(_DIR, "devicelog.jsonl")
MAX_BYTES = 2_000_000
CATS = ("aktor", "sensor", "thermostat", "sicherheit", "regel")
CAT_LABEL = {"aktor": "Aktoren", "sensor": "Sensoren", "thermostat": "Thermostate", "sicherheit": "Sicherheit", "regel": "Regeln"}

_lock = threading.Lock()
_local = threading.local()


# ---------------------------------------------------------------- Wer?
@contextmanager
def actor(label: str):
    prev = getattr(_local, "who", None)
    _local.who = label
    try:
        yield
    finally:
        _local.who = prev


def as_actor(label_fn):
    """Decorator: die ganze Funktion laeuft "im Namen" von label_fn(*args, **kwargs) (z. B. Regel- oder Automatik-Schritte)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            try:
                label = label_fn(*a, **k)
            except Exception:                                              # noqa: BLE001
                label = "System"
            with actor(label):
                return fn(*a, **k)
        return wrapper
    return deco


def current_actor() -> str:
    who = getattr(_local, "who", None)
    if who:
        return who
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, "user", None):
            return f"Konto „{getattr(g, 'user_display', None) or g.user}“"
    except Exception:                                                       # noqa: BLE001
        pass
    return "System"


def current_user() -> str:
    """Anmeldename (klein geschrieben) des Kontos, das gerade per Browser bedient - sonst leer (Regel, Automatik, Alexa ...)."""
    if getattr(_local, "who", None):
        return ""
    try:
        from flask import g, has_request_context
        if has_request_context() and getattr(g, "user", None):
            return str(g.user).strip().lower()
    except Exception:                                                       # noqa: BLE001
        pass
    return ""


# ---------------------------------------------------------------- Schreiben / Lesen
def log(cat: str, ref: str, name: str, text: str, ok: bool = True, by: str | None = None) -> None:
    try:
        row = {"ts": datetime.now().isoformat(timespec="seconds"), "cat": cat, "ref": ref, "name": name, "text": text,
               "by": by or current_actor(), "ok": bool(ok)}
        usr = "" if by else current_user()
        if usr:
            row["user"] = usr                                               # Anmeldename: damit Regeln "bedient von Konto X" pruefen koennen
        line = json.dumps(row, ensure_ascii=False)
        with _lock:
            with open(PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            if os.path.getsize(PATH) > MAX_BYTES:
                _trim_locked()
    except Exception as e:                                                  # noqa: BLE001
        log_.warning("Geraete-Logbuch: %s", e)


def _trim_locked() -> None:
    with open(PATH, encoding="utf-8") as f:
        lines = f.readlines()
    keep = lines[int(len(lines) * 0.4):]
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, PATH)


_cache: dict = {"key": None, "rows": []}


def _rows() -> list[dict]:
    """Alle Eintraege (alt -> neu), nur neu eingelesen, wenn sich die Datei geaendert hat (Abfragen der Seite kosten sonst jedes Mal das ganze Parsen)."""
    try:
        st = os.stat(PATH)
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    with _lock:
        if _cache["key"] == key:
            return _cache["rows"]
        rows = []
        try:
            with open(PATH, encoding="utf-8") as f:
                for line in f:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        _cache["key"], _cache["rows"] = key, rows
        return rows


def recent(limit: int = 200, cat: str | None = None, q: str | None = None, allow=None) -> list[dict]:
    """Neueste zuerst. allow(ref) -> bool filtert nach Sichtbarkeit fuer das Konto; cat = Kategorie; q = Suchtext (Name, Text, wer)."""
    out: list[dict] = []
    q = (q or "").strip().lower()
    for e in reversed(_rows()):
        if cat and e.get("cat") != cat:
            continue
        if allow is not None and not allow(e.get("ref", "")):
            continue
        if q and q not in (str(e.get("name", "")) + " " + str(e.get("text", "")) + " " + str(e.get("by", ""))).lower():
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


_pre: dict = {}                        # Referenz -> (wer, Konto, Zeit): schon VOR dem Schaltbefehl gemerkt, damit eine Regel den Bediener auch dann kennt, wenn sie schneller ist als der Logbucheintrag
WHO_MAX_AGE_S = 120.0


def who_last(ref: str, max_age: float = WHO_MAX_AGE_S) -> dict | None:
    """Wer hat dieses Ding zuletzt bedient (innerhalb von max_age Sekunden)? -> {"by": Text, "user": Anmeldename oder "", "age": Sekunden} oder None."""
    now = time.time()
    best = None
    p = _pre.get(ref)
    if p and now - p[2] <= max_age:
        best = {"by": p[0], "user": p[1], "age": now - p[2]}
    try:
        for e in reversed(_rows()[-3000:]):
            if e.get("ref") != ref:
                continue
            try:
                age = now - datetime.fromisoformat(e.get("ts", "")).timestamp()
            except ValueError:
                break
            if age <= max_age and (best is None or age < best["age"]):
                best = {"by": e.get("by") or "", "user": e.get("user") or "", "age": age}
            break
    except Exception:                                                       # noqa: BLE001
        pass
    return best


def who_name(w: dict | None) -> str:
    """Kurzer Name fuer Texte: bei einem Konto der Kontoname, sonst die Quelle (Regel, Alexa, System ...)."""
    if not w:
        return "unbekannt"
    by = str(w.get("by") or "").strip()
    if by.startswith("Konto „") and by.endswith("“"):
        return by[len("Konto „"):-1]
    return by or "unbekannt"


_last_cache: dict = {"key": None, "map": {}}


def last_map(allow=None) -> dict:
    """{ref: letztes Ereignis} - fuer den Hinweis "zuletzt ..." in den Listen (je Dateistand nur einmal berechnet)."""
    rows = _rows()
    key = (id(rows), len(rows))
    if _last_cache["key"] != key:
        full: dict = {}
        for e in reversed(rows):
            r = e.get("ref", "")
            if not r or r in full or e.get("cat") == "sensor":
                continue
            full[r] = {"ts": e.get("ts"), "text": e.get("text"), "by": e.get("by"), "ok": e.get("ok", True)}
        _last_cache["key"], _last_cache["map"] = key, full
    full = _last_cache["map"]
    return {r: v for r, v in full.items() if allow is None or allow(r)}


# ---------------------------------------------------------------- Einhaengen in die Schalt-Funktionen
def _wrap(module, attr: str, build):
    """Umhuellt module.attr: build(args, kwargs, result, error) -> [(cat, ref, name, text, ok)] (leer = nichts protokollieren)."""
    fn = getattr(module, attr, None)
    if fn is None or getattr(fn, "_dl", False):
        return

    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            for ent in build(a, k, None, None) or []:               # Echo-Unterdrueckung: schon vor dem Befehl merken (das Geraet meldet manchmal vor der Antwort zurueck)
                note_app_action(ent[1])
                _pre[ent[1]] = (current_actor(), current_user(), time.time())
        except Exception:                                           # noqa: BLE001
            pass
        try:
            res = fn(*a, **k)
        except Exception as e:                                              # noqa: BLE001
            try:
                for cat, ref, name, text, ok in build(a, k, None, e) or []:
                    log(cat, ref, name, text, ok)
            except Exception:                                               # noqa: BLE001
                pass
            raise
        try:
            for cat, ref, name, text, ok in build(a, k, res, None) or []:
                log(cat, ref, name, text, ok)
        except Exception as e2:                                             # noqa: BLE001
            log_.warning("Geraete-Logbuch (%s): %s", attr, e2)
        return res
    wrapper._dl = True
    setattr(module, attr, wrapper)


def _arg(a, k, i, name, default=None):
    return k[name] if name in k else (a[i] if len(a) > i else default)


def _minutes(secs) -> str:
    try:
        s = int(secs)
    except (TypeError, ValueError):
        return ""
    return f" (Timer {s // 60} min)" if s >= 60 else (f" (Timer {s} s)" if s > 0 else "")


SENSOR_WORDS = {"lock": ("verriegelt", "entriegelt"), "contact": ("offen", "geschlossen"), "motion": ("Bewegung erkannt", None),
                "presence": ("anwesend", "niemand da"), "input": ("aktiv", "nicht aktiv"), "key_short": ("kurz gedrückt", None),
                "running": ("an", "aus"), "key_long": ("lang gedrückt", None), "key_long_release": ("lang losgelassen", None)}
_sens_last: dict = {}


def sensor_word(sen: dict, val):
    """Das Wort zum Sensorwert, wie es auch die Anzeige zeigt: bei "Umkehren" stehen die Worte vertauscht (TRUE = geschlossen statt TRUE = offen)."""
    words = SENSOR_WORDS.get(sen.get("kind"))
    if not words:
        return None
    if sen.get("invert"):
        words = (words[1], words[0])
    return words[0] if val else words[1]
_app_act: dict = {}                    # Referenz -> Zeit der letzten Bedienung DURCH DIE APP (Echo-Unterdrueckung)
_ext_last: dict = {}
APP_ECHO_S = 10.0                      # so lange gilt eine Meldung des Geraets nach eigener Bedienung als deren Echo
EXTERNAL = "von außen (Gerät/Schalter)"


def note_app_action(ref: str) -> None:
    _app_act[ref] = time.time()


def external(ref: str, name: str, text: str, cat: str = "aktor") -> bool:
    """Ein Geraet hat von sich aus geschaltet (Lichtschranke, Taster am Geraet, eigener Timer): ins Logbuch, ausser es ist nur das Echo einer Bedienung durch die App.
    True = protokolliert."""
    now = time.time()
    if now - _app_act.get(ref, 0.0) < APP_ECHO_S:
        return False
    try:                                                           # Geraet, dessen Zustand auch als Sensor angelegt ist: mit den Worten des Sensors (offen/geschlossen ...)
        import homematic
        import shelly
        d = shelly._find(ref.split(":", 1)[1]) if ref.startswith("device:") else None
        sen = next((s for s in homematic.load_sensors() if s["id"] == d.get("as_sensor")), None) if d and d.get("as_sensor") else None
        if sen:
            val = ((text == "eingeschaltet") != bool(sen.get("dev_inv"))) != bool(sen.get("invert"))      # wie die Sensor-Abfrage: erst Zuordnung zum Geraet, dann Umkehren des Sensors
            if _sens_last.get(sen["id"], "?") != val:
                _sens_last[sen["id"]] = val
                word = sensor_word(sen, val)
                if word:
                    log("sensor", "sensor:" + sen["id"], sen.get("name") or sen["id"], word, True, by="Sensor")
            return True
    except Exception:                                              # noqa: BLE001
        pass
    last = _ext_last.get(ref)
    if last and last[0] == text and now - last[1] < 1.0:           # doppelte Meldung desselben Zustands
        return False
    _ext_last[ref] = (text, now)
    log(cat, ref, name, text, True, by=EXTERNAL)
    return True


def observe_sensor(sen: dict, val) -> None:
    """Zustandswechsel von Ja/Nein-Sensoren (Fenster, Tuer, Bewegung, Anwesenheit, Schloss, Eingang, Tasten) mitschreiben - nur beim Wechsel, nicht bei der ersten Abfrage."""
    try:
        if not SENSOR_WORDS.get(sen.get("kind")) or not sen.get("binary") or sen.get("source") == "remote" or val is None:
            return
        sid = sen["id"]
        prev = _sens_last.get(sid, "?")
        _sens_last[sid] = val
        if prev == "?" or prev == val:
            return
        text = sensor_word(sen, val)
        if text:
            log("sensor", "sensor:" + sid, sen.get("name") or sid, text, True, by="Sensor")
    except Exception as e:                                                  # noqa: BLE001
        log_.warning("Geraete-Logbuch (Sensor): %s", e)


def install() -> None:
    """Einmalig beim Start: die Schalt-Funktionen der Module umhuellen (wiederholtes Aufrufen schadet nicht)."""
    import homematic
    import shelly
    import virtual
    import wol

    def dev_name(dev_id):
        d = shelly._find(dev_id) or {}
        return d.get("name") or dev_id

    def err_text(e):
        return f"Schalten fehlgeschlagen: {e}"

    def b_set_state(a, k, res, e):
        did, on, timer = _arg(a, k, 0, "dev_id"), _arg(a, k, 1, "on"), _arg(a, k, 2, "timer_s")
        base = "eingeschaltet" if on else "ausgeschaltet"
        return [("aktor", "device:" + str(did), dev_name(did), (base + (_minutes(timer) if on else "")) if e is None else err_text(e), e is None)]
    _wrap(shelly, "set_state", b_set_state)

    def b_midea(a, k, res, e):
        did = _arg(a, k, 0, "dev_id")
        parts = ", ".join(f"{key} {v}" for key, v in k.items() if v is not None and key != "dev_id")
        return [("aktor", "device:" + str(did), dev_name(did), ("Klimaanlage gestellt" + (f" ({parts})" if parts else "")) if e is None else err_text(e), e is None)]
    _wrap(shelly, "midea_set", b_midea)

    def b_bright(a, k, res, e):
        did, pct = _arg(a, k, 0, "dev_id"), _arg(a, k, 1, "percent")
        return [("aktor", "device:" + str(did), dev_name(did), f"Helligkeit {pct} %" if e is None else err_text(e), e is None)]
    _wrap(shelly, "set_brightness", b_bright)

    def b_wled(a, k, res, e):
        did = _arg(a, k, 0, "dev_id")
        return [("aktor", "device:" + str(did), dev_name(did), "Licht eingestellt (Farbe/Effekt/Voreinstellung)" if e is None else err_text(e), e is None)]
    _wrap(shelly, "wled_apply", b_wled)
    _wrap(shelly, "wled_set", b_wled)

    def v_name(vid):
        return next((v.get("name") for v in virtual.load() if v["id"] == vid), None) or vid

    def b_press(a, k, res, e):
        vid = _arg(a, k, 0, "vid")
        if e is None and not res:
            return []
        return [("aktor", "virtual:" + str(vid), v_name(vid), "gedrückt" if e is None else err_text(e), e is None)]
    _wrap(virtual, "press", b_press)

    def b_vset(a, k, res, e):
        vid, on = _arg(a, k, 0, "vid"), _arg(a, k, 1, "on")
        if e is None and not res:
            return []
        return [("aktor", "virtual:" + str(vid), v_name(vid), ("eingeschaltet" if on else "ausgeschaltet") if e is None else err_text(e), e is None)]
    _wrap(virtual, "set_state", b_vset)

    def b_wake(a, k, res, e):
        wid = _arg(a, k, 0, "wid")
        name = next((x.get("name") for x in wol.load() if x["id"] == wid), None) or wid
        return [("aktor", "wol:" + str(wid), name, "aufgeweckt (Wake-on-LAN)" if e is None else f"Aufwecken fehlgeschlagen: {e}", e is None)]
    _wrap(wol, "wake", b_wake)

    def blind_name(bid):
        return next((x.get("name") for x in homematic.load_blinds() if x["id"] == bid), None) or bid

    def b_blind_set(a, k, res, e):
        bid, lv = _arg(a, k, 0, "bid"), _arg(a, k, 1, "level")
        try:
            lv_txt = f"{int(round(float(lv)))} %"
        except (TypeError, ValueError):
            lv_txt = str(lv)
        return [("aktor", "blind:" + str(bid), blind_name(bid), f"Rollladen auf {lv_txt} gefahren" if e is None else err_text(e), e is None)]
    _wrap(homematic, "blind_set", b_blind_set)

    def b_blind_stop(a, k, res, e):
        bid = _arg(a, k, 0, "bid")
        return [("aktor", "blind:" + str(bid), blind_name(bid), "Rollladen angehalten" if e is None else err_text(e), e is None)]
    _wrap(homematic, "blind_stop", b_blind_stop)

    def b_sound(a, k, res, e):
        sid, track = _arg(a, k, 0, "sid"), _arg(a, k, 1, "track")
        name = next((x.get("name") for x in homematic.load_sounds() if x["id"] == sid), None) or sid
        return [("aktor", "sound:" + str(sid), name, f"Ton abgespielt (Titel {track})" if e is None else f"Abspielen fehlgeschlagen: {e}", e is None)]
    _wrap(homematic, "sound_play", b_sound)

    def b_setpoints(a, k, res, e):
        ids, value = _arg(a, k, 0, "ids", []), _arg(a, k, 1, "value")
        items = homematic.load_setpoints()
        chosen = items if "*" in ids else [s for s in items if s["id"] in ids]
        out = []
        for i, s in enumerate(chosen):
            if e is not None:
                out.append(("thermostat", "setpoint:" + s["id"], s.get("name") or s["id"], err_text(e), False))
                continue
            r = res[i] if res and i < len(res) else (s.get("name"), value, None)
            ok = r[2] is None
            out.append(("thermostat", "setpoint:" + s["id"], s.get("name") or s["id"],
                        f"Solltemperatur {float(r[1]):g} °C" if ok else f"Solltemperatur setzen fehlgeschlagen: {r[2]}", ok))
        return out
    _wrap(homematic, "set_setpoints", b_setpoints)

    def b_lock(a, k, res, e):
        lid, action = _arg(a, k, 0, "lid"), _arg(a, k, 1, "action")
        name = next((x.get("name") for x in homematic.load_locks() if x["id"] == lid), None) or lid
        word = {"lock": "verriegelt", "unlock": "entriegelt", "open": "geöffnet"}.get(action, str(action))
        return [("sicherheit", "lock:" + str(lid), name, word if e is None else f"{word} fehlgeschlagen: {e}", e is None)]
    _wrap(homematic, "lock_action", b_lock)

    fn = getattr(homematic, "read_sensor", None)
    if fn is not None and not getattr(fn, "_dl", False):
        @functools.wraps(fn)
        def read_sensor(sen, latch=False):
            val = fn(sen, latch)
            observe_sensor(sen, val)
            return val
        read_sensor._dl = True
        homematic.read_sensor = read_sensor
