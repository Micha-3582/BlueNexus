"""
Eigene Schalter und Knoepfe (reine Software, kein Geraet dahinter).

  button   Knopf: wird gedrueckt (Dashboard oder Regel-Aktion). Fuer Regeln ist "wird gedrueckt" ein kurzer Impuls.
           Optional mit hinterlegter Web-Adresse (url, geheim, nie im Klartext an den Browser): beim Druecken wird sie aufgerufen (webhook.py).
  switch   Schalter mit Zustand an/aus (bleibt, bis jemand oder eine Regel ihn umschaltet).
  timer    Nachlauf-Timer: "an" = laeuft die eingestellte Zeit (Minuten), danach von selbst "aus". Jedes erneute Einschalten/Druecken startet die
           Zeit NEU (nachtriggerbar). Gemeinsamer Nachlauf fuer mehrere Ausloeser: viele Regeln starten den Timer, EINE Regel "Zustand halten"
           schaltet die Geraete, solange er laeuft.

Sie haben ihr eigenes Register (virtual.json) und erscheinen auf dem Dashboard in einer eigenen Kachel - getrennt von den
Hardware-Geraeten. Regeln der Art "Ablauf" (flows.py) koennen sie als Ausloeser (WENN) und als Aktion (DANN) benutzen.
Das Register selbst ist reine Logik; nur der optionale Web-Aufruf eines Knopfs geht ueber webhook.py (im Hintergrund).
"""
from __future__ import annotations

import os
import threading
import uuid

import pins

_DIR = os.path.dirname(os.path.abspath(__file__))
VIRTUAL_PATH = os.path.join(_DIR, "virtual.json")
KINDS = ("button", "switch", "timer")
DEFAULT_ICON = {"button": "🔘", "switch": "🎚️", "timer": "⏲️"}
DEFAULT_TIMER_MIN = 3
MAX_TIMER_MIN = 1440

_lock = threading.RLock()
_pressed: dict[str, float] = {}                  # knopf-id -> Zeitpunkt des Druecks (Impuls, bis die Regelschleife ihn gesehen hat)


class VirtualError(ValueError):
    pass


def _store():
    import store
    return store


def load() -> list[dict]:
    with _lock:
        d = _store()._load_json_recovering(VIRTUAL_PATH, lambda: [])
        return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []


def _save(items: list[dict]):
    _store()._dump_json(VIRTUAL_PATH, items, indent=2)


def _minutes(v, default=DEFAULT_TIMER_MIN) -> int:
    try:
        n = int(round(float(v if v not in (None, "") else default)))
    except (TypeError, ValueError):
        raise VirtualError("Nachlaufzeit: Zahl in Minuten")
    if not 1 <= n <= MAX_TIMER_MIN:
        raise VirtualError(f"Nachlaufzeit: 1 bis {MAX_TIMER_MIN} Minuten")
    return n


def _running(it: dict, now: float | None = None) -> bool:
    import time
    return it.get("kind") == "timer" and float(it.get("until") or 0) > (now if now is not None else time.time())


def _method(m) -> str:
    m = str(m or "GET").strip().upper()
    if m not in ("GET", "POST"):
        raise VirtualError("Aufruf-Art: GET oder POST")
    return m


def add(name: str, kind: str, icon: str | None = None, minutes=None, url: str | None = None, method: str | None = None) -> dict:
    name = (name or "").strip()[:60]
    if not name:
        raise VirtualError("Name eingeben")
    if kind not in KINDS:
        raise VirtualError("Art: Knopf, Schalter oder Nachlauf-Timer")
    with _lock:
        items = load()
        item = {"id": "v-" + uuid.uuid4().hex[:8], "name": name, "kind": kind, "icon": (icon or DEFAULT_ICON[kind]).strip()[:12] or DEFAULT_ICON[kind],
                "show": True, "on": False, "users": []}        # users=[]: zunaechst nur Administratoren (siehe visibility.py)
        if kind == "timer":
            item.update(minutes=_minutes(minutes), until=0.0)
        if url:
            if kind != "button":
                raise VirtualError("Ein Web-Aufruf geht nur bei einem Knopf")
            item.update(url=_url(url), method=_method(method))
        items.append(item)
        _save(items)
    return item


def _url(url: str) -> str:
    import webhook
    try:
        return webhook.validate(url)
    except webhook.WebhookError as e:
        raise VirtualError(str(e))


def update(vid: str, name: str | None = None, icon: str | None = None, show: bool | None = None, minutes=None,
           url: str | None = None, clear_url: bool = False, method: str | None = None) -> bool:
    with _lock:
        items = load()
        for it in items:
            if it["id"] == vid:
                if name is not None and name.strip():
                    it["name"] = name.strip()[:60]
                if icon is not None and 0 < len(icon.strip()) <= 12:
                    it["icon"] = icon.strip()
                if show is not None:
                    it["show"] = bool(show)
                if minutes is not None and it.get("kind") == "timer":
                    it["minutes"] = _minutes(minutes)
                if (url or clear_url or method) and it.get("kind") != "button":
                    raise VirtualError("Ein Web-Aufruf geht nur bei einem Knopf")
                if url:
                    it["url"] = _url(url)
                    it.setdefault("method", "GET")
                if clear_url:
                    it.pop("url", None)
                    it.pop("method", None)
                if method and it.get("url"):
                    it["method"] = _method(method)
                _save(items)
                return True
    return False


def remove(vid: str) -> bool:
    with _lock:
        items = load()
        keep = [x for x in items if x["id"] != vid]
        if len(keep) == len(items):
            return False
        _save(keep)
        _pressed.pop(vid, None)
        return True


def reorder(ids: list[str]):
    with _lock:
        items = load()
        pos = {i: n for n, i in enumerate(ids)}
        items.sort(key=lambda x: pos.get(x["id"], len(ids)))
        _save(items)


# ---- Sicherheits-PIN (4 Ziffern, siehe pins.py) fuer Bedienung ueber das Dashboard. Regeln/Ablaeufe loesen Knoepfe selbst aus und brauchen keine PIN.
def set_pin(vid: str, pin: str | None) -> bool:
    """PIN setzen (4 Ziffern) bzw. mit None/'' entfernen."""
    if pin:
        try:
            pins.validate(pin)
        except pins.PinError as e:
            raise VirtualError(str(e))
    with _lock:
        items = load()
        for it in items:
            if it["id"] == vid:
                pins.apply(it, pin)
                _save(items)
                return True
    return False


def has_pin(vid: str) -> bool:
    return any(x["id"] == vid and x.get("pin_hash") for x in load())


def check_pin(vid: str, pin) -> bool:
    it = next((x for x in load() if x["id"] == vid), None)
    return True if not it else pins.check(it, pin)


def public(item: dict) -> dict:
    """Fuer den Browser: ohne PIN-Hash und ohne die geheime Web-Adresse (nur "has_url" und die Art)."""
    out = pins.strip(item)
    if out.pop("url", None):
        out["has_url"] = True
    else:
        out.pop("method", None)
    return out


def press(vid: str) -> bool:
    """Knopf druecken (Impuls fuer Regeln)."""
    import time
    with _lock:
        it = next((x for x in load() if x["id"] == vid), None)
        if it and it["kind"] == "timer":
            return set_state(vid, True)                      # Timer: Druecken = (neu) starten
        if not it or it["kind"] != "button":
            return False
        _pressed[vid] = time.time()
        if it.get("url"):                                    # hinterlegte Web-Adresse aufrufen (im Hintergrund, Ergebnis im Logbuch)
            import webhook
            webhook.fire(vid, it["name"], it["url"], it.get("method", "GET"))
        return True


def toggle(vid: str) -> bool:
    """Schalter umschalten."""
    with _lock:
        it = next((x for x in load() if x["id"] == vid), None)
        if it and it["kind"] == "timer":
            return set_state(vid, not _running(it))
        return bool(it) and it["kind"] == "switch" and set_state(vid, not it.get("on"))


def set_state(vid: str, on: bool) -> bool:
    import time
    with _lock:
        items = load()
        for it in items:
            if it["id"] == vid and it["kind"] == "timer":      # an = Zeit (neu) starten, aus = sofort beenden
                it["until"] = (time.time() + _minutes(it.get("minutes")) * 60) if on else 0.0
                _save(items)
                return True
            if it["id"] == vid and it["kind"] == "switch":
                if bool(it.get("on")) != bool(on):
                    it["on"] = bool(on)
                    _save(items)
                return True
    return False


def snapshot() -> dict[str, dict]:
    """Fuer die Regel-Bedingungen: {id: {name, kind, on, pressed}}. Timer: on = laeuft noch (remaining_s = Restzeit)."""
    import time
    now = time.time()
    with _lock:
        return {x["id"]: {"id": x["id"], "name": x["name"], "kind": x["kind"], "on": _running(x, now) if x["kind"] == "timer" else bool(x.get("on")),
                          "pressed": x["id"] in _pressed, **({"remaining_s": max(0, int(float(x.get("until") or 0) - now))} if x["kind"] == "timer" else {})}
                for x in load()}


def next_due() -> float | None:
    """Zeitpunkt, an dem der naechste laufende Timer ablaeuft (die Regelschleife wacht dann genau auf)."""
    import time
    now = time.time()
    due = [float(x["until"]) for x in load() if _running(x, now)]
    return min(due) if due else None


def consume(ids) -> None:
    """Die Regelschleife hat diese Druecke gesehen - Impuls beenden."""
    with _lock:
        for i in ids:
            _pressed.pop(i, None)


def pressed_ids() -> list[str]:
    with _lock:
        return list(_pressed)


def users_registry():
    """(laden, speichern) fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load, _save
