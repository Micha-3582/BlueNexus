"""
Offene Lese-Schnittstelle fuer andere Programme (API v1) - nur im lokalen Netz, nur lesend.

Gedacht fuer alles, was Zustaende aus BlueNexus lesen will: ein Info-Monitor, ein Skript, ein anderes Smart-Home-System, ein eigenes Projekt.
Mit Teilen (share.py, zwischen zwei BlueNexus-Anlagen, auch ueber das Internet) hat sie nichts zu tun: eigene Schluessel, eigene Datei,
eigener Pfad (/api/v1/...). Die Teilen-Funktion bleibt unveraendert.

Schluessel:
- Ein Administrator legt in den Einstellungen Schluessel an (Name, welche Sensoren/Geraete/Schalter, optional erlaubte Absenderadressen).
- Der Schluessel (bnxapi_...) wird nur EINMAL angezeigt, gespeichert wird nur ein Hash (api_keys.json, nicht im Repo).
- Rechte: nur lesen. Nichts schalten, nichts aendern, keine Zugangsdaten, keine internen Adressen oder PINs in der Antwort.

Nur lokales Netz (lan_request_ok):
- Die Absenderadresse der Verbindung muss aus einem privaten Netz kommen (10.x, 172.16-31.x, 192.168.x, 127.x, fe80::, fc00::/7) ...
- ... und die Anfrage darf nicht ueber Cloudflare (Tunnel) oder einen fremden Proxy hereinkommen. Der Tunnel verbindet von localhost, deshalb
  reicht die Adresse allein nicht: Cloudflare-Kopfzeilen (CF-Connecting-IP, CF-Ray ...) sowie weitergeleitete oeffentliche Adressen
  (X-Forwarded-For, X-Real-IP, Forwarded) fuehren zur Ablehnung. Auch bei laufendem Tunnel ist die Schnittstelle von aussen nicht erreichbar.

Aenderungszeitpunkt: BlueNexus merkt sich (api_changes.json), seit wann ein Eintrag seinen aktuellen Zustand hat ("changed_at"). Ein
Hintergrundlauf liest dazu alle paar Sekunden die freigegebenen Eintraege; nach einem Neustart bleibt der Zeitpunkt erhalten, solange sich
der Zustand nicht geaendert hat.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime

log = logging.getLogger("extapi")

API_VERSION = 1
_DIR = os.path.dirname(os.path.abspath(__file__))
KEYS_PATH = os.path.join(_DIR, "api_keys.json")
CHANGES_PATH = os.path.join(_DIR, "api_changes.json")
TOKEN_PREFIX = "bnxapi_"
MAX_KEYS = 20
MAX_REFS = 1000
MAX_ALLOW = 20
SAMPLE_S = 15                                       # so oft liest der Hintergrundlauf die freigegebenen Eintraege (fuer "changed_at")
REF_TYPES = ("device", "sensor", "virtual")         # Geraete (Aktoren), Sensoren, eigene Schalter/Knoepfe
_ID_RE = re.compile(r"[A-Za-z0-9_.\-]{1,64}")

_lock = threading.RLock()


class ApiKeyError(Exception):
    pass


# ---------------------------------------------------------------- Speicher
def _load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(path: str, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_keys() -> list:
    d = _load(KEYS_PATH)
    return d if isinstance(d, list) else []


def _save_keys(keys: list) -> None:
    _save(KEYS_PATH, keys)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Pruefung der Eingaben
def normalize_refs(refs) -> list:
    """Verweise "device:ID" / "sensor:ID" / "virtual:ID" - eindeutig, nur bekannte Arten."""
    out = []
    for r in refs if isinstance(refs, list) else []:
        t, _, i = str(r or "").partition(":")
        ref = f"{t}:{i}"
        if t in REF_TYPES and _ID_RE.fullmatch(i) and ref not in out:
            out.append(ref)
        if len(out) >= MAX_REFS:
            break
    return out


def normalize_allow(items) -> list:
    """Erlaubte Absenderadressen (einzelne Adresse oder Netz wie 192.168.2.0/24). Leer = jeder Rechner im lokalen Netz."""
    out = []
    for x in items if isinstance(items, list) else []:
        s = str(x or "").strip()
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            raise ApiKeyError(f"„{s}“ ist keine gültige Adresse (z. B. 192.168.2.40 oder 192.168.2.0/24)")
        t = str(net.network_address) if net.num_addresses == 1 else str(net)
        if t not in out:
            out.append(t)
    if len(out) > MAX_ALLOW:
        raise ApiKeyError(f"Höchstens {MAX_ALLOW} erlaubte Adressen")
    return out


def _name(raw) -> str:
    n = " ".join(str(raw or "").split())[:60]
    if not n:
        raise ApiKeyError("Bitte dem Schlüssel einen Namen geben (z. B. den Namen des Programms, das ihn nutzt)")
    return n


def public(k: dict) -> dict:
    """Fuer den Browser: ohne Hash."""
    return {"id": k["id"], "name": k["name"], "prefix": k.get("prefix", ""), "created": k.get("created", 0), "last_used": k.get("last_used", 0),
            "last_ip": k.get("last_ip", ""), "all": bool(k.get("all")), "items": list(k.get("items") or []), "allow": list(k.get("allow") or [])}


# ---------------------------------------------------------------- Schluessel verwalten
def list_public() -> list:
    return [public(k) for k in load_keys()]


def create(name, all_items=False, items=None, allow=None):
    """Neuen Schluessel anlegen. Rueckgabe (Eintrag, Schluessel im Klartext) - der Klartext wird nur dieses eine Mal geliefert."""
    nm = _name(name)
    refs, al = normalize_refs(items), normalize_allow(allow)
    with _lock:
        keys = load_keys()
        if len(keys) >= MAX_KEYS:
            raise ApiKeyError(f"Höchstens {MAX_KEYS} Schlüssel")
        token = TOKEN_PREFIX + secrets.token_urlsafe(30)
        k = {"id": "k-" + secrets.token_hex(4), "name": nm, "hash": _hash(token), "prefix": token[:len(TOKEN_PREFIX) + 4], "created": time.time(), "last_used": 0,
             "last_ip": "", "all": bool(all_items), "items": refs, "allow": al}
        keys.append(k)
        _save_keys(keys)
    return public(k), token


def update(kid: str, name=None, all_items=None, items=None, allow=None) -> dict | None:
    with _lock:
        keys = load_keys()
        k = next((x for x in keys if x["id"] == kid), None)
        if not k:
            return None
        if name is not None:
            k["name"] = _name(name)
        if all_items is not None:
            k["all"] = bool(all_items)
        if items is not None:
            k["items"] = normalize_refs(items)
        if allow is not None:
            k["allow"] = normalize_allow(allow)
        _save_keys(keys)
        return public(k)


def regenerate(kid: str):
    """Neuen Schluessel-Text vergeben (der alte ist sofort ungueltig). Rueckgabe (Eintrag, Klartext) oder None."""
    with _lock:
        keys = load_keys()
        k = next((x for x in keys if x["id"] == kid), None)
        if not k:
            return None
        token = TOKEN_PREFIX + secrets.token_urlsafe(30)
        k["hash"], k["prefix"] = _hash(token), token[:len(TOKEN_PREFIX) + 4]
        _save_keys(keys)
        return public(k), token


def remove(kid: str) -> bool:
    with _lock:
        keys = load_keys()
        rest = [k for k in keys if k["id"] != kid]
        if len(rest) == len(keys):
            return False
        _save_keys(rest)
        return True


def by_token(token: str, ip: str = "") -> dict | None:
    """Schluessel zum Text (zeitkonstanter Vergleich). Vermerkt nebenbei, wann und von wo er zuletzt benutzt wurde (hoechstens einmal pro Minute)."""
    token = (token or "").strip()
    if not token.startswith(TOKEN_PREFIX):
        return None
    h = _hash(token)
    found = None
    for k in load_keys():
        if hmac.compare_digest(k.get("hash", ""), h):
            found = k
    if found and (time.time() - float(found.get("last_used") or 0) > 60 or (ip and found.get("last_ip") != ip)):
        with _lock:
            keys = load_keys()
            for k in keys:
                if k["id"] == found["id"]:
                    k["last_used"], k["last_ip"] = time.time(), ip
            _save_keys(keys)
    return found


# ---------------------------------------------------------------- nur lokales Netz
_LAN_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16", "::1/128", "fe80::/10", "fc00::/7")]


def _private(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text.strip().split("%")[0].strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip in n for n in _LAN_NETS if n.version == ip.version)


def lan_request_ok(headers, remote_addr: str) -> bool:
    """True nur, wenn die Anfrage direkt aus dem lokalen Netz kommt (nicht ueber Cloudflare/Tunnel oder einen Proxy aus dem Internet)."""
    for h in ("CF-Connecting-IP", "CF-Ray", "CF-Visitor", "CF-IPCountry", "True-Client-IP", "CDN-Loop"):
        if headers.get(h):
            return False
    for h in ("X-Forwarded-For", "X-Real-IP"):
        v = headers.get(h)
        if v and not all(_private(p) for p in v.split(",") if p.strip()):
            return False
    fwd = headers.get("Forwarded")
    if fwd:
        for m in re.finditer(r'for="?\[?([^;,"\]]+)', fwd, re.I):
            if not _private(m.group(1)):
                return False
    return _private(remote_addr or "")


def ip_allowed(key: dict, ip: str) -> bool:
    """Hat der Schluessel eine Liste erlaubter Absender, muss die Adresse dazu passen."""
    allow = key.get("allow") or []
    if not allow:
        return True
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in ipaddress.ip_network(a, strict=False) for a in allow)


# ---------------------------------------------------------------- Zustaende lesen
# Sensorart -> (Wort fuer "Wert wahr", Wort fuer "falsch", Anzeigetext wahr, Anzeigetext falsch) - wie die Dashboard-Kachel
_SENSOR_WORDS = {
    "lock": ("locked", "unlocked", "verriegelt", "entriegelt"),
    "contact": ("open", "closed", "offen", "geschlossen"),
    "motion": ("motion", "none", "Bewegung", "keine Bewegung"),
    "presence": ("present", "absent", "anwesend", "niemand da"),
    "input": ("active", "inactive", "aktiv", "nicht aktiv"),
    "key_short": ("pressed", "idle", "kurz gedrückt", "nicht gedrückt"),
    "key_long": ("pressed", "idle", "lang gedrückt", "nicht gedrückt"),
    "key_long_release": ("released", "idle", "lang losgelassen", "nicht losgelassen"),
}
_track: dict = {}
_track_loaded = False
_track_saved = 0.0
_track_dirty = False


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def _track_load() -> None:
    global _track_loaded, _track
    if _track_loaded:
        return
    d = _load(CHANGES_PATH)
    _track = d if isinstance(d, dict) else {}
    _track_loaded = True


def _observe(ref: str, sig, now: float) -> float:
    """Seit wann gilt dieser Zustand? (Zeitpunkt, an dem BlueNexus ihn zuerst gesehen hat.)"""
    global _track_dirty
    with _lock:
        _track_load()
        t = _track.get(ref)
        if t is None or t.get("sig") != sig:
            t = _track[ref] = {"sig": sig, "at": now}
            _track_dirty = True
        return float(t["at"])


def _track_flush(force: bool = False) -> None:
    global _track_saved, _track_dirty
    with _lock:
        if _track_dirty and (force or time.time() - _track_saved > 5):
            try:
                _save(CHANGES_PATH, _track)
                _track_saved, _track_dirty = time.time(), False
            except OSError as e:
                log.warning("api_changes.json nicht schreibbar: %s", e)


def _sensor_item(s: dict, now: float) -> dict:
    v = s.get("value")
    ok = v is not None
    binary = bool(s.get("binary"))
    state, text = None, "kein Wert"
    if ok and binary:
        w = _SENSOR_WORDS.get(s.get("kind"), ("on", "off", "Ja", "Nein"))
        if s.get("invert"):
            w = (w[1], w[0], w[3], w[2])
        state, text = (w[0], w[2]) if v else (w[1], w[3])
        v = bool(v)
    elif ok:
        text = str(v).replace(".", ",") + (" " + s["unit"] if s.get("unit") else "")
    ref = "sensor:" + s["id"]
    it = {"ref": ref, "id": s["id"], "type": "sensor", "kind": s.get("kind") or "", "name": s.get("name") or s["id"], "room": s.get("room") or "",
          "icon": s.get("icon") or "", "online": ok, "value": v, "state": state, "text": text, "unit": s.get("unit") or "", "binary": binary,
          "source": s.get("source") or ""}
    it["changed_at"] = _iso(_observe(ref, [v, state], now))
    return it


def _device_item(d: dict, now: float) -> dict:
    online = bool(d.get("online"))
    sw = d.get("switchable") is not False
    on = bool(d.get("on")) if online else None
    ref = "device:" + d["id"]
    it = {"ref": ref, "id": d["id"], "type": "device", "kind": d.get("rkind") or d.get("kind") or "", "name": d.get("name") or d["id"], "room": d.get("room") or "",
          "icon": d.get("icon") or "", "online": online, "value": on, "state": ("on" if on else "off") if online else None,
          "text": ("an" if on else "aus") if online else "nicht erreichbar", "unit": "", "binary": True, "switchable": sw}
    if online and d.get("power") is not None:
        it["power_w"] = d["power"]
    it["changed_at"] = _iso(_observe(ref, [online, on], now))
    return it


def _virtual_item(v: dict, now: float, snap: dict) -> dict:
    sn = snap.get(v["id"], {})
    kind = v.get("kind") or "switch"
    on = bool(sn.get("on"))
    ref = "virtual:" + v["id"]
    it = {"ref": ref, "id": v["id"], "type": "virtual", "kind": kind, "name": v.get("name") or v["id"], "room": "", "icon": v.get("icon") or "", "online": True,
          "unit": "", "binary": kind != "button"}
    if kind == "button":
        it.update(value=None, state="button", text="Knopf")
        sig = [bool(sn.get("pressed"))]
    else:
        it.update(value=on, state="on" if on else "off", text=("an" if on else "aus") if kind != "timer" else ("läuft" if on else "aus"))
        sig = [on]
    if kind == "timer" and on:
        it["remaining_s"] = sn.get("remaining_s", 0)
    it["changed_at"] = _iso(_observe(ref, sig, now))
    return it


def build_items(scope: dict, types=None, refs=None, now: float | None = None) -> list:
    """Die Eintraege, die ein Schluessel (scope = {"all": bool, "items": [refs]}) sehen darf, mit aktuellem Zustand.
    types: nur diese Arten (device/sensor/virtual); refs: nur diese Verweise. Reihenfolge: Sensoren, Geraete, Schalter."""
    import homematic
    import shelly
    import virtual
    now = time.time() if now is None else now
    allow_all = bool(scope.get("all"))
    want = set(normalize_refs(scope.get("items")))
    if refs is not None:
        refs = set(refs)
    def ids(t: str):
        pre = t + ":"
        got = None if allow_all else {r[len(pre):] for r in want if r.startswith(pre)}
        if refs is not None:
            only = {r[len(pre):] for r in refs if r.startswith(pre)}
            got = only if got is None else got & only
        return got
    out = []
    if not types or "sensor" in types:
        sid = ids("sensor")
        if sid is None or sid:
            sens = [s for s in homematic.load_sensors() if sid is None or s["id"] in sid]
            vals = homematic.read_values(sens) if sens else {}
            out += [_sensor_item({**s, "value": vals.get(s["id"])}, now) for s in sens]
    if not types or "device" in types:
        did = ids("device")
        if did is None or did:
            out += [_device_item(d, now) for d in shelly.list_with_status(ids=did, live=True)]
    if not types or "virtual" in types:
        vid = ids("virtual")
        if vid is None or vid:
            snap = virtual.snapshot()
            out += [_virtual_item(v, now, snap) for v in virtual.load() if vid is None or v["id"] in vid]
    _track_flush()
    stamp = _iso(now)
    for it in out:
        it["updated_at"] = stamp
    return out


# ---------------------------------------------------------------- Hintergrundlauf fuer "changed_at"
_sampler = None


def _union_scope(keys: list) -> dict:
    if any(k.get("all") for k in keys):
        return {"all": True}
    refs = []
    for k in keys:
        refs += k.get("items") or []
    return {"items": refs}


def sample_once() -> int:
    """Alle freigegebenen Eintraege einmal lesen (haelt "changed_at" aktuell). Rueckgabe: Anzahl."""
    keys = load_keys()
    if not keys:
        return 0
    return len(build_items(_union_scope(keys)))


def start_sampler(active=lambda: True) -> None:
    """Hintergrundlauf starten (einmal). active(): False im Demo-/Testmodus - dann wird nichts gelesen."""
    global _sampler
    if _sampler is not None:
        return

    def run():
        while True:
            time.sleep(SAMPLE_S)
            try:
                if active():
                    sample_once()
            except Exception as e:                     # noqa: BLE001
                log.warning("Schnittstelle: Hintergrundlauf: %s", e)
    _sampler = threading.Thread(target=run, daemon=True, name="extapi-sampler")
    _sampler.start()
