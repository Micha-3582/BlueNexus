"""
Telegram-Befehle: Triggerworte, die jemand dem Bot schreibt, loesen Regeln aus (z. B. "Tor" oeffnet das Schiebetor).

- Der Bot fragt bei Telegram per Long-Poll nach neuen Nachrichten (getUpdates) - es muss nichts von aussen erreichbar sein.
- Nur FREIGEGEBENE Chats werden bedient: das sind die Empfaenger unter Einstellungen -> Meldungen (Chat-ID einmalig eintragen). Wer dem Bot
  zum ersten Mal schreibt, landet als "Anfrage" in einer Liste; der Administrator gibt ihn mit einem Klick frei (oder lehnt ab). Fremde bekommen
  nur einmal eine Antwort, dass sie noch nicht freigegeben sind - sonst nichts, und es wird nichts ausgeloest.
- Welche Woerter es gibt, bestimmen die Regeln: Bedingung "Telegram-Wort" (nur bei Regeln der Art Ablauf), wahlweise nur fuer bestimmte Empfaenger
  und wahlweise mit Rueckfrage ("wirklich? Antworte mit ja"). Die Aktionen sind dieselben wie bei jeder Regel.
- Sicherheit: Nachrichten, die aelter als MAX_AGE_S sind (z. B. nach einem Neustart oder Netzausfall liegengeblieben), werden verworfen - ein altes
  "Tor" darf nie spaeter ein Tor oeffnen. Jede Auslösung, jede Rueckfrage und jede Anfrage steht im Logbuch (nur fuer Administratoren sichtbar).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

import requests

import notify
import store

log = logging.getLogger("telegram_in")

_DIR = os.path.dirname(os.path.abspath(__file__))
REQUESTS_PATH = os.path.join(_DIR, "telegram_requests.json")
API = notify.API
POLL_S = 20                       # Long-Poll-Dauer bei Telegram
MAX_AGE_S = 90                    # aeltere Nachrichten werden nicht mehr ausgefuehrt
CONFIRM_S = 60                    # so lange gilt eine Rueckfrage ("ja")
UNKNOWN_REPLY_S = 6 * 3600        # einem unbekannten Chat nur so oft antworten
MAX_REQUESTS = 30
YES = ("ja", "j", "yes", "y")
NO = ("nein", "n", "no", "abbrechen", "stop")
HELP = ("hilfe", "help", "start", "?")

_lock = threading.RLock()
_events: list[dict] = []                      # frisch ausgeloeste Woerter, bis die Regelschleife sie gesehen hat
_seq = 0
_pending: dict[str, tuple] = {}               # Chat-ID -> (Wort, Zeit) einer offenen Rueckfrage
_replied: dict[str, float] = {}
_hooks = {"words": lambda: [], "wake": lambda: None, "enabled": lambda: True}
_thread: threading.Thread | None = None
_stop = threading.Event()
_polling = False                              # True, solange der Poller laeuft (dann liest "Chat ermitteln" aus der Anfrageliste)


def norm(text) -> str:
    """Vergleichsform eines Befehlswortes: ohne fuehrendes /, ohne @Botname, Leerzeichen vereinheitlicht. Gross-/Kleinschreibung bleibt: "Bing" ist nicht "bing"."""
    t = str(text or "").strip()
    if t.startswith("/"):
        t = t[1:]
    first, _, rest = t.partition(" ")
    if "@" in first:
        first = first.split("@")[0]
    return " ".join((first + " " + rest).split())


# ---------------------------------------------------------------- Anfragen (noch nicht freigegebene Chats)
def _load_requests() -> dict:
    d = store._load_json_recovering(REQUESTS_PATH, lambda: {})
    return d if isinstance(d, dict) else {}


def requests_list() -> list[dict]:
    """Chats, die dem Bot geschrieben haben, aber noch kein Empfaenger sind (neueste zuerst)."""
    known = {r["chat_id"] for r in notify.recipients()}
    items = [v for k, v in _load_requests().items() if k not in known and isinstance(v, dict)]
    return sorted(items, key=lambda v: v.get("last", 0), reverse=True)


def reject_request(chat_id) -> bool:
    with _lock:
        d = _load_requests()
        if str(chat_id) not in d:
            return False
        d.pop(str(chat_id))
        store._dump_json(REQUESTS_PATH, d, indent=None)
        return True


def _note_request(chat: dict, name: str, text: str) -> None:
    cid = str(chat["id"])
    with _lock:
        d = _load_requests()
        v = d.get(cid) or {"id": chat["id"], "first": time.time(), "count": 0}
        v.update({"name": name, "type": chat.get("type", ""), "last": time.time(), "text": str(text or "")[:60], "count": int(v.get("count", 0)) + 1})
        d[cid] = v
        if len(d) > MAX_REQUESTS:                                      # aelteste verwerfen
            for k in sorted(d, key=lambda k: d[k].get("last", 0))[: len(d) - MAX_REQUESTS]:
                d.pop(k)
        store._dump_json(REQUESTS_PATH, d, indent=None)


# ---------------------------------------------------------------- Ereignisse fuer die Regelschleife
def snapshot() -> list[dict]:
    with _lock:
        return [dict(e) for e in _events]


def max_seq() -> int:
    with _lock:
        return _seq


def consume(upto: int) -> None:
    """Die Regelschleife hat die Ereignisse bis einschliesslich `upto` gesehen."""
    with _lock:
        _events[:] = [e for e in _events if e["seq"] > upto]


def _fire(rec: dict, word: str) -> None:
    global _seq
    with _lock:
        _seq += 1
        _events.append({"seq": _seq, "word": word, "rid": rec["id"], "name": rec["name"], "ts": time.time()})
    _hooks["wake"]()


# ---------------------------------------------------------------- Nachrichten verarbeiten
def _log(text: str) -> None:
    try:
        import opslog
        opslog.log("telegram", text, dry=False)
    except Exception:                                                  # noqa: BLE001
        pass
    log.info(text)


def _reply(token: str, chat_id, text: str) -> None:
    try:
        notify._api(token, "sendMessage", {"chat_id": chat_id, "text": text, "disable_web_page_preview": True})
    except notify.NotifyError as e:
        log.warning("Antwort an %s nicht gesendet: %s", chat_id, e)


DEFAULT_REPLY = "✓ „{wort}“ wird ausgelöst."
NO_REPLY = "-"                                  # als Antworttext eingetragen: der Bot antwortet nicht


def _answer(token: str, chat_id, entries: list, word: str, rec: dict) -> None:
    """Antwort nach dem Ausloesen: der in der Regel eingestellte Text ({wort}, {name} werden ersetzt), sonst der Standardtext; "-" = keine Antwort."""
    e = next((x for x in entries if x["word"] == word and (x.get("reply") or "").strip()), None)
    text = (e or {}).get("reply") or DEFAULT_REPLY
    if text.strip() == NO_REPLY:
        return
    shown = next((x["shown"] for x in entries if x["word"] == word), word)
    _reply(token, chat_id, text.replace("{wort}", shown).replace("{name}", rec["name"]))


def _sender(msg: dict) -> str:
    chat = msg.get("chat") or {}
    fr = msg.get("from") or {}
    return (chat.get("title") or " ".join(x for x in (fr.get("first_name"), fr.get("last_name")) if x) or fr.get("username")
            or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or str(chat.get("id")))


def handle_message(token: str, msg: dict, now: float | None = None) -> None:
    now = now or time.time()
    chat = msg.get("chat") or {}
    text = msg.get("text")
    if "id" not in chat or not isinstance(text, str):
        return
    if now - float(msg.get("date") or now) > MAX_AGE_S:
        _log(f"Telegram: veraltete Nachricht von „{_sender(msg)}“ verworfen (älter als {MAX_AGE_S} s)")
        return
    cid = str(chat["id"])
    rec = next((r for r in notify.recipients() if r["chat_id"] == cid), None)
    word = norm(text)
    if rec is None:                                                    # nicht freigegeben: nur als Anfrage vermerken
        name = _sender(msg)
        _note_request(chat, name, text)
        _log(f"Telegram: Anfrage von noch nicht freigegebenem Chat „{name}“ (ID {cid}) – unter Einstellungen → Meldungen freigeben oder ablehnen")
        if now - _replied.get(cid, 0) > UNKNOWN_REPLY_S:
            _replied[cid] = now
            _reply(token, cid, "Hallo! Dein Chat ist noch nicht freigegeben. Der Administrator sieht deine Anfrage in BlueNexus und kann dich freischalten.")
        return
    entries = [e for e in _hooks["words"]() if not e["who"] or rec["id"] in e["who"]]
    shown = sorted({e["shown"] for e in entries})
    lw = word.lower()                                                  # nur die festen Bot-Befehle (hilfe, ja, nein) sind unabhaengig von der Schreibweise
    if lw in HELP:
        _reply(token, cid, ("Du kannst mir schreiben: " + ", ".join(f"„{w}“" for w in shown)) if shown else "Für dich ist hier noch kein Befehl eingerichtet.")
        return
    p = _pending.get(cid)
    if p and now - p[1] < CONFIRM_S:
        if lw in YES:
            _pending.pop(cid, None)
            _fire(rec, p[0])
            _log(f"Telegram: „{p[0]}“ von {rec['name']} bestätigt und ausgelöst")
            _answer(token, cid, entries, p[0], rec)
            return
        _pending.pop(cid, None)
        if lw in NO:
            _reply(token, cid, "Abgebrochen.")
            return
    match = [e for e in entries if e["word"] == word]
    if not match:
        _log(f"Telegram: unbekanntes Wort „{str(text)[:40]}“ von {rec['name']}")
        _reply(token, cid, "Das kenne ich nicht. Schreib „hilfe“, dann nenne ich dir die möglichen Wörter." if shown else "Für dich ist hier noch kein Befehl eingerichtet.")
        return
    if any(e["confirm"] for e in match):
        _pending[cid] = (word, now)
        _log(f"Telegram: „{word}“ von {rec['name']} – Rückfrage gestellt")
        _reply(token, cid, f"„{word}“ wirklich auslösen? Antworte innerhalb einer Minute mit „ja“.")
        return
    _fire(rec, word)
    _log(f"Telegram: „{word}“ von {rec['name']} ausgelöst")
    _answer(token, cid, entries, word, rec)


# ---------------------------------------------------------------- Long-Poll-Schleife
def _poll(token: str, offset) -> list[dict]:
    payload = {"timeout": POLL_S, "allowed_updates": ["message", "channel_post"]}
    if offset is not None:
        payload["offset"] = offset
    r = requests.post(f"{API}/bot{token}/getUpdates", json=payload, timeout=POLL_S + 15)
    if r.status_code == 409:
        raise notify.NotifyError("409")                                # ein anderer Abruf (zweiter Server mit demselben Bot?)
    try:
        j = r.json()
    except ValueError:
        raise notify.NotifyError(f"Ungültige Antwort (HTTP {r.status_code})")
    if not j.get("ok"):
        raise notify.NotifyError(j.get("description") or f"HTTP {r.status_code}")
    return j.get("result") or []


def _loop():
    global _polling
    offset, wait = None, 0
    while not _stop.is_set():
        token = (notify.load_credentials().get("token") or "").strip()
        if not token or not _hooks["enabled"]():
            _polling = False
            offset = None
            _stop.wait(15)
            continue
        _polling = True
        try:
            for u in _poll(token, offset):
                offset = int(u["update_id"]) + 1
                msg = u.get("message") or u.get("channel_post")
                if msg:
                    try:
                        handle_message(token, msg)
                    except Exception as e:                             # noqa: BLE001 - eine kaputte Nachricht darf den Abruf nicht beenden
                        log.warning("Telegram-Nachricht nicht verarbeitet: %s", e)
            wait = 0
        except notify.NotifyError as e:
            wait = 60 if str(e) == "409" else min(60, (wait or 5) * 2)
            if str(e) == "409":
                log.warning("Telegram: ein anderer Abruf läuft mit diesem Bot (zweiter Server?) – Befehle pausieren kurz")
            else:
                log.info("Telegram-Abruf: %s", e)
            _stop.wait(wait)
        except requests.RequestException as e:
            wait = min(60, (wait or 5) * 2)
            log.info("Telegram nicht erreichbar: %s", e.__class__.__name__)
            _stop.wait(wait)
    _polling = False


def start(words_cb, wake_cb, enabled_cb=None) -> None:
    """words_cb() -> [{word (normalisiert), shown, who [Empfaenger-IDs, leer = alle], confirm}]; wake_cb(): Regelschleife wecken."""
    global _thread
    _hooks.update(words=words_cb, wake=wake_cb, enabled=enabled_cb or (lambda: True))
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="telegram-in", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def active() -> bool:
    return _polling
