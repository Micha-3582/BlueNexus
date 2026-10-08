"""
Pushover als zweiter Meldeweg neben Telegram (https://pushover.net/api).

- Zugang: App-Token (aus dem eigenen Pushover-Konto -> "Create an Application") + je Empfaenger ein Benutzer-Schluessel ("User Key").
  Gespeichert in `pushover.json` (nicht im Repo, nie zum Browser). Jeder Empfaenger hat einen Namen und das Merkmal "system"
  (bekommt die Systemmeldungen; in Regeln waehlt man je Schritt, wer die Nachricht bekommt).
- Kann Text mit Titel, Prioritaet (-1 leise ... 2 Notfall mit Wiederholung bis zur Bestaetigung), Ton und ein Kamera-Standbild als Anhang.
- Ein Standbild wird nur EINMAL geholt und an alle gewaehlten Empfaenger geschickt.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

import requests

import opslog
import store

log = logging.getLogger("pushover")

_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_PATH = os.path.join(_DIR, "pushover.json")
API = "https://api.pushover.net/1"
TIMEOUT = 15
MAX_MESSAGE = 1024
MAX_TITLE = 250
PRIORITIES = {-1: "leise", 0: "normal", 1: "hoch (durchbricht Ruhezeiten)", 2: "Notfall (wiederholt, bis du bestätigst)"}
SOUNDS = {"": "Standard", "siren": "Sirene", "spacealarm": "Weltraumalarm", "alien": "Alien", "persistent": "Dauerton", "bugle": "Signalhorn",
          "cashregister": "Kasse", "magic": "Magic", "vibrate": "nur Vibration", "none": "lautlos"}
EMERGENCY_RETRY_S = 60            # Notfall: alle 60 s wiederholen ...
EMERGENCY_EXPIRE_S = 1800         # ... bis zu 30 Minuten

_lock = threading.Lock()


class PushoverError(Exception):
    pass


# ---------------------------------------------------------------- Zugang + Empfaenger
def load() -> dict:
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    store._dump_json(CRED_PATH, d, indent=None)


def recipients() -> list[dict]:
    out = []
    for r in load().get("recipients") or []:
        if isinstance(r, dict) and r.get("id") and r.get("user_key"):
            out.append({"id": str(r["id"]), "name": str(r.get("name") or "Empfänger"), "user_key": str(r["user_key"]), "system": bool(r.get("system")),
                        "device": str(r.get("device") or "")})
    return out


def configured() -> bool:
    c = load()
    return bool(c.get("token") and recipients())


def has_token() -> bool:
    return bool(load().get("token"))


def recipients_light() -> list[dict]:
    """Ohne Schluessel (fuer den Regel-Editor)."""
    return [{"id": r["id"], "name": r["name"], "system": r["system"]} for r in recipients()]


def credentials_public() -> dict:
    return {"has_token": has_token(), "configured": configured()}


def save_token(token: str | None) -> None:
    """Leerer Token = vorhandenen behalten."""
    c = load()
    tok = str(token or "").strip() or c.get("token", "")
    if not tok:
        raise PushoverError("Bitte den App-Token eintragen (pushover.net → Create an Application/API Token)")
    if not tok.isalnum() or len(tok) < 20:
        raise PushoverError("Der App-Token sieht ungültig aus (30 Zeichen, Buchstaben und Ziffern)")
    c["token"] = tok
    _save(c)


def clear_credentials() -> None:
    """App-Token und alle Empfaenger loeschen (Datei entfernen)."""
    try:
        os.remove(CRED_PATH)
    except FileNotFoundError:
        pass


def _validate(token: str, user_key: str, device: str = "") -> None:
    """Fragt Pushover, ob der Benutzer-Schluessel (und das Geraet) zu diesem App-Token passt (kein Versand)."""
    try:
        r = requests.post(f"{API}/users/validate.json", data={"token": token, "user": user_key, **({"device": device} if device else {})}, timeout=TIMEOUT)
        j = r.json()
    except requests.RequestException as e:
        raise PushoverError(f"Pushover nicht erreichbar: {e}")
    except ValueError:
        raise PushoverError(f"Ungültige Antwort von Pushover (HTTP {r.status_code})")
    if j.get("status") != 1:
        errs = j.get("errors") or []
        raise PushoverError("Pushover lehnt den Schlüssel ab: " + ", ".join(str(e) for e in errs) if errs else "Pushover lehnt den Schlüssel ab")


DEVICE_RE = re.compile(r"[A-Za-z0-9_-]{1,25}")


def add_recipient(name: str, user_key: str, system: bool = False, check: bool = True, device: str = "") -> dict:
    """Empfaenger = Benutzer-Schluessel, optional nur EIN Geraet dieses Kontos (Name wie in Pushover unter "Your Devices").
    Derselbe Schluessel darf mehrfach vorkommen, wenn die Geraete verschieden sind (z. B. zwei Handys im selben Konto)."""
    c = load()
    if not c.get("token"):
        raise PushoverError("Bitte zuerst den App-Token speichern")
    name, key = str(name or "").strip()[:40], str(user_key or "").strip()
    device = str(device or "").strip()
    if device and not DEVICE_RE.fullmatch(device):
        raise PushoverError("Gerätename: nur Buchstaben, Ziffern, _ und -, höchstens 25 Zeichen – genau so, wie er in Pushover unter „Your Devices“ steht")
    if not name:
        raise PushoverError("Bitte einen Namen eingeben")
    if not key.isalnum() or len(key) < 20:
        raise PushoverError("Der Benutzer-Schlüssel sieht ungültig aus (30 Zeichen, steht oben in der Pushover-App bzw. auf pushover.net)")
    if any(r["user_key"] == key and r["device"] == device for r in recipients()):
        raise PushoverError("Dieser Schlüssel" + (" mit diesem Gerät" if device else " (alle Geräte)") + " ist schon als Empfänger eingetragen")
    if check:
        _validate(c["token"], key, device)
    items = list(c.get("recipients") or [])
    n = 1 + max([int(str(r["id"])[1:]) for r in items if str(r.get("id", "")).startswith("p") and str(r["id"])[1:].isdigit()] or [0])
    rec = {"id": f"p{n}", "name": name, "user_key": key, "system": bool(system) or not items, **({"device": device} if device else {})}       # der erste Empfaenger bekommt immer die Systemmeldungen
    items.append(rec)
    c["recipients"] = items
    _save(c)
    return {k: v for k, v in rec.items() if k != "user_key"}


def update_recipient(rid: str, name=None, system=None) -> bool:
    c = load()
    items = list(c.get("recipients") or [])
    for r in items:
        if r.get("id") == rid:
            if name is not None:
                nm = str(name).strip()[:40]
                if not nm:
                    raise PushoverError("Name darf nicht leer sein")
                r["name"] = nm
            if system is not None:
                r["system"] = bool(system)
            c["recipients"] = items
            _save(c)
            return True
    return False


def remove_recipient(rid: str) -> bool:
    c = load()
    items = [r for r in (c.get("recipients") or []) if r.get("id") != rid]
    if len(items) == len(c.get("recipients") or []):
        return False
    c["recipients"] = items
    _save(c)
    return True


def _targets(to=None) -> list[dict]:
    recs = recipients()
    if to:
        ids = {str(i) for i in to}
        sel = [r for r in recs if r["id"] in ids]
        if sel:
            return sel
    return [r for r in recs if r["system"]]


def names(to=None) -> str:
    return ", ".join(r["name"] for r in _targets(to))


# ---------------------------------------------------------------- Senden
def send(text: str, title: str | None = None, priority: int = 0, sound: str | None = None, jpeg: bytes | None = None, to=None, only: str | None = None) -> None:
    """Nachricht an die gewaehlten Empfaenger (ohne Angabe: Systemempfaenger). Scheitert einer, laufen die anderen trotzdem durch."""
    c = load()
    token = c.get("token")
    targets = [r for r in recipients() if r["id"] == only] if only else _targets(to)
    if not (token and targets):
        raise PushoverError("Pushover ist noch nicht eingerichtet")
    data = {"token": token, "message": str(text)[:MAX_MESSAGE], "priority": int(priority)}
    if title:
        data["title"] = str(title)[:MAX_TITLE]
    if sound and sound in SOUNDS:
        data["sound"] = sound
    if int(priority) == 2:
        data.update(retry=EMERGENCY_RETRY_S, expire=EMERGENCY_EXPIRE_S)
    errs = []
    for r in targets:
        try:
            files = {"attachment": ("standbild.jpg", jpeg, "image/jpeg")} if jpeg else None
            resp = requests.post(f"{API}/messages.json", data={**data, "user": r["user_key"], **({"device": r["device"]} if r["device"] else {})},
                                 files=files, timeout=30 if jpeg else TIMEOUT)
            j = resp.json()
        except requests.RequestException as e:
            errs.append(f"{r['name']}: Pushover nicht erreichbar ({e})")
            continue
        except ValueError:
            errs.append(f"{r['name']}: ungültige Antwort (HTTP {resp.status_code})")
            continue
        if j.get("status") != 1:
            errs.append(f"{r['name']}: " + (", ".join(str(e) for e in (j.get("errors") or [])) or f"HTTP {resp.status_code}"))
    if errs:
        raise PushoverError("; ".join(errs))


def _async(fn, what: str) -> None:
    def run():
        try:
            fn()
            opslog.count("notify_sent")
            opslog.log("notify", ("Pushover: " + what)[:200])
        except Exception as e:                              # noqa: BLE001
            log.warning("Pushover nicht gesendet: %s", e)
            opslog.log("notify_fail", f"Pushover: {e} | {what[:100]}")
    threading.Thread(target=run, daemon=True).start()


def message(text: str, cfg: dict | None = None, title: str | None = None, priority: int = 0, sound: str | None = None, to=None,
            get_jpeg=None) -> bool:
    """Nachricht aus einer Regel (Schritt "Pushover"); optional mit Kamera-Standbild (`get_jpeg()` holt es im Hintergrund, einmal fuer alle)."""
    if not configured():
        return False

    def go():
        jpeg, last = None, None
        if get_jpeg:
            for attempt in (1, 2):                          # Kamera antwortet sporadisch nicht: einmal nochmal versuchen
                try:
                    jpeg = get_jpeg()
                    break
                except Exception as e:                      # noqa: BLE001
                    last = e
                    if attempt == 1:
                        time.sleep(1.5)
            if jpeg is None:
                log.warning("Pushover: Standbild nicht verfuegbar (%s) - Text wird ohne Bild gesendet", last)
        send(text, title=title, priority=priority, sound=sound, jpeg=jpeg, to=to)
    _async(go, text)
    return True


def system(text: str) -> None:
    """Systemmeldung (Fehler, Tagesbilanz ...) an die Systemempfaenger - ruft notify.py zusammen mit Telegram auf."""
    if configured():
        _async(lambda: send(text), text)
