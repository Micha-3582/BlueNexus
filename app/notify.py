"""
Benachrichtigungen aufs Handy per Telegram-Bot.

Zugang (Bot-Token + Chat-ID) liegt in `telegram.json` (nicht im Repo, Token geht nie zum Browser). Ereignisse werden nur
bei einem WECHSEL gemeldet (Problem beginnt / Problem behoben) und nicht bei jedem Durchlauf; der Zustand steht in
`notify_state.json`, damit ein Neustart nicht dieselbe Meldung nochmal ausloest. Jede Meldung beginnt mit dem Anlagennamen,
damit man mehrere Anlagen (z. B. Original und Fork) im selben Chat auseinanderhalten kann.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime

import requests

import opslog
import pushover
import store

log = logging.getLogger("notify")

_DIR = os.path.dirname(os.path.abspath(__file__))
CRED_PATH = os.path.join(_DIR, "telegram.json")
STATE_PATH = os.path.join(_DIR, "notify_state.json")
API = "https://api.telegram.org"
TIMEOUT = 10

# key -> (Beschriftung, Standard an?)
EVENTS = {
    "tick_error": ("Steuerung meldet einen Fehler (z. B. Cerbo oder Tibber nicht erreichbar)", True),
    "tibber": ("Tibber-Preise fehlen (Notlauf mit gespeicherten Preisen / Netzladen gestoppt)", True),
    "vrm": ("VRM-Prognose nicht verfügbar", True),
    "watchdog": ("Batterie-Watchdog schlägt an (Batterie reagiert nicht)", True),
    "alarms": ("Multiplus/Batterie meldet einen Alarm (Übertemperatur, Überlast, Zellen-Ungleichgewicht, ...)", True),
    "low_soc": ("Akkustand niedrig", True),
    "surplus": ("Überschuss-Automatik schaltet ein Gerät (auch im Trockenlauf)", False),
    "rules": ("Regeln schalten ein Gerät (auch im Trockenlauf)", False),
    "summary": ("Tages-Zusammenfassung am Abend", False),
    "startup": ("App wurde gestartet / neu gestartet", False),
}
DEFAULT_LOW_SOC = 15
DEFAULT_SUMMARY_HOUR = 21

_lock = threading.Lock()


class NotifyError(Exception):
    pass


# ---------------------------------------------------------------- Zugang
def load_credentials() -> dict:
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def configured() -> bool:
    c = load_credentials()
    return bool(c.get("token") and c.get("chat_id"))


def any_configured() -> bool:
    """Telegram ODER Pushover eingerichtet (Systemmeldungen gehen an beide)."""
    return configured() or pushover.configured()


def save_credentials(token: str | None, chat_id) -> None:
    """Leerer Token = vorhandenen behalten."""
    c = load_credentials()
    tok = str(token or "").strip() or c.get("token", "")
    cid = str(chat_id or "").strip()
    if not tok:
        raise NotifyError("Bitte den Bot-Token eintragen")
    if not cid.lstrip("-").isdigit():
        raise NotifyError("Die Chat-ID besteht nur aus Ziffern (ggf. mit Minus bei Gruppen) – „Chat-ID ermitteln“ hilft")
    store._dump_json(CRED_PATH, {**c, "token": tok, "chat_id": cid}, indent=None)       # weitere Empfaenger bleiben erhalten


def clear_credentials() -> None:
    """Bot-Token, Chat-ID und alle weiteren Empfaenger loeschen (Datei entfernen). Danach sendet die App nichts mehr."""
    try:
        os.remove(CRED_PATH)
    except FileNotFoundError:
        pass


def credentials_public() -> dict:
    c = load_credentials()
    return {"configured": bool(c.get("token") and c.get("chat_id")), "has_token": bool(c.get("token")),
            "chat_id": c.get("chat_id", "")}


# ---------------------------------------------------------------- Empfaenger
# Ein Bot, mehrere Empfaenger: der erste ("main") ist die Chat-ID oben, weitere stehen unter "extra". Jeder Empfaenger hat einen Namen und
# das Merkmal "system" (bekommt Systemmeldungen und Regel-Schritte, bei denen keine Empfaenger gewaehlt sind). In Regeln waehlt man je
# Schritt, wer die Nachricht bzw. das Foto bekommt - das Foto wird nur EINMAL gemacht und an alle gewaehlten verschickt.
def recipients() -> list[dict]:
    c = load_credentials()
    out = []
    if c.get("chat_id"):
        out.append({"id": "main", "name": c.get("primary_name") or "Ich", "chat_id": str(c["chat_id"]), "system": True})
    for r in c.get("extra") or []:
        if isinstance(r, dict) and r.get("id") and r.get("chat_id"):
            out.append({"id": str(r["id"]), "name": str(r.get("name") or "Empfänger"), "chat_id": str(r["chat_id"]), "system": bool(r.get("system"))})
    return out


def recipients_light() -> list[dict]:
    """Ohne Chat-IDs (fuer den Regel-Editor)."""
    return [{"id": r["id"], "name": r["name"], "system": r["system"]} for r in recipients()]


def _targets(to=None) -> list[dict]:
    recs = recipients()
    if to:
        ids = {str(i) for i in to}
        sel = [r for r in recs if r["id"] in ids]
        if sel:
            return sel
    return [r for r in recs if r["system"]]               # nichts (mehr) gewaehlt oder Empfaenger entfernt -> Standard


def names(to=None) -> str:
    return ", ".join(r["name"] for r in _targets(to))


def _save_extra(c: dict, extra: list[dict]) -> None:
    c = dict(c)
    c["extra"] = extra
    store._dump_json(CRED_PATH, c, indent=None)


def add_recipient(name: str, chat_id, system: bool = False) -> dict:
    c = load_credentials()
    if not c.get("token"):
        raise NotifyError("Bitte zuerst den Bot-Token eintragen und speichern")
    name, cid = str(name or "").strip()[:40], str(chat_id or "").strip()
    if not name:
        raise NotifyError("Bitte einen Namen eingeben")
    if not cid.lstrip("-").isdigit():
        raise NotifyError("Die Chat-ID besteht nur aus Ziffern (ggf. mit Minus bei Gruppen) – „Chat ermitteln“ hilft")
    if any(r["chat_id"] == cid for r in recipients()):
        raise NotifyError("Dieser Chat ist schon als Empfänger eingetragen")
    extra = list(c.get("extra") or [])
    n = 1 + max([int(str(r["id"])[1:]) for r in extra if str(r.get("id", "")).startswith("r") and str(r["id"])[1:].isdigit()] or [0])
    rec = {"id": f"r{n}", "name": name, "chat_id": cid, "system": bool(system)}
    extra.append(rec)
    _save_extra(c, extra)
    return rec


def update_recipient(rid: str, name=None, system=None) -> bool:
    c = load_credentials()
    if rid == "main":
        if name is not None:
            nm = str(name).strip()[:40]
            if not nm:
                raise NotifyError("Name darf nicht leer sein")
            c["primary_name"] = nm
            store._dump_json(CRED_PATH, c, indent=None)
        return True
    extra = list(c.get("extra") or [])
    for r in extra:
        if r.get("id") == rid:
            if name is not None:
                nm = str(name).strip()[:40]
                if not nm:
                    raise NotifyError("Name darf nicht leer sein")
                r["name"] = nm
            if system is not None:
                r["system"] = bool(system)
            _save_extra(c, extra)
            return True
    return False


def remove_recipient(rid: str) -> bool:
    if rid == "main":
        raise NotifyError("Der erste Empfänger (Chat-ID oben) lässt sich nicht entfernen – ändere stattdessen die Chat-ID")
    c = load_credentials()
    extra = [r for r in (c.get("extra") or []) if r.get("id") != rid]
    if len(extra) == len(c.get("extra") or []):
        return False
    _save_extra(c, extra)
    return True


# ---------------------------------------------------------------- Telegram-Aufrufe
def _api(token: str, method: str, payload: dict | None = None) -> dict:
    try:
        r = requests.post(f"{API}/bot{token}/{method}", json=payload or {}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise NotifyError(f"Telegram nicht erreichbar: {e}")
    try:
        j = r.json()
    except ValueError:
        raise NotifyError(f"Ungültige Antwort von Telegram (HTTP {r.status_code})")
    if not j.get("ok"):
        desc = j.get("description") or f"HTTP {r.status_code}"
        if r.status_code == 401:
            desc = "Bot-Token wird von Telegram abgelehnt"
        raise NotifyError(desc)
    return j


def _each(chat_id, to, one):
    """`one(chat_id)` fuer einen bestimmten Chat oder fuer alle gewaehlten Empfaenger; scheitert einer, laufen die anderen trotzdem durch."""
    if chat_id:
        one(chat_id)
        return
    errs = []
    for r in _targets(to):
        try:
            one(r["chat_id"])
        except NotifyError as e:
            errs.append(f"{r['name']}: {e}")
    if errs:
        raise NotifyError("; ".join(errs))


def send(text: str, token: str | None = None, chat_id=None, to=None) -> None:
    c = load_credentials()
    token = token or c.get("token")
    if not (token and (chat_id or recipients())):
        raise NotifyError("Telegram ist noch nicht eingerichtet")
    _each(chat_id, to, lambda cid: _api(token, "sendMessage", {"chat_id": cid, "text": text, "disable_web_page_preview": True}))


def send_photo(jpeg: bytes, caption: str = "", token: str | None = None, chat_id=None, to=None) -> None:
    c = load_credentials()
    token = token or c.get("token")
    if not (token and (chat_id or recipients())):
        raise NotifyError("Telegram ist noch nicht eingerichtet")

    def one(cid):
        try:
            r = requests.post(f"{API}/bot{token}/sendPhoto", data={"chat_id": cid, "caption": caption[:1000]},
                              files={"photo": ("standbild.jpg", jpeg, "image/jpeg")}, timeout=30)
            j = r.json()
        except requests.RequestException as e:
            raise NotifyError(f"Telegram nicht erreichbar: {e}")
        except ValueError:
            raise NotifyError(f"Ungültige Antwort von Telegram (HTTP {r.status_code})")
        if not j.get("ok"):
            raise NotifyError(j.get("description") or f"HTTP {r.status_code}")
    _each(chat_id, to, one)


def send_video(path: str, caption: str = "", token: str | None = None, chat_id=None, to=None) -> None:
    c = load_credentials()
    token = token or c.get("token")
    if not (token and (chat_id or recipients())):
        raise NotifyError("Telegram ist noch nicht eingerichtet")

    def one(cid):
        try:
            with open(path, "rb") as f:
                r = requests.post(f"{API}/bot{token}/sendVideo", data={"chat_id": cid, "caption": caption[:1000], "supports_streaming": "true"},
                                  files={"video": ("ereignis.mp4", f, "video/mp4")}, timeout=180)
            j = r.json()
        except requests.RequestException as e:
            raise NotifyError(f"Telegram nicht erreichbar: {e}")
        except ValueError:
            raise NotifyError(f"Ungültige Antwort von Telegram (HTTP {r.status_code})")
        if not j.get("ok"):
            raise NotifyError(j.get("description") or f"HTTP {r.status_code}")
    _each(chat_id, to, one)


def detect_chats(token: str | None = None) -> list[dict]:
    """Chats, die dem Bot zuletzt geschrieben haben (nach einer Nachricht an den Bot)."""
    token = (token or load_credentials().get("token") or "").strip()
    if not token:
        raise NotifyError("Bitte zuerst den Bot-Token eintragen")
    import notify_in
    if notify_in.active():                                    # der Hintergrund-Abruf laeuft schon und merkt sich neue Chats als Anfragen
        return [{"id": v["id"], "name": v.get("name") or str(v["id"]), "type": v.get("type", "")} for v in notify_in.requests_list()]
    j = _api(token, "getUpdates", {"limit": 50})
    seen: dict = {}
    for u in j.get("result", []):
        m = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
        chat = m.get("chat") or {}
        if "id" in chat:
            name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username") or str(chat["id"])
            seen[chat["id"]] = {"id": chat["id"], "name": name, "type": chat.get("type", "")}
    return list(seen.values())


# ---------------------------------------------------------------- Zustand
def _state() -> dict:
    d = store._load_json_recovering(STATE_PATH, lambda: {"events": {}})
    if not isinstance(d, dict):
        d = {"events": {}}
    d.setdefault("events", {})
    return d


def enabled(key: str, cfg: dict | None = None) -> bool:
    cfg = cfg if cfg is not None else store.load_config()
    flags = cfg.get("notify_events") or {}
    return bool(flags.get(key, EVENTS[key][1]))


ENERGY_EVENTS = ("tick_error", "tibber", "vrm", "watchdog", "alarms", "low_soc", "surplus", "summary")      # nur mit Modul Energie sinnvoll


# Von sich aus gesprochene Antworten des Telegram-Bots (siehe notify_in.py) - jede einzeln abschaltbar; die Bestaetigung nach dem Ausloesen stellt die Regel selbst ein
BOT_REPLIES = {"help": "tg_reply_help", "unknown": "tg_reply_unknown", "stranger": "tg_reply_stranger"}
BOT_TEXTS = {"unknown": "tg_text_unknown", "stranger": "tg_text_stranger"}          # frei einstellbare Texte (leer = Standardtext, siehe notify_in.DEFAULT_TEXT)


def settings_public(cfg: dict) -> dict:
    energy, smart = store.module_on("energy", cfg), store.module_on("smarthome", cfg)
    shown = lambda k: (energy or k not in ENERGY_EVENTS) and (smart or k not in ("rules", "surplus"))        # Regeln/Ueberschuss schalten Geraete (Smart Home)  # noqa: E731
    return {"events": [{"key": k, "label": lab, "enabled": enabled(k, cfg), "default": dflt} for k, (lab, dflt) in EVENTS.items() if shown(k)],
            "prefix": bool(cfg.get("notify_prefix", True)),
            "low_soc": int(cfg.get("notify_low_soc", DEFAULT_LOW_SOC)),
            "summary_hour": int(cfg.get("notify_summary_hour", DEFAULT_SUMMARY_HOUR)),
            "bot": {k: bool(cfg.get(ck, True)) for k, ck in BOT_REPLIES.items()},
            "bot_text": {k: str(cfg.get(ck) or "") for k, ck in BOT_TEXTS.items()}}


def validate_settings(body: dict) -> dict:
    out = {}
    if "events" in body:
        if not isinstance(body["events"], dict):
            raise NotifyError("Ungültige Ereignisliste")
        out["notify_events"] = {k: bool(v) for k, v in body["events"].items() if k in EVENTS}
    if "prefix" in body:
        out["notify_prefix"] = bool(body["prefix"])
    if "bot_text" in body:
        if not isinstance(body["bot_text"], dict):
            raise NotifyError("Ungültiger Antworttext")
        for k, v in body["bot_text"].items():
            if k in BOT_TEXTS:
                out[BOT_TEXTS[k]] = str(v or "").strip()[:200]
    if "bot" in body:
        if not isinstance(body["bot"], dict):
            raise NotifyError("Ungültige Bot-Einstellung")
        for k, v in body["bot"].items():
            if k in BOT_REPLIES:
                out[BOT_REPLIES[k]] = bool(v)
    for key, cfgkey, lo, hi in (("low_soc", "notify_low_soc", 3, 60), ("summary_hour", "notify_summary_hour", 0, 23)):
        if key in body:
            try:
                v = int(body[key])
            except (TypeError, ValueError):
                raise NotifyError(f"{key}: keine ganze Zahl")
            if not lo <= v <= hi:
                raise NotifyError(f"{key}: erlaubt sind {lo} bis {hi}")
            out[cfgkey] = v
    return out


def _prefix(cfg: dict) -> str:
    """[Anlagenname] vor jeder Meldung - abschaltbar (Einstellung notify_prefix, Standard: an)."""
    if not cfg.get("notify_prefix", True):
        return ""
    return f"[{store.default_app_name(cfg)}] "


def _send_async(text: str, to=None, system: bool = False):
    """Telegram im Hintergrund senden; Systemmeldungen (system=True) gehen zusaetzlich an die Pushover-Systemempfaenger."""
    def run():
        if not configured():
            return
        try:
            send(text, to=to)
            opslog.count("notify_sent")
            opslog.log("notify", text[:200])
        except Exception as e:                              # noqa: BLE001
            log.warning("Telegram-Meldung nicht gesendet: %s", e)
            opslog.log("notify_fail", f"{e} | {text[:120]}")
    threading.Thread(target=run, daemon=True).start()
    if system:
        pushover.system(text)


def push(key: str, text: str, cfg: dict | None = None) -> bool:
    """Einmalige Meldung (kein Zustand). True, wenn sie abgeschickt wurde."""
    cfg = cfg if cfg is not None else store.load_config()
    if not (any_configured() and enabled(key, cfg)):
        return False
    _send_async(_prefix(cfg) + text, system=True)
    return True


def message(text: str, cfg: dict | None = None, to=None) -> bool:
    """Freie Nachricht aus einer Regel (Aktion „Nachricht senden“): geht immer raus, sobald Telegram eingerichtet ist. `to` = Empfaenger-IDs (leer: Standard)."""
    cfg = cfg if cfg is not None else store.load_config()
    if not configured():
        return False
    _send_async(_prefix(cfg) + text, to)
    return True


def photo(get_jpeg, caption: str, cfg: dict | None = None, to=None) -> bool:
    """Standbild aus einer Regel (Aktion „Kamera-Standbild senden“): `get_jpeg()` holt das Bild im Hintergrund (Kamera kann traege sein)."""
    cfg = cfg if cfg is not None else store.load_config()
    if not configured():
        return False

    def run():
        try:
            jpeg, last = None, None
            for attempt in (1, 2):                                            # Kamera antwortet sporadisch nicht: einmal nochmal versuchen
                try:
                    jpeg = get_jpeg()
                    break
                except Exception as e:                                        # noqa: BLE001
                    last = e
                    if attempt == 1:
                        time.sleep(1.5)
            if jpeg is None:
                raise last
            send_photo(jpeg, _prefix(cfg) + caption, to=to)                   # ein Bild fuer alle gewaehlten Empfaenger
            opslog.count("notify_sent")
            opslog.log("notify", ("Standbild: " + caption)[:200])
        except Exception as e:                              # noqa: BLE001
            log.warning("Telegram-Standbild nicht gesendet: %s", e)
            opslog.log("notify_fail", f"{e} | Standbild {caption[:100]}")
    threading.Thread(target=run, daemon=True).start()
    return True


_video_sem = threading.Semaphore(1)             # Download + Verkleinern immer nur eins nach dem anderen (schont Kamera, Netz und Rechner)
_video_sent: dict = {}                          # (Kamera, Aufnahme, Empfaenger) -> Zeit: dieselbe Aufnahme wird nie doppelt gesendet
VIDEO_WAIT_S, VIDEO_POLL_S, VIDEO_SETTLE_S, VIDEO_PRE_S, VIDEO_LEN_S = 240, 10, 8, 3, 10


def video(cam: dict, wanted, caption: str, cfg: dict | None = None, to=None) -> bool:
    """Video zum Ereignis aus einer Regel: wartet (im Hintergrund) auf die fertige Aufnahme auf der SD-Karte der Kamera, sucht sie anhand der Ereignisart
    (wanted = {'animal', ...}, leer = jede), schneidet 10 s (ab 3 s vor dem Ausloesen) in 720p heraus und sendet sie per Telegram."""
    import camera
    import tempfile
    from datetime import datetime, timedelta
    cfg = cfg if cfg is not None else store.load_config()
    if not configured():
        return False
    wanted = set(wanted or [])
    t_event = datetime.now()
    what = ", ".join(camera.VIDEO_LABEL[x] for x in camera.VIDEO_TYPES if x in wanted) or "jedes Ereignis"

    def run():
        try:
            chosen, seen = None, set()
            deadline = time.time() + VIDEO_WAIT_S
            while time.time() < deadline and not chosen:
                now = datetime.now()
                try:
                    files = camera.recordings(cam, t_event - timedelta(minutes=3), now + timedelta(minutes=1))
                except camera.CameraError as e:
                    log.debug("Video: Aufnahmeliste nicht lesbar: %s", e)
                    files = []
                for f in files:
                    if f["end"] < t_event - timedelta(seconds=15):
                        continue                                                           # endete vor dem Ereignis
                    trig = f["triggers"]
                    if trig is not None:
                        seen |= trig & set(camera.VIDEO_TYPES)
                    if wanted and (trig is None or not (trig & wanted)):
                        continue
                    if (now - f["end"]).total_seconds() < VIDEO_SETTLE_S or (f["end"] - f["start"]).total_seconds() < 3:
                        continue                                                           # Aufnahme laeuft noch bzw. ist noch nicht abgeschlossen
                    key = (cam["id"], f["name"], tuple(sorted(to or [])))
                    if key in _video_sent:
                        continue
                    chosen = (f, key)
                    break
                if not chosen:
                    time.sleep(VIDEO_POLL_S)
            if not chosen:
                got = ", ".join(camera.VIDEO_LABEL[x] for x in camera.VIDEO_TYPES if x in seen)
                opslog.log("notify", f"Video {cam['name']}: kein passendes Ereignis ({what}) gefunden – nichts gesendet" + (f" (Aufnahme enthielt: {got})" if got and wanted else ""))
                return
            f, key = chosen
            _video_sent[key] = time.time()
            for k in [k for k, v in _video_sent.items() if time.time() - v > 86400]:
                _video_sent.pop(k, None)
            off = max(0.0, (t_event - f["start"]).total_seconds() - VIDEO_PRE_S)
            with _video_sem, tempfile.TemporaryDirectory() as tmp:
                src, dst = tmp + "/aufnahme.mp4", tmp + "/clip.mp4"
                camera.download_recording(cam, f["name"], src)
                camera.make_clip(src, dst, off, VIDEO_LEN_S, 720)
                kinds = ", ".join(camera.VIDEO_LABEL[x] for x in camera.VIDEO_TYPES if f["triggers"] and x in f["triggers"])
                send_video(dst, _prefix(cfg) + (caption or f"🎥 {cam['name']}" + (f" · {kinds}" if kinds else "")), to=to)
            opslog.count("notify_sent")
            opslog.log("notify", f"Video {cam['name']} gesendet ({f['name'].rsplit('/', 1)[-1]})")
        except Exception as e:                                                             # noqa: BLE001
            log.warning("Telegram-Video nicht gesendet: %s", e)
            opslog.log("notify_fail", f"{e} | Video {cam['name']}")
    threading.Thread(target=run, daemon=True).start()
    return True


def is_active(key: str) -> bool:
    with _lock:
        return key in _state()["events"]


def event(key: str, active: bool, text_on: str, text_off: str | None = None, *, cfg: dict | None = None,
          after_min: float = 0, flag: str | None = None, now: datetime | None = None) -> None:
    """Zustandsmeldung: sendet `text_on` einmal, sobald das Problem `after_min` Minuten am Stueck besteht, und `text_off`
    (falls angegeben) einmal, wenn es behoben ist. `flag` = welcher Schalter in den Einstellungen gilt (Standard: key)."""
    cfg = cfg if cfg is not None else store.load_config()
    flag = flag or key
    if flag not in EVENTS:
        return
    now = now or datetime.now()
    send_text = None
    can = any_configured() and enabled(flag, cfg)      # nur als "gemeldet" markieren, wenn die Meldung auch wirklich rausgeht
    with _lock:
        st = _state()
        ev = st["events"].get(key)
        changed = False
        if active:
            if ev is None:
                ev = st["events"][key] = {"since": now.isoformat(timespec="seconds"), "sent": False}
                changed = True
            if not ev["sent"]:
                since = datetime.fromisoformat(ev["since"])
                if can and (now - since).total_seconds() >= after_min * 60:
                    ev["sent"] = True
                    changed = True
                    send_text = text_on
        elif ev is not None:
            if ev.get("sent") and text_off:
                send_text = text_off
            del st["events"][key]
            changed = True
        if changed:
            try:
                store._dump_json(STATE_PATH, st, indent=None)
            except OSError as e:
                log.warning("Meldungs-Zustand nicht speicherbar: %s", e)
    if send_text and can:
        _send_async(_prefix(cfg) + send_text, system=True)


def daily_summary(cfg: dict, now: datetime, extra=None) -> None:
    """Abends einmal die Tagesbilanz (ab notify_summary_hour)."""
    if not (any_configured() and enabled("summary", cfg)):
        return
    hour = int(cfg.get("notify_summary_hour", DEFAULT_SUMMARY_HOUR))
    if now.hour < hour:
        return
    with _lock:
        st = _state()
        if st.get("summary_date") == now.date().isoformat():
            return
        st["summary_date"] = now.date().isoformat()
        store._dump_json(STATE_PATH, st, indent=None)
    try:
        day = store.energy_week_summary(now)["days"][-1]
    except Exception as e:                                  # noqa: BLE001
        log.warning("Tages-Zusammenfassung nicht berechenbar: %s", e)
        return
    zeilen = [f"📊 Tagesbilanz {now:%d.%m.}",
              f"☀️ Solar: {day['solar']:.1f} kWh",
              f"🏠 Verbrauch: {day['verbrauch']:.1f} kWh",
              f"⬇️ Netzbezug: {day['import']:.1f} kWh",
              f"⬆️ Einspeisung: {day['export']:.1f} kWh"]
    if day.get("autarky") is not None:
        zeilen.append(f"🔋 Autarkie: {day['autarky']:.0f} %")
    if day.get("cost_eur"):
        zeilen.append(f"💶 Netzkosten: {day['cost_eur']:.2f} €")
        try:                                                     # nur, wenn Vertragskosten eingetragen sind (sonst unveraendert wie bisher)
            if store.contract_fixed_cost_eur(cfg, 1) or float(cfg.get("vat_percent", 0) or 0):
                incl = store.cost_incl_fees_eur(cfg, day["cost_eur"], 1)
                zeilen.append(f"🧾 Geschätzte Gesamtkosten heute (inkl. Gebühren, MwSt): {incl:.2f} €")
        except Exception as e:                                   # noqa: BLE001
            log.warning("Gesamtkosten inkl. Gebuehren nicht berechenbar: %s", e)
    try:
        zusatz = ("\n\n" + extra()) if extra else ""
    except Exception:                                       # noqa: BLE001
        zusatz = ""
    _send_async(_prefix(cfg) + "\n".join(zeilen) + zusatz, system=True)
