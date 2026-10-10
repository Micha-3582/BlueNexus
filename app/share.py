"""
Geraete teilen zwischen BlueNexus-Instanzen (z. B. Wohnung und Mutter im selben Haus).

GEBER (Micha): legt unter "Teilen" eine Freigabe an, waehlt Geraete / Sensoren / Schalter und Knoepfe aus und gibt pro Eintrag "nur sehen" oder
"sehen und bedienen" frei. Dazu gibt es eine Adresse (Tunnel oder LAN) und einen Zugangsschluessel (nur ein Mal sichtbar, gespeichert wird nur sein Hash).
EMPFAENGER (Mama): traegt Adresse + Schluessel unter "Fremde Quellen" ein und holt sich die freigegebenen Eintraege in die eigene Anlage. Sie erscheinen dort
wie eigene Geraete bzw. Sensoren (mit Vermerk "von ..."), lassen sich in Regeln nutzen, und Befehle gehen zum Geber, der sie mit SEINEN Zugangsdaten ausfuehrt
(z. B. Klimaanlage: der Medea-Login bleibt nur beim Geber).

Alles laeuft ueber HTTP(S) mit "Authorization: Bearer <Schluessel>" gegen /share/v1/...; es gibt keine Verbindung zu irgendeinem Dritten.
Weitergeben ist nicht moeglich: einen Eintrag, der selbst von einer Quelle stammt, kann man nicht weiter freigeben.

Eintraege werden ueber eine Referenz angesprochen: "device:<id>", "sensor:<id>", "virtual:<id>".
Ein Empfaenger-Geraet ist ein normaler Geraete-Eintrag mit kind="remote" (rkind = Art beim Geber, z. B. "midea"); ein Empfaenger-Sensor ein Sensor mit source="remote".
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

_DIR = os.path.dirname(os.path.abspath(__file__))
SHARES_PATH = os.path.join(_DIR, "shares.json")            # Geber: Freigaben
SOURCES_PATH = os.path.join(_DIR, "sources.json")          # Empfaenger: Fremde Quellen (mit Schluessel!)
API_VERSION = 1
REF_TYPES = ("device", "sensor", "virtual")
MODES = ("view", "control")
MAX_ITEMS = 300
CACHE_TTL_S = 2.0                                          # eine Abfrage pro Quelle genuegt fuer alle Geraete/Sensoren dieser Quelle
FAIL_TTL_S = 8.0                                           # nach einem Fehler nicht jede Runde neu warten
TIMEOUT = (3.0, 8.0)
STATUS_KEYS = ("online", "on", "power", "info", "error")

_lock = threading.RLock()


class ShareError(Exception):
    def __init__(self, msg: str, code: int = 400):
        super().__init__(msg)
        self.code = code


def _store():
    import store
    return store


def _load(path: str) -> list[dict]:
    d = _store()._load_json_recovering(path, lambda: [])
    return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []


def _save(path: str, items: list[dict]):
    _store()._dump_json(path, items, indent=2)


# ================================================================ GEBER
def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(s: dict) -> dict:
    return {"id": s["id"], "name": s["name"], "items": list(s.get("items") or []), "created": s.get("created", 0), "last_seen": s.get("last_seen", 0)}


def list_shares() -> list[dict]:
    return [_public(s) for s in _load(SHARES_PATH)]


def create(name: str) -> tuple[dict, str]:
    name = (name or "").strip()[:60]
    if not name:
        raise ShareError("Name eingeben (z. B. „Mama“)")
    token = "bnx_" + secrets.token_urlsafe(24)
    s = {"id": "s-" + uuid.uuid4().hex[:8], "name": name, "token_hash": _hash(token), "items": [], "created": time.time(), "last_seen": 0}
    with _lock:
        items = _load(SHARES_PATH)
        items.append(s)
        _save(SHARES_PATH, items)
    return _public(s), token


def regenerate(share_id: str) -> str:
    """Neuer Schluessel (der alte gilt sofort nicht mehr)."""
    token = "bnx_" + secrets.token_urlsafe(24)
    with _lock:
        items = _load(SHARES_PATH)
        for s in items:
            if s["id"] == share_id:
                s["token_hash"] = _hash(token)
                _save(SHARES_PATH, items)
                return token
    raise ShareError("Freigabe nicht gefunden", 404)


def remove(share_id: str) -> bool:
    with _lock:
        items = _load(SHARES_PATH)
        keep = [s for s in items if s["id"] != share_id]
        if len(keep) == len(items):
            return False
        _save(SHARES_PATH, keep)
        return True


def shareable() -> list[dict]:
    """Was sich teilen laesst: [{ref, type, name, icon, detail}] - ohne Eintraege, die selbst aus einer fremden Quelle stammen."""
    import homematic
    import shelly
    import virtual
    out = []
    for d in shelly.load_devices():
        if d.get("kind") == "remote":
            continue
        out.append({"ref": "device:" + d["id"], "type": "device", "name": d.get("name") or d["id"], "icon": d.get("icon") or "🔌",
                    "detail": "Klimaanlage" if d.get("kind") == "midea" else "Gerät"})
    for s in homematic.load_sensors():
        if s.get("source") == "remote":
            continue
        out.append({"ref": "sensor:" + s["id"], "type": "sensor", "name": s.get("name") or s["id"], "icon": s.get("icon") or "📟", "detail": "Sensor"})
    for v in virtual.load():
        out.append({"ref": "virtual:" + v["id"], "type": "virtual", "name": v.get("name") or v["id"], "icon": v.get("icon") or "🎚️",
                    "detail": {"button": "Knopf", "switch": "Schalter", "timer": "Nachlauf-Timer"}.get(v.get("kind"), "Schalter")})
    return out


def update(share_id: str, name: str | None = None, items=None) -> dict:
    with _lock:
        shares = _load(SHARES_PATH)
        s = next((x for x in shares if x["id"] == share_id), None)
        if not s:
            raise ShareError("Freigabe nicht gefunden", 404)
        if name is not None:
            n = name.strip()[:60]
            if not n:
                raise ShareError("Name darf nicht leer sein")
            s["name"] = n
        if items is not None:
            if not isinstance(items, list) or len(items) > MAX_ITEMS:
                raise ShareError("Einträge ungültig")
            valid = {x["ref"] for x in shareable()}
            clean, seen = [], set()
            for it in items:
                ref = str(it.get("ref") if isinstance(it, dict) else "")
                mode = it.get("mode") if isinstance(it, dict) else None
                if ref in seen:
                    continue
                if ref not in valid:
                    raise ShareError("Ein Eintrag lässt sich nicht freigeben (gibt es nicht mehr?)")
                if mode not in MODES:
                    raise ShareError("Art der Freigabe: nur sehen oder bedienen")
                seen.add(ref)
                clean.append({"ref": ref, "mode": mode})
            s["items"] = clean
        _save(SHARES_PATH, shares)
        return _public(s)


def by_token(token: str) -> dict | None:
    """Freigabe zum Schluessel (zeitkonstanter Vergleich). Vermerkt nebenbei, wann sie zuletzt benutzt wurde."""
    token = (token or "").strip()
    if not token:
        return None
    h = _hash(token)
    found = None
    for s in _load(SHARES_PATH):
        if hmac.compare_digest(s.get("token_hash", ""), h):
            found = s
    if found and time.time() - float(found.get("last_seen") or 0) > 60:
        with _lock:
            shares = _load(SHARES_PATH)
            for s in shares:
                if s["id"] == found["id"]:
                    s["last_seen"] = time.time()
            _save(SHARES_PATH, shares)
    return found


def _parse(ref: str) -> tuple[str, str]:
    t, _, i = str(ref or "").partition(":")
    if t not in REF_TYPES or not i:
        raise ShareError("Eintrag unbekannt", 404)
    return t, i


def provider_items(share: dict) -> list[dict]:
    """Was der Empfaenger sieht: freigegebene Eintraege samt aktuellem Zustand (parallel abgefragt)."""
    import homematic
    import shelly
    import virtual
    mode = {x["ref"]: x["mode"] for x in share.get("items") or []}
    dev_ids = {r.split(":", 1)[1] for r in mode if r.startswith("device:")}
    sens_ids = {r.split(":", 1)[1] for r in mode if r.startswith("sensor:")}
    out = []
    if dev_ids:
        devs = [d for d in shelly.list_with_status(ids=dev_ids) if d.get("kind") != "remote"]
        for d in devs:
            kind = d.get("kind") or "shelly"
            sw = d.get("switchable") is not False
            out.append({"ref": "device:" + d["id"], "type": "device", "name": d.get("name") or d["id"], "icon": d.get("icon") or "🔌", "kind": kind,
                        "control": mode["device:" + d["id"]] == "control" and sw,
                        "state": {k: d[k] for k in d if k in STATUS_KEYS or k in ("mode", "target_c", "indoor_c", "outdoor_c", "fan", "swing", "eco")}})
    if sens_ids:
        sens = [s for s in homematic.load_sensors() if s["id"] in sens_ids and s.get("source") != "remote"]
        vals = homematic.read_values(sens)
        for s in sens:
            out.append({"ref": "sensor:" + s["id"], "type": "sensor", "name": s.get("name") or s["id"], "icon": s.get("icon") or "📟", "kind": s.get("kind") or "",
                        "binary": bool(s.get("binary")), "unit": s.get("unit") or "", "room": s.get("room") or "", "control": False, "state": {"value": vals.get(s["id"])}})
    snap = virtual.snapshot()
    for v in virtual.load():
        r = "virtual:" + v["id"]
        if r in mode:
            out.append({"ref": r, "type": "virtual", "name": v.get("name") or v["id"], "icon": v.get("icon") or "🎚️", "kind": v.get("kind") or "switch",
                        "control": mode[r] == "control", "state": {"online": True, "on": bool((snap.get(v["id"]) or {}).get("on"))}})
    order = {r: n for n, r in enumerate(x["ref"] for x in share.get("items") or [])}
    out.sort(key=lambda x: order.get(x["ref"], 999))
    return out


def _granted(share: dict, ref: str, need_control: bool) -> tuple[str, str]:
    t, i = _parse(ref)
    mode = next((x["mode"] for x in share.get("items") or [] if x["ref"] == ref), None)
    if mode is None:
        raise ShareError("Eintrag unbekannt", 404)
    if need_control and mode != "control":
        raise ShareError("Dieser Eintrag ist nur zum Ansehen freigegeben", 403)
    return t, i


def provider_act(share: dict, ref: str, body: dict) -> dict:
    """Schalten / Druecken. Gibt den neuen Zustand zurueck ({online, on, ...}) und den Namen fuers Logbuch."""
    import shelly
    import virtual
    t, i = _granted(share, ref, True)
    on = bool(body.get("on"))
    if t == "device":
        d = next((x for x in shelly.load_devices() if x["id"] == i and x.get("kind") != "remote"), None)
        if not d:
            raise ShareError("Gerät nicht gefunden", 404)
        timer = body.get("timer_s")
        try:
            timer = int(timer) if timer not in (None, "") else None
        except (TypeError, ValueError):
            timer = None
        try:
            st = shelly.set_state(i, on, timer)
        except shelly.ShellyError as e:
            raise ShareError(str(e), 400)
        return {"name": d.get("name") or i, "on": on, "state": {k: v for k, v in (st or {}).items() if k in STATUS_KEYS}}
    if t == "virtual":
        v = next((x for x in virtual.load() if x["id"] == i), None)
        if not v:
            raise ShareError("Eintrag nicht gefunden", 404)
        ok = virtual.press(i) if v["kind"] == "button" else virtual.set_state(i, on)
        if not ok:
            raise ShareError("Eintrag nicht gefunden", 404)
        return {"name": v.get("name") or i, "on": on, "state": {"online": True, "on": False if v["kind"] == "button" else on}}
    raise ShareError("Dieser Eintrag lässt sich nicht schalten", 400)


def provider_ac(share: dict, ref: str, body: dict | None) -> dict:
    """Klimaanlage: body=None -> Moeglichkeiten + Zustand, sonst setzen {power, mode, target, fan, swing, eco}."""
    import shelly
    t, i = _granted(share, ref, body is not None)
    d = next((x for x in shelly.load_devices() if x["id"] == i and x.get("kind") == "midea"), None) if t == "device" else None
    if not d:
        raise ShareError("Das ist keine Klimaanlage", 400)
    try:
        if body is None:
            return {"name": d.get("name") or i, "details": shelly.midea_details(i)}
        power = body.get("power")
        res = shelly.midea_set(i, power=(None if power is None else bool(power)), mode=body.get("mode"), target=body.get("target"), fan=body.get("fan"),
                               swing=body.get("swing"), eco=body.get("eco") if isinstance(body.get("eco"), bool) else None)
        return {"name": d.get("name") or i, "state": res}
    except shelly.ShellyError as e:
        raise ShareError(str(e), 400)


# ================================================================ EMPFAENGER
def _norm_url(url: str) -> str:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise ShareError("Adresse: http:// oder https:// und der Name des anderen Systems, z. B. https://mama.beispiel.de")
    return f"{u.scheme}://{u.netloc}"


def _src_public(s: dict) -> dict:
    return {"id": s["id"], "name": s["name"], "url": s["url"]}


def list_sources() -> list[dict]:
    return [_src_public(s) for s in _load(SOURCES_PATH)]


def _source(source_id: str) -> dict:
    s = next((x for x in _load(SOURCES_PATH) if x["id"] == source_id), None)
    if not s:
        raise ShareError("Quelle nicht gefunden", 404)
    return s


def _http(s: dict, method: str, path: str, **kw):
    try:
        r = requests.request(method, s["url"] + path, headers={"Authorization": "Bearer " + s["token"]}, timeout=TIMEOUT, **kw)
    except requests.RequestException as e:
        raise ShareError(f"{s.get('name', 'Quelle')} nicht erreichbar ({e.__class__.__name__})", 502)
    try:
        j = r.json()
    except ValueError:
        j = {}
    if r.status_code == 401:
        raise ShareError("Der Zugangsschlüssel wurde abgelehnt (neu erzeugt oder falsch eingetippt?)", 401)
    if not r.ok:
        raise ShareError(j.get("error") or f"Fehler {r.status_code}", r.status_code if r.status_code < 500 else 502)
    return j


def add_source(name: str, url: str, token: str) -> dict:
    name = (name or "").strip()[:60]
    token = (token or "").strip()
    if not name:
        raise ShareError("Name eingeben (z. B. „Wohnung Micha“)")
    if not token:
        raise ShareError("Zugangsschlüssel eingeben")
    s = {"id": "q-" + uuid.uuid4().hex[:8], "name": name, "url": _norm_url(url), "token": token}
    j = _http(s, "GET", "/share/v1/items")                       # Probe: Adresse + Schluessel pruefen
    with _lock:
        items = _load(SOURCES_PATH)
        items.append(s)
        _save(SOURCES_PATH, items)
    _cache[s["id"]] = (time.time(), j.get("items") or [], None)
    return _src_public(s)


def imported_ids(source_id: str) -> tuple[list[str], list[str]]:
    import homematic
    import shelly
    return ([d["id"] for d in shelly.load_devices() if d.get("kind") == "remote" and d.get("source") == source_id],
            [s["id"] for s in homematic.load_sensors() if s.get("source") == "remote" and s.get("src") == source_id])


def remove_source(source_id: str) -> bool:
    """Quelle samt aller von dort geholten Geraete und Sensoren entfernen."""
    import homematic
    import shelly
    with _lock:
        items = _load(SOURCES_PATH)
        keep = [s for s in items if s["id"] != source_id]
        if len(keep) == len(items):
            return False
        _save(SOURCES_PATH, keep)
    dev_ids, sen_ids = imported_ids(source_id)
    shelly._save([d for d in shelly.load_devices() if d["id"] not in dev_ids])
    homematic._save_sensors([s for s in homematic.load_sensors() if s["id"] not in sen_ids])
    _cache.pop(source_id, None)
    return True


_cache: dict[str, tuple] = {}                                  # Quelle -> (Zeit, Eintraege | None, Fehler | None)
_fetch_locks: dict[str, threading.Lock] = {}


def fetch(source_id: str, force: bool = False) -> tuple[list[dict] | None, str | None]:
    """(Eintraege, Fehlertext) der Quelle - mit kurzem Zwischenspeicher, damit viele Geraete nur eine Abfrage ausloesen."""
    lk = _fetch_locks.setdefault(source_id, threading.Lock())
    with lk:
        hit = _cache.get(source_id)
        if hit and not force and time.time() - hit[0] < (FAIL_TTL_S if hit[2] else CACHE_TTL_S):
            return hit[1], hit[2]
        try:
            s = _source(source_id)
            j = _http(s, "GET", "/share/v1/items")
            _cache[source_id] = (time.time(), j.get("items") or [], None)
        except ShareError as e:
            _cache[source_id] = (time.time(), None, str(e))
        h = _cache[source_id]
        return h[1], h[2]


def _item(source_id: str, ref: str) -> tuple[dict | None, str | None]:
    items, err = fetch(source_id)
    if items is None:
        return None, err
    return next((x for x in items if x.get("ref") == ref), None), None


def source_items(source_id: str) -> list[dict]:
    """Was die Quelle anbietet, markiert mit 'already' (schon geholt)."""
    items, err = fetch(source_id, force=True)
    if items is None:
        raise ShareError(err or "Quelle nicht erreichbar", 502)
    have_d, have_s = imported_ids(source_id)
    have = set(have_d) | set(have_s)
    return [{"ref": x["ref"], "type": x.get("type"), "name": x.get("name"), "icon": x.get("icon"), "kind": x.get("kind"), "control": bool(x.get("control")),
             "already": _local_id(source_id, x["ref"]) in have} for x in items]


def _local_id(source_id: str, ref: str) -> str:
    return "r-" + source_id[2:] + "-" + hashlib.sha1(ref.encode("utf-8")).hexdigest()[:8]


def import_items(source_id: str, refs: list[str]) -> dict:
    """Legt die gewaehlten Eintraege als Geraete bzw. Sensoren an. Gibt {devices: [...], sensors: [...]} (die neuen Eintraege) zurueck."""
    import homematic
    import shelly
    src = _source(source_id)
    items, err = fetch(source_id, force=True)
    if items is None:
        raise ShareError(err or "Quelle nicht erreichbar", 502)
    by_ref = {x["ref"]: x for x in items}
    devs, sens = shelly.load_devices(), homematic.load_sensors()
    have = {d["id"] for d in devs} | {s["id"] for s in sens}
    new_d, new_s = [], []
    for ref in refs:
        x = by_ref.get(ref)
        if not x:
            raise ShareError("Eintrag wird nicht (mehr) angeboten", 404)
        lid = _local_id(source_id, ref)
        if lid in have:
            continue
        model = "von " + src["name"]
        if x.get("type") == "sensor":
            new_s.append({"id": lid, "kind": x.get("kind") or "", "source": "remote", "src": source_id, "rref": ref, "address": ref, "interface": "remote", "datapoint": "",
                          "unit": x.get("unit") or "", "binary": bool(x.get("binary")), "model": model, "room": x.get("room") or "", "name": x.get("name") or ref,
                          "icon": x.get("icon") or "📟", "users": [], "show": False})
        else:
            rkind = ("virtual-" + str(x.get("kind"))) if x.get("type") == "virtual" else (x.get("kind") or "shelly")
            new_d.append({"id": lid, "kind": "remote", "source": source_id, "rref": ref, "rkind": rkind, "gen": 0, "channel": 0, "model": model,
                          "name": x.get("name") or ref, "icon": x.get("icon") or "🔌", "room": "", "switchable": bool(x.get("control")),
                          "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "users": []})
        have.add(lid)
    if new_d:
        shelly._save(devs + new_d)
    if new_s:
        homematic._save_sensors(sens + new_s)
    return {"devices": new_d, "sensors": new_s}


# ---- Einbindung in Geraete / Sensoren / Klima -----------------------------------------
def status(d: dict) -> dict:
    """Zustand eines Empfaenger-Geraets (aus dem Zwischenspeicher der Quelle)."""
    x, err = _item(d.get("source", ""), d.get("rref", ""))
    if err:
        return {"online": False, "on": None, "power": None, "error": err}
    if x is None:
        return {"online": False, "on": None, "power": None, "error": "Nicht mehr freigegeben"}
    st = dict(x.get("state") or {})
    st.setdefault("online", True)
    st.setdefault("on", None)
    st.setdefault("power", None)
    return st


def set_state(d: dict, on: bool, timer_s: int | None = None) -> dict:
    x, err = _item(d.get("source", ""), d.get("rref", ""))
    if err:
        raise ShareError(err, 502)
    if x is None:
        raise ShareError("Nicht mehr freigegeben", 404)
    if not x.get("control"):
        raise ShareError("Der Geber hat dieses Gerät nur zum Ansehen freigegeben", 403)
    j = _http(_source(d["source"]), "POST", "/share/v1/act", json={"ref": d["rref"], "on": bool(on), "timer_s": timer_s})
    fetch(d["source"], force=True)
    return j.get("state") or status(d)


def read_sensor(sen: dict):
    """Wert eines Empfaenger-Sensors: Zahl, True/False oder None (nicht erreichbar)."""
    x, err = _item(sen.get("src", ""), sen.get("rref", ""))
    if x is None or err:
        return None
    v = (x.get("state") or {}).get("value")
    if v is None:
        return None
    if sen.get("binary"):
        v = bool(v)
        return (not v) if sen.get("invert") else v
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


def ac_details(d: dict) -> dict:
    return _http(_source(d["source"]), "GET", "/share/v1/ac", params={"ref": d["rref"]}).get("details") or {}


def ac_set(d: dict, **kw) -> dict:
    body = {k: v for k, v in kw.items() if v is not None}
    j = _http(_source(d["source"]), "POST", "/share/v1/ac", json={"ref": d["rref"], **body})
    fetch(d["source"], force=True)
    return j.get("state") or {}
