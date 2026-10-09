"""Passwort vergessen: Einmal-Code per Telegram/Pushover und Wiederherstellungsschluessel (Anmeldeseite -> "Passwort vergessen?").

- Code (6 Ziffern, 10 Minuten, hoechstens 5 Fehlversuche, einmal verwendbar) geht nur an die SYSTEM-Empfaenger (die als Admin eingerichteten
  Telegram-/Pushover-Empfaenger) und nur fuer Konten mit vollen Administratorrechten.
- Wiederherstellungsschluessel: gehoert zu einem Konto (siehe auth.UserStore.set_recovery), einmal verwendbar, danach gibt es einen neuen.
- Codes liegen nur im Speicher (als Hash); ein Neustart der App macht offene Codes ungueltig.
"""
import hashlib
import hmac
import secrets
import threading
import time

import notify
import pushover

CODE_TTL_S = 600
MAX_TRIES = 5
SEND_WINDOW_S, SEND_LIMIT = 900, 3                         # hoechstens 3 Codes je Konto in 15 Minuten
_lock = threading.Lock()
_codes: dict = {}                                          # Konto -> {"h": Hash, "salt", "exp", "tries"}
_sends: dict = {}                                          # Konto -> [Zeiten]


def channels() -> list[dict]:
    """Nur Wege, die wirklich eingerichtet sind (mindestens ein Systemempfaenger)."""
    out = []
    try:
        if notify.configured() and any(r.get("system") for r in notify.recipients()):
            out.append({"id": "telegram", "name": "Telegram"})
    except Exception:                                      # noqa: BLE001
        pass
    try:
        if pushover.configured() and any(r.get("system") for r in pushover.recipients()):
            out.append({"id": "pushover", "name": "Pushover"})
    except Exception:                                      # noqa: BLE001
        pass
    return out


def _hash(code: str, salt: str) -> str:
    return hashlib.sha256((salt + code).encode()).hexdigest()


def may_send(user: str) -> bool:
    now = time.time()
    with _lock:
        tries = [t for t in _sends.get(user, []) if now - t < SEND_WINDOW_S]
        _sends[user] = tries
        if len(tries) >= SEND_LIMIT:
            return False
        tries.append(now)
        return True


def send_code(user: str, channel: str) -> None:
    """Erzeugt einen Code und schickt ihn an die Systemempfaenger des gewaehlten Dienstes. Wirft bei Zustellfehlern (nur zum Protokollieren)."""
    code = f"{secrets.randbelow(1000000):06d}"
    salt = secrets.token_hex(8)
    with _lock:
        _codes[user] = {"h": _hash(code, salt), "salt": salt, "exp": time.time() + CODE_TTL_S, "tries": 0}
    text = f"🔑 Dein Code zum Zurücksetzen des Passworts (Konto „{user}“): {code}\nGültig für {CODE_TTL_S // 60} Minuten. Wenn du das nicht angefordert hast, ignoriere diese Nachricht."
    if channel == "telegram":
        notify.send(text)
    elif channel == "pushover":
        pushover.send(text, title="Passwort zurücksetzen", priority=1)
    else:
        raise ValueError("unbekannter Dienst")


def check_code(user: str, code: str) -> bool:
    """True genau einmal, wenn der Code stimmt und nicht abgelaufen ist; zu viele Fehlversuche entwerten ihn."""
    with _lock:
        c = _codes.get(user)
        if not c or time.time() > c["exp"]:
            _codes.pop(user, None)
            return False
        c["tries"] += 1
        ok = hmac.compare_digest(c["h"], _hash("".join(ch for ch in str(code) if ch.isdigit()), c["salt"]))
        if ok or c["tries"] >= MAX_TRIES:
            _codes.pop(user, None)
        return ok


def clear(user: str) -> None:
    with _lock:
        _codes.pop(user, None)
