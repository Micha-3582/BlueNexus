"""NFC-Tags: Das Handy scannt einen Tag, auf dem eine Adresse (/nfc/<Tag>) steht, und löst damit einen eigenen Knopf/Schalter aus.

Sicherheit: Ohne Anmeldung gilt nur ein **registriertes Handy**. Beim Registrieren bekommt der Browser des Handys ein langes zufälliges Kennzeichen
(Cookie, rund 10 Jahre gültig, hier nur als Hash gespeichert). Wer einen Tag kopiert, kann damit nichts auslösen. Handys lassen sich einzeln löschen.
Welche Handys einen Tag nutzen dürfen, ist je Tag einstellbar.
"""
import hashlib
import hmac
import os
import secrets
import threading
import time

import virtual

_DIR = os.path.dirname(os.path.abspath(__file__))
NFC_PATH = os.path.join(_DIR, "nfc.json")
TAG_ICON = "🏷️"                                 # Symbol des Etiketts: Tags und die dazu angelegten Knoepfe
COOKIE = "hn_nfc"
COOKIE_MAX_AGE = 10 * 365 * 86400
PAIR_TTL_S = 900                                  # Kopplungs-Link: 15 Minuten, einmal benutzbar
DEBOUNCE_S = 3                                    # derselbe Tag vom selben Handy innerhalb dieser Zeit zaehlt nur einmal (Doppel-Lesen, Neuladen)
MAX_PHONES, MAX_TAGS = 30, 60

_lock = threading.RLock()
_pair: dict = {}                                  # Code -> (Name, Ablauf)
_last: dict = {}                                  # (Tag, Handy) -> Zeit


class NfcError(ValueError):
    pass


def _store():
    import store
    return store


def load() -> dict:
    d = _store()._load_json_recovering(NFC_PATH, lambda: {"base_url": "", "phones": [], "tags": []})
    if not isinstance(d, dict):
        d = {}
    d.setdefault("base_url", "")
    d["phones"] = [p for p in d.get("phones", []) if isinstance(p, dict) and p.get("id")]
    d["tags"] = [t for t in d.get("tags", []) if isinstance(t, dict) and t.get("id")]
    return d


def _save(d: dict):
    _store()._dump_json(NFC_PATH, d, indent=2)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _clean_name(name, what: str) -> str:
    name = " ".join(str(name or "").split())[:40]
    if not name:
        raise NfcError(f"Bitte einen Namen für {what} eingeben")
    return name


# ---------------------------------------------------------------- Handys
def add_phone(name: str) -> tuple:
    """Neues Handy registrieren: gibt (Handy, Kennzeichen) zurueck. Das Kennzeichen wird nur hier im Klartext sichtbar."""
    name = _clean_name(name, "das Handy")
    with _lock:
        d = load()
        if len(d["phones"]) >= MAX_PHONES:
            raise NfcError(f"Höchstens {MAX_PHONES} Handys")
        token = secrets.token_urlsafe(32)
        p = {"id": "ph_" + secrets.token_hex(4), "name": name, "hash": _hash(token), "created": time.time(), "last_used": None, "last_tag": ""}
        d["phones"].append(p)
        _save(d)
    return p, token


def pair_new(name: str) -> str:
    """Einmal-Link fuer ein anderes Handy: der Code gilt PAIR_TTL_S Sekunden und genau einmal."""
    name = _clean_name(name, "das Handy")
    now = time.time()
    with _lock:
        for k in [k for k, v in _pair.items() if v[1] < now]:
            _pair.pop(k, None)
        code = secrets.token_urlsafe(18)
        _pair[code] = (name, now + PAIR_TTL_S)
    return code


def pair_peek(code: str):
    """Name des Handys zu einem noch gueltigen Kopplungs-Code (verbraucht ihn nicht), sonst None."""
    with _lock:
        v = _pair.get(code)
    return v[0] if v and v[1] >= time.time() else None


def pair_use(code: str):
    with _lock:
        v = _pair.pop(code, None)
    if not v or v[1] < time.time():
        return None
    return add_phone(v[0])


def remove_phone(pid: str) -> bool:
    with _lock:
        d = load()
        n = len(d["phones"])
        d["phones"] = [p for p in d["phones"] if p["id"] != pid]
        if len(d["phones"]) == n:
            return False
        for t in d["tags"]:                                       # explizite Auswahl: das geloeschte Handy faellt heraus (leer = niemand, NICHT alle)
            if t.get("phones") != ["*"]:
                t["phones"] = [x for x in t.get("phones", []) if x != pid]
        _save(d)
    return True


def identify(token: str):
    """Registriertes Handy zum Kennzeichen aus dem Cookie (None = unbekannt)."""
    if not token or len(token) > 200:
        return None
    h = _hash(token)
    for p in load()["phones"]:
        if hmac.compare_digest(p["hash"], h):
            return p
    return None


def rename_phone(pid: str, name: str) -> bool:
    name = _clean_name(name, "das Handy")
    with _lock:
        d = load()
        for p in d["phones"]:
            if p["id"] == pid:
                p["name"] = name
                _save(d)
                return True
    return False


# ---------------------------------------------------------------- Tags
def known_targets() -> list:
    """Alle eigenen Schalter/Knoepfe/Timer ohne PIN (aeltere Tags koennen auch auf Schalter/Timer zeigen und funktionieren weiter)."""
    return [{"id": v["id"], "name": v["name"], "kind": v["kind"]} for v in virtual.load() if not v.get("pin_hash")]


def targets() -> list:
    """Ziele fuer NEUE Tags: nur Knoepfe (der Tag drueckt, die Regel entscheidet; Schalter/Timer haben ohne Regel keine eigene Wirkung)."""
    return [t for t in known_targets() if t["kind"] == "button"]


def add_tag(name: str, target: str) -> dict:
    name = _clean_name(name, "den Tag")
    if target not in {t["id"] for t in targets()}:
        raise NfcError("Ziel (eigenen Knopf) wählen – PIN-geschützte sind nicht erlaubt")
    with _lock:
        d = load()
        if len(d["tags"]) >= MAX_TAGS:
            raise NfcError(f"Höchstens {MAX_TAGS} Tags")
        t = {"id": secrets.token_urlsafe(9), "name": name, "target": target, "phones": ["*"], "created": time.time(), "last_used": None}
        d["tags"].append(t)
        _save(d)
    return t


def update_tag(tid: str, name=None, phones=None, target=None) -> bool:
    with _lock:
        d = load()
        t = next((x for x in d["tags"] if x["id"] == tid), None)
        if not t:
            return False
        if name is not None:
            t["name"] = _clean_name(name, "den Tag")
        if target is not None:
            if target != t.get("target") and target not in {x["id"] for x in targets()}:
                raise NfcError("Ziel ungültig, kein Knopf oder PIN-geschützt")
            t["target"] = target
        if phones is not None:
            known = {p["id"] for p in d["phones"]}
            t["phones"] = ["*"] if phones == ["*"] else [x for x in dict.fromkeys(phones) if x in known]
        _save(d)
    return True


def remove_tag(tid: str) -> bool:
    with _lock:
        d = load()
        n = len(d["tags"])
        d["tags"] = [t for t in d["tags"] if t["id"] != tid]
        if len(d["tags"]) == n:
            return False
        _save(d)
    return True


def is_target(vid: str) -> bool:
    """Gehoert dieser eigene Knopf zu einem NFC-Tag? (sein Symbol ist dann fest)"""
    return any(t.get("target") == vid for t in load()["tags"])


def migrate_icons() -> None:
    """Alle Knoepfe, die zu einem NFC-Tag gehoeren, tragen das Etikett-Symbol (fest, dient der Erkennbarkeit)."""
    for t in load()["tags"]:
        it = next((v for v in virtual.load() if v["id"] == t.get("target")), None)
        if it and it.get("icon") != TAG_ICON:
            virtual.update(it["id"], icon=TAG_ICON)


def remove_target(vid: str) -> None:
    """Eigener Knopf/Schalter wurde geloescht: Tags darauf entfernen."""
    with _lock:
        d = load()
        keep = [t for t in d["tags"] if t.get("target") != vid]
        if len(keep) != len(d["tags"]):
            d["tags"] = keep
            _save(d)


def used_by(vid: str) -> list:
    return [t["name"] for t in load()["tags"] if t.get("target") == vid]


def public(d=None) -> dict:
    d = d or load()
    return {"base_url": d.get("base_url", ""), "tags": d["tags"], "targets": targets(), "known": known_targets(),
            "phones": [{k: p.get(k) for k in ("id", "name", "created", "last_used", "last_tag")} for p in d["phones"]]}


def set_base_url(url: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if url and not (url.startswith("http://") or url.startswith("https://")) or len(url) > 200 or any(c in url for c in " <>\"'"):
        raise NfcError("Adresse muss mit http:// oder https:// beginnen")
    with _lock:
        d = load()
        d["base_url"] = url
        _save(d)
    return url


# ---------------------------------------------------------------- Ausloesen
def trigger(tid: str, token: str) -> dict:
    """Ergebnis {ok, text, tag, phone, why}; 'why' = Grund bei Ablehnung: unknown_tag | unknown_phone | not_allowed | no_target | pin | debounced."""
    d = load()
    tag = next((t for t in d["tags"] if t["id"] == tid), None)
    phone = identify(token)
    if not tag:
        return {"ok": False, "why": "unknown_tag", "text": "Dieser Tag ist nicht (mehr) eingerichtet."}
    if not phone:
        return {"ok": False, "why": "unknown_phone", "tag": tag["name"], "text": "Dieses Handy ist nicht registriert."}
    if tag.get("phones") != ["*"] and phone["id"] not in tag.get("phones", []):
        return {"ok": False, "why": "not_allowed", "tag": tag["name"], "phone": phone["name"], "text": "Dieses Handy darf diesen Tag nicht nutzen."}
    it = next((v for v in virtual.load() if v["id"] == tag.get("target")), None)
    if not it:
        return {"ok": False, "why": "no_target", "tag": tag["name"], "phone": phone["name"], "text": "Das Ziel dieses Tags existiert nicht mehr."}
    if it.get("pin_hash"):
        return {"ok": False, "why": "pin", "tag": tag["name"], "phone": phone["name"], "text": "Das Ziel ist PIN-geschützt und lässt sich nicht per NFC auslösen."}
    now = time.time()
    with _lock:
        if now - _last.get((tag["id"], phone["id"]), 0) < DEBOUNCE_S:
            return {"ok": True, "why": "debounced", "tag": tag["name"], "phone": phone["name"], "text": f"{tag['name']} – bereits ausgelöst"}
        _last[(tag["id"], phone["id"])] = now
    kind = it["kind"]
    if kind == "button":
        virtual.press(it["id"])
        what = "ausgelöst"
    elif kind == "timer":
        virtual.press(it["id"])
        what = "gestartet"
    else:
        virtual.toggle(it["id"])
        on = next((v.get("on") for v in virtual.load() if v["id"] == it["id"]), None)
        what = "eingeschaltet" if on else "ausgeschaltet"
    with _lock:
        d = load()
        for p in d["phones"]:
            if p["id"] == phone["id"]:
                p["last_used"], p["last_tag"] = now, tag["name"]
        for t in d["tags"]:
            if t["id"] == tag["id"]:
                t["last_used"] = now
        _save(d)
    return {"ok": True, "why": "", "tag": tag["name"], "phone": phone["name"], "target": it["name"], "text": f"{tag['name']} – {it['name']} {what}"}
