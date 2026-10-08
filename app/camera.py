"""
Kameras (Reolink): Standbild und Live-Ansicht ueber die App.

- Reolink-Kameras (LAN/PoE/WLAN) werden **lokal** angesprochen: Standbild ueber die HTTP-Schnittstelle (cgi-bin/api.cgi, "Snap"),
  Live-Bild ueber RTSP, das ffmpeg in einen MJPEG-Strom umwandelt (laeuft in jedem Browser, auch iPhone). Ohne ffmpeg gibt es nur
  Standbilder (die Seite fragt dann schnell hintereinander neu ab).
- Zugangsdaten und IP der Kamera verlassen den Server nie: Bilder laufen durch die App (Anmeldung, Rechte und Sichtbarkeit pro Konto).
- Zweiter Typ "rtsp" (z. B. Wansview und andere Kameras mit RTSP): Standbild = ein Bild aus dem RTSP-Strom (ffmpeg), Live wie oben.
  Der passende RTSP-Pfad wird beim Hinzufuegen automatisch gesucht.
- Eigenes Register (cameras.json). Neue Kameras sind zunaechst nur fuer Administratoren sichtbar (siehe visibility.py).
"""
from __future__ import annotations

import os
import queue
import random
import shutil
import subprocess
import threading
import time
import uuid
from urllib.parse import quote

import requests

try:                                       # selbstsignierte Kamera-Zertifikate (https) sind normal
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:                          # noqa: BLE001
    pass

_DIR = os.path.dirname(os.path.abspath(__file__))
CAMERAS_PATH = os.path.join(_DIR, "cameras.json")
TIMEOUT = 6.0
RTSP_SNAP_TTL_S = 1.5                      # RTSP-Kameras: Bild kommt per ffmpeg (Verbindungsaufbau dauert ein, zwei Sekunden)
SNAP_TTL_S = 0.8                           # mehrere Betrachter teilen sich ein Bild (schont die Kamera), kurz genug fuer "jede Sekunde"
MAX_STREAMS = 6                            # gleichzeitige Live-Stroeme insgesamt (jeder belegt einen Server-Thread + ffmpeg)
MAX_LIVE_S = 15 * 60                       # ein Live-Strom endet nach dieser Zeit (Tab vergessen = kein Dauerverkehr); "Play" startet neu
STREAM_FPS = 8
MOTION_TTL_S = 0.5                        # Bewegungszustand je Kamera so lange gueltig (mehrere Sensoren derselben Kamera teilen eine Abfrage)
MOTION_LABEL = {"md": "Bewegung", "people": "Person", "vehicle": "Fahrzeug", "dog_cat": "Tier", "visitor": "Klingel gedrückt"}

_lock = threading.RLock()
_snap_cache: dict[str, tuple[float, bytes]] = {}
_snap_locks: dict[str, threading.Lock] = {}
_tokens: dict[str, tuple[float, str]] = {}
_motion_cache: dict[str, tuple[float, object]] = {}      # Kamera-ID -> (Zeit, Zustand | CameraError)
_motion_locks: dict[str, threading.Lock] = {}
_slots = threading.BoundedSemaphore(MAX_STREAMS)


class CameraError(ValueError):
    pass


def _store():
    import store
    return store


def load() -> list[dict]:
    with _lock:
        d = _store()._load_json_recovering(CAMERAS_PATH, lambda: [])
        return [x for x in d if isinstance(x, dict) and x.get("id")] if isinstance(d, list) else []


def _save(items: list[dict]):
    _store()._dump_json(CAMERAS_PATH, items, indent=2)


def users_registry():
    """(laden, speichern) fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load, _save


def get(cid: str) -> dict | None:
    return next((x for x in load() if x["id"] == cid), None)


def public(item: dict, admin: bool = False) -> dict:
    """Ohne Passwort. IP/Benutzer/Port/Kanal nur fuer Administratoren."""
    out = {k: item.get(k) for k in ("id", "name", "model", "kind", "show", "users") if k in item}
    out["kind"] = item.get("kind", "reolink")
    if admin:
        out.update({"host": item.get("host", ""), "user": item.get("user", ""), "port": item.get("port"), "channel": item.get("channel", 0),
                    "https": bool(item.get("https")), "password_set": bool(item.get("password"))})
        if item.get("kind") == "rtsp":
            out.update({"path_main": item.get("path_main", ""), "path_sub": item.get("path_sub", "")})
    else:
        out.pop("users", None)
    return out


# ---------------------------------------------------------------- Reolink-Schnittstelle
def _base(item: dict) -> str:
    https = bool(item.get("https"))
    port = int(item.get("port") or (443 if https else 80))
    return f"{'https' if https else 'http'}://{item['host']}:{port}/cgi-bin/api.cgi"


class _CredsError(CameraError):
    """Benutzer/Passwort wurden von der Kamera abgelehnt."""


def _detail(j: dict) -> str:
    e = j.get("error") or {}
    return f"{e.get('rspCode')}" + (f": {e.get('detail')}" if e.get("detail") else "")


def _login(item: dict) -> str:
    """Token-Anmeldung (von Reolink empfohlen; neuere Firmware lehnt Benutzer/Passwort in der Adresse teils ab)."""
    body = [{"cmd": "Login", "param": {"User": {"Version": "0", "userName": item.get("user", ""), "password": item.get("password", "")}}}]
    try:
        r = requests.post(_base(item), params={"cmd": "Login"}, json=body, timeout=TIMEOUT, verify=False)
        j = r.json()[0]
    except requests.RequestException as e:
        raise CameraError(f"Kamera nicht erreichbar ({e.__class__.__name__}) – Adresse/Netz prüfen")
    except (ValueError, IndexError, KeyError):
        raise CameraError("Unerwartete Antwort der Kamera – ist das eine Reolink-Kamera?")
    if j.get("code") != 0:
        if (j.get("error") or {}).get("rspCode") in (-6, -7):
            raise _CredsError("Anmeldung an der Kamera fehlgeschlagen – Benutzer/Passwort prüfen")
        raise CameraError(f"Die Kamera lehnt die Token-Anmeldung ab ({_detail(j)})")
    try:
        tok = j["value"]["Token"]["name"]
    except (KeyError, TypeError):
        raise CameraError("Die Kamera lieferte kein Token")
    _tokens[item.get("id", "")] = (time.time() + 3000, tok)
    return tok


def _auth(item: dict) -> dict:
    """Zugang fuer eine Anfrage: bevorzugt Token (einmal anmelden, ~50 min gueltig); kennt die Kamera keine Token-Anmeldung, Benutzer/Passwort in der Adresse."""
    tok = _tokens.get(item.get("id", ""))
    if tok and tok[0] > time.time():
        return {"token": tok[1]}
    try:
        return {"token": _login(item)}
    except _CredsError:
        raise
    except CameraError as e:
        if "nicht erreichbar" in str(e) or "Unerwartete" in str(e):
            raise
        return {"user": item.get("user", ""), "password": item.get("password", "")}


def _call(item: dict, cmd: str, param: dict | None = None, action: int = 0) -> dict:
    last = None
    for attempt in (0, 1):
        auth = _auth(item) if attempt == 0 else {"user": item.get("user", ""), "password": item.get("password", "")}   # 2. Versuch: Benutzer/Passwort in der Adresse
        try:
            r = requests.post(_base(item), params={"cmd": cmd, **auth}, json=[{"cmd": cmd, "action": action, "param": param or {}}], timeout=TIMEOUT, verify=False)
            j = r.json()[0]
        except requests.RequestException as e:
            raise CameraError(f"Kamera nicht erreichbar ({e.__class__.__name__}) – Adresse/Netz prüfen")
        except (ValueError, IndexError, KeyError):
            raise CameraError("Unerwartete Antwort der Kamera – ist das eine Reolink-Kamera?")
        if j.get("code") == 0:
            return j.get("value") or {}
        last = j
        rsp = (j.get("error") or {}).get("rspCode")
        if rsp in (-6, -7):
            _tokens.pop(item.get("id", ""), None)
            if attempt == 0 and "token" in auth:                        # Token abgelaufen -> neu anmelden
                try:
                    _login(item)
                except _CredsError:
                    raise
                except CameraError:
                    pass
                continue
            raise _CredsError("Anmeldung an der Kamera fehlgeschlagen – Benutzer/Passwort prüfen")
    raise CameraError(f"Die Kamera meldet einen Fehler ({_detail(last or {})}) – Reolink-Kamera, Firmware und Benutzerrechte (Administrator?) prüfen")


# ---------------------------------------------------------------- Aufnahmen auf der SD-Karte (Video zum Ereignis)
VIDEO_TYPES = ("animal", "person", "vehicle", "motion")                        # Ereignisarten, nach denen sich filtern laesst
VIDEO_LABEL = {"animal": "Tier", "person": "Person", "vehicle": "Fahrzeug", "motion": "Bewegung"}
_TRIGGER_BIT = {"person": 17, "vehicle": 19, "animal": 20, "schedule": 23, "motion": 24, "doorbell": 26}     # Stelle im Hex-Block des Dateinamens (von links, wie reolink_aio)


def decode_triggers(name: str):
    """Ereignisarten einer Aufnahme aus dem Dateinamen (RecM02_<Datum>_<von>_<bis>_<Hex>_<Groesse>.mp4); None = Name nicht lesbar."""
    base = str(name).rsplit("/", 1)[-1].rsplit(".", 1)[0]
    parts = base.split("_")
    if not parts[0].startswith("Rec") or len(parts[0]) != 6 or len(parts) not in (6, 7):
        return None
    hexv = parts[4] if len(parts) == 6 else parts[5]
    try:
        bits = bin(int(hexv, 16))[2:].zfill(len(hexv) * 4)
    except ValueError:
        return None
    return {k for k, p in _TRIGGER_BIT.items() if p < len(bits) and bits[p] == "1"}


def _rt(t: dict):
    from datetime import datetime
    try:
        return datetime(t["year"], t["mon"], t["day"], t["hour"], t["min"], t["sec"])
    except (KeyError, TypeError, ValueError):
        return None


def recordings(item: dict, start, end, stream: str = "main") -> list[dict]:
    """Aufnahmen der SD-Karte im Zeitraum (Kamerazeit = Serverzeit angenommen): [{name, start, end, size, triggers}], aelteste zuerst."""
    ch = int(item.get("channel") or 0)
    tm = lambda d: {"year": d.year, "mon": d.month, "day": d.day, "hour": d.hour, "min": d.minute, "sec": d.second}
    param = {"Search": {"channel": ch, "onlyStatus": 0, "streamType": stream, "StartTime": tm(start), "EndTime": tm(end)}}
    err = None
    for action in (1, 0):                                                    # laut Reolink-Doku action 1, manche Firmware nur 0
        try:
            v = _call(item, "Search", param, action)
            break
        except _CredsError:
            raise
        except CameraError as e:
            err = e
    else:
        raise err or CameraError("Aufnahmeliste nicht lesbar")
    out = []
    for f in ((v.get("SearchResult") or {}).get("File")) or []:
        a, b = _rt(f.get("StartTime") or {}), _rt(f.get("EndTime") or {})
        if not (f.get("name") and a and b):
            continue
        try:
            size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        out.append({"name": f["name"], "start": a, "end": b, "size": size, "triggers": decode_triggers(f["name"])})
    return sorted(out, key=lambda x: x["start"])


def download_recording(item: dict, name: str, dest: str, timeout: float = 400.0) -> int:
    """Laedt eine Aufnahme (MP4) in die Datei `dest`; gibt die Groesse in Bytes zurueck."""
    auth = _auth(item)
    try:
        r = requests.get(_base(item), params={"cmd": "Download", "source": name, "output": name.rsplit("/", 1)[-1], **auth}, stream=True, timeout=(8, 30), verify=False)
    except requests.RequestException as e:
        raise CameraError(f"Aufnahme nicht ladbar ({e.__class__.__name__})")
    if r.status_code != 200:
        r.close()
        raise CameraError(f"Aufnahme nicht ladbar (HTTP {r.status_code})")
    got, t0, head = 0, time.time(), b""
    try:
        with open(dest, "wb") as f:
            for chunk in r.iter_content(262144):
                if not head:
                    head = chunk[:16]
                f.write(chunk)
                got += len(chunk)
                if time.time() - t0 > timeout:
                    raise CameraError("Download der Aufnahme dauert zu lange")
    except requests.RequestException as e:
        raise CameraError(f"Aufnahme nicht ladbar ({e.__class__.__name__})")
    finally:
        r.close()
    if got < 1024 or b"ftyp" not in head:
        raise CameraError("Die Kamera lieferte keine gültige Videodatei")
    return got


def make_clip(src: str, dst: str, offset_s: float = 0.0, length_s: int = 20, height: int = 720) -> None:
    """Kurzclip: ab `offset_s` Sekunden, `length_s` lang, auf `height` Pixel Hoehe verkleinert (H.264/AAC, schnell startbar) - passt sicher unter die 50-MB-Grenze von Telegram."""
    ff = ffmpeg_path()
    if not ff:
        raise CameraError("ffmpeg fehlt – für Video-Clips nötig")
    cmd = [ff, "-y", "-loglevel", "error", "-ss", f"{max(0.0, offset_s):.1f}", "-i", src, "-t", str(int(length_s)), "-vf", f"scale=-2:{int(height)}",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", dst]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        raise CameraError("Verkleinern des Videos dauert zu lange")
    if p.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) < 1024:
        raise CameraError("Video konnte nicht verkleinert werden: " + p.stderr.decode("utf-8", "replace")[-160:].strip())
    if os.path.getsize(dst) > 48 * 1024 * 1024:
        raise CameraError("Der Clip ist zu groß für Telegram")


def motion_states(item: dict, force: bool = False) -> dict:
    """{"md": bool, "people": bool, "vehicle": bool, "dog_cat": bool, "support": {...}} einer Reolink-Kamera.
    "md" = einfache Bewegungserkennung, "visitor" = Klingel einer Tuerklingel gedrueckt, die anderen (nur wenn die Kamera sie kann) = KI-Erkennung. 1 s zwischengespeichert, auch bei Fehlern."""
    cid = item["id"]
    with _motion_locks.setdefault(cid, threading.Lock()):            # mehrere Sensoren derselben Kamera: nur eine Abfrage
        hit = _motion_cache.get(cid)
        if hit and not force and time.time() - hit[0] < MOTION_TTL_S:
            if isinstance(hit[1], Exception):
                raise hit[1]
            return hit[1]
        ch = int(item.get("channel") or 0)
        try:
            v = _call(item, "GetMdState", {"channel": ch})
            out = {"md": bool(int(v.get("state") or 0)), "support": {"md"}}
            try:
                ai = _call(item, "GetAiState", {"channel": ch})
            except CameraError:
                ai = {}                                              # aeltere Kameras: keine KI-Erkennung
            for k in ("people", "vehicle", "dog_cat", "visitor"):                # visitor = Klingeltaste (nur Video-Tuerklingeln)
                e = ai.get(k)
                if isinstance(e, dict) and "alarm_state" in e:
                    out[k] = bool(int(e.get("alarm_state") or 0))
                    if int(e.get("support") or 0):
                        out["support"].add(k)
        except (CameraError, ValueError, TypeError) as e:
            err = e if isinstance(e, CameraError) else CameraError("Unerwartete Antwort der Kamera")
            _motion_cache[cid] = (time.time(), err)
            raise err
        _motion_cache[cid] = (time.time(), out)
        return out


def motion_sensor_id(cid: str, key: str) -> str:
    return f"cam-{cid}-{key}"


def motion_scan(known_ids: set) -> list[dict]:
    """Bewegungs-Sensoren aller Reolink-Kameras (Bewegung + unterstuetzte Person/Fahrzeug/Tier)."""
    out, errors = [], []
    for cam in load():
        if cam.get("kind", "reolink") != "reolink":
            continue
        try:
            st = motion_states(cam, force=True)
        except CameraError as e:
            errors.append(f"{cam.get('name')}: {e}")
            continue
        for key in ("md", "people", "vehicle", "dog_cat", "visitor"):
            if key not in st["support"]:
                continue
            sid = motion_sensor_id(cam["id"], key)
            out.append({"id": sid, "kind": "motion", "address": cam["id"], "interface": "Kamera", "datapoint": key, "unit": "", "binary": True,
                        "model": cam.get("model") or "Reolink", "room": "", "name": f"{cam.get('name')} – {MOTION_LABEL[key]}", "source": "camera",
                        "known": sid in known_ids})
    if errors and not out:
        raise CameraError("Keine Kamera erreichbar – " + "; ".join(errors))
    return out


_motion_scan: dict[str, dict] = {}


def motion_sensors_scan() -> list[dict]:
    import homematic
    items = motion_scan({s["id"] for s in homematic.load_sensors()})
    _motion_scan.clear()
    _motion_scan.update({f["id"]: f for f in items})
    return items


def add_motion_sensors(ids: list[str]) -> list[dict]:
    import homematic
    if any(i not in _motion_scan for i in ids):
        motion_sensors_scan()
    items = homematic.load_sensors()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _motion_scan.get(i)
        if not f:
            raise CameraError("Sensor nicht gefunden (Kamera entfernt oder nicht erreichbar?)")
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "kind", "address", "interface", "datapoint", "unit", "binary", "model", "room", "name", "source")}
        item["users"] = []                                           # neu: zunaechst nur fuer Administratoren sichtbar
        items.append(item)
        added.append(item)
    if added:
        homematic._save_sensors(items)
    return added


def read_motion(sen: dict):
    """True/False (Bewegung/Erkennung aktiv) oder None (Kamera weg/nicht erreichbar/Erkennung nicht vorhanden)."""
    cam = get(sen.get("address", ""))
    if not cam:
        return None
    try:
        st = motion_states(cam)
    except CameraError:
        return None
    v = st.get(sen.get("datapoint"))
    return None if v is None else bool(v)


def motion_sensor_ids(cid: str) -> list[str]:
    import homematic
    return [s["id"] for s in homematic.load_sensors() if s.get("source") == "camera" and s.get("address") == cid]


def device_info(item: dict) -> dict:
    v = _call(item, "GetDevInfo")
    di = v.get("DevInfo") or {}
    return {"name": di.get("name") or "", "model": di.get("model") or "", "firmware": di.get("firmVer") or ""}


def snapshot(item: dict, max_age: float | None = None) -> bytes:
    """Aktuelles Standbild (JPEG). Kurz zwischengespeichert, damit mehrere Betrachter die Kamera nicht belasten.
    `max_age` (Sekunden) ueberschreibt das: 0 = immer ein frisches Bild (Regeln: Foto soll den Moment des Ausloesers zeigen)."""
    cid = item["id"]
    hit = _snap_cache.get(cid)
    ttl = max_age if max_age is not None else (RTSP_SNAP_TTL_S if item.get("kind") == "rtsp" else SNAP_TTL_S)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    if item.get("kind") == "rtsp":
        with _snap_locks.setdefault(cid, threading.Lock()):               # nie mehrere ffmpeg-Aufrufe gleichzeitig fuer dieselbe Kamera
            hit = _snap_cache.get(cid)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            data = rtsp_grab(item)
            _snap_cache[cid] = (time.time(), data)
            return data
    for attempt in (0, 1):
        auth = _auth(item) if attempt == 0 else {"user": item.get("user", ""), "password": item.get("password", "")}
        try:
            r = requests.get(_base(item), params={"cmd": "Snap", "channel": int(item.get("channel") or 0), "rs": "%06x" % random.randrange(1 << 24), **auth},
                             timeout=TIMEOUT, verify=False)
        except requests.RequestException as e:
            raise CameraError(f"Kamera nicht erreichbar ({e.__class__.__name__})")
        if r.ok and r.content[:2] == b"\xff\xd8":
            _snap_cache[cid] = (time.time(), r.content)
            return r.content
        _tokens.pop(cid, None)                                         # JSON-Fehler statt Bild: Token verwerfen, 2. Versuch mit Benutzer/Passwort
    raise CameraError("Kein Bild von der Kamera")


# ---------------------------------------------------------------- RTSP-Kameras (Standbild aus dem Strom, Pfad-Suche)
CANDIDATE_PATHS = ["/live/ch0", "/live/ch00_0", "/live/ch1", "/live/ch00_1", "/stream1", "/stream0", "/h264/ch1/main/av_stream", "/Streaming/Channels/101",
                   "/cam/realmonitor?channel=1&subtype=0", "/11", "/1", "/h264Preview_01_main", "/onvif1"]
GRAB_TIMEOUT_S = 12


def snapshot_cmd(item: dict, path: str | None = None) -> list[str]:
    """ffmpeg-Aufruf, der EIN Bild aus dem RTSP-Strom holt. In Tests ersetzbar."""
    return [ffmpeg_path() or "ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", rtsp_url(item, DEFAULT_QUALITY, path), "-frames:v", "1",
            "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "pipe:1"]


def _grab(item: dict, path: str | None) -> tuple[bytes | None, str]:
    """(JPEG oder None, Fehlertext von ffmpeg)."""
    if not ffmpeg_path():
        raise CameraError("ffmpeg ist auf dem Server nicht installiert – RTSP-Kameras brauchen es (apt install ffmpeg)")
    try:
        r = subprocess.run(snapshot_cmd(item, path), capture_output=True, timeout=GRAB_TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except OSError as e:
        raise CameraError(f"ffmpeg konnte nicht gestartet werden: {e}")
    if r.returncode == 0 and r.stdout[:2] == b"\xff\xd8":
        return r.stdout, ""
    return None, (r.stderr or b"").decode("utf-8", "replace")


def _err_kind(err: str) -> str:
    e = err.lower()
    if "401" in e or "unauthorized" in e or "403" in e:
        return "creds"
    if "connection refused" in e or "no route" in e or "network is unreachable" in e or "timed out" in e or e == "timeout" or "name or service" in e:
        return "down"
    return "path"                                              # z. B. 404 Not Found: Pfad stimmt nicht


def rtsp_grab(item: dict) -> bytes:
    data, err = _grab(item, None)
    if data:
        return data
    k = _err_kind(err)
    raise CameraError({"creds": "Anmeldung an der Kamera fehlgeschlagen – Benutzer/Passwort prüfen", "down": "Kamera nicht erreichbar (RTSP) – Adresse/Port/Netz prüfen"}
                      .get(k, "Kein Bild vom RTSP-Strom – Pfad prüfen"))


def probe_rtsp(item: dict) -> str:
    """Findet den funktionierenden RTSP-Pfad (zuerst der eingetragene, sonst die gaengigen). Gibt ihn zurueck oder wirft CameraError."""
    paths = [item["path_main"]] if item.get("path_main") else CANDIDATE_PATHS
    last = ""
    for p in paths:
        data, err = _grab(item, p)
        if data:
            return p if p.startswith("/") else "/" + p
        k = _err_kind(err); last = k
        if k == "creds":
            raise CameraError("Anmeldung an der Kamera fehlgeschlagen – Benutzer/Passwort prüfen (bei Wansview: das Gerätepasswort, nicht das App-Konto)")
        if k == "down":
            raise CameraError("Kamera nicht erreichbar (RTSP) – IP/Port prüfen und in der Kamera-App RTSP/ONVIF aktivieren")
    raise CameraError("Verbindung steht, aber kein Bild gefunden – RTSP-Pfad stimmt nicht" if item.get("path_main") else
                      "Kein bekannter RTSP-Pfad passt – in der Kamera-App RTSP aktivieren oder den Pfad aus der Anleitung der Kamera unter „Erweitert“ eintragen")


# ---------------------------------------------------------------- Live (ffmpeg: RTSP -> MJPEG)
def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


QUALITIES = {                                                      # Reolink-Namen: "Fluessig" = Teilstrom (klein), "Klar" = Hauptstrom (hohe Aufloesung)
    "fluessig": {"stream": "sub", "width": 960, "fps": 8, "q": 6},
    "klar": {"stream": "main", "width": 1920, "fps": 10, "q": 4},
}
DEFAULT_QUALITY = "klar"


def norm_quality(q) -> str:
    return q if q in QUALITIES else DEFAULT_QUALITY


def rtsp_url(item: dict, quality: str = DEFAULT_QUALITY, path: str | None = None) -> str:
    """Reolink: Preview_<kanal>_main/sub. RTSP-Typ: Host/Port + Pfad (Hauptstrom bei 'klar', Teilstrom bei 'fluessig', sonst derselbe)."""
    user, pw = quote(item.get("user", ""), safe=""), quote(item.get("password", ""), safe="")
    if item.get("kind") == "rtsp":
        p = path if path is not None else ((item.get("path_sub") if norm_quality(quality) == "fluessig" else "") or item.get("path_main") or "")
        return f"rtsp://{user}:{pw}@{item['host']}:{int(item.get('port') or 554)}{p if p.startswith('/') else '/' + p}"
    ch = int(item.get("channel") or 0) + 1
    return f"rtsp://{user}:{pw}@{item['host']}:554/Preview_{ch:02d}_{QUALITIES[norm_quality(quality)]['stream']}"


def ffmpeg_cmd(item: dict, quality: str = DEFAULT_QUALITY) -> list[str]:
    """ffmpeg-Aufruf fuer den MJPEG-Strom. 'klar' = Hauptstrom (bis 1920 Pixel Breite, mehr Serverlast und Datenrate), 'fluessig' = Teilstrom. In Tests ersetzbar."""
    qd = QUALITIES[norm_quality(quality)]
    return [ffmpeg_path() or "ffmpeg", "-loglevel", "error", "-rtsp_transport", "tcp", "-i", rtsp_url(item, quality), "-an",
            "-vf", f"scale='min({qd['width']},iw)':-2", "-r", str(qd["fps"]), "-q:v", str(qd["q"]), "-f", "mpjpeg", "pipe:1"]


MJPEG_TYPE = "multipart/x-mixed-replace;boundary=ffmpeg"


class _Stream:
    """Iterator ueber den MJPEG-Strom von ffmpeg. Ein Leser-Thread holt die Daten, damit Start (erstes Bild) und Ende sauber ueberwacht werden koennen.
    close() raeumt IMMER auf (ffmpeg beenden, Platz freigeben) - auch wenn nie iteriert wurde. ffmpeg wird erst freundlich beendet ('q', danach SIGTERM),
    damit es die RTSP-Sitzung bei der Kamera abmeldet; sonst haelt die Kamera die Sitzung noch lange offen und lehnt die naechste Verbindung ab."""

    def __init__(self, proc):
        self.proc, self.started, self._done = proc, time.time(), False
        self._q: "queue.Queue[bytes | None]" = queue.Queue(maxsize=32)
        self._first = threading.Event()
        self.got = False                                           # wirklich Bilddaten empfangen (nicht nur Ende/Fehler)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while not self._done:
                chunk = self.proc.stdout.read1(16384)                  # liefert, was gerade da ist (kein Warten, bis 16 KB voll sind)
                if not chunk:
                    break
                self.got = True
                self._first.set()
                while not self._done:
                    try:
                        self._q.put(chunk, timeout=0.5)
                        break
                    except queue.Full:
                        continue
        except (OSError, ValueError):
            pass
        finally:
            try:
                self._q.put_nowait(None)
            except queue.Full:
                pass
            self._first.set()                                      # auch bei Fehlern: Wartende nicht haengen lassen

    def __iter__(self):
        return self

    def __next__(self):
        while True:
            if self._done or time.time() - self.started >= MAX_LIVE_S:
                self.close()
                raise StopIteration
            try:
                chunk = self._q.get(timeout=1.0)
            except queue.Empty:
                continue
            if chunk is None:
                self.close()
                raise StopIteration
            return chunk

    def close(self, release: bool = True):
        if self._done:
            return
        self._done = True
        p = self.proc
        try:
            if p.poll() is None:
                try:
                    p.stdin.write(b"q"); p.stdin.flush()               # ffmpeg beendet sich sauber und meldet sich bei der Kamera ab (TEARDOWN)
                except (OSError, ValueError):
                    pass
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.terminate()
                    try:
                        p.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        p.kill()
        except OSError:
            pass
        for f in (p.stdin, p.stdout):
            try:
                f.close()
            except Exception:                                      # noqa: BLE001
                pass
        try:
            p.wait(timeout=3)
        except Exception:                                          # noqa: BLE001
            pass
        if release:
            _slots.release()


START_WAIT_S = 14                    # so lange auf das erste Bild warten (RTSP-Aufbau, Kamera wacht auf)
START_TRIES = 2                      # Kameras halten alte Sitzungen manchmal noch kurz fest: einmal neu verbinden


def stream(item: dict, quality: str = DEFAULT_QUALITY):
    """MJPEG-Strom fuer eine Kamera (Iterator mit close()), erst zurueckgegeben, wenn das erste Bild da ist (bis zu START_TRIES Versuche).
    Wirft CameraError, wenn ffmpeg fehlt, alle Plaetze belegt sind oder die Kamera kein Bild liefert. Endet nach MAX_LIVE_S oder wenn der Betrachter geht."""
    if not ffmpeg_path():
        raise CameraError("ffmpeg ist auf dem Server nicht installiert")
    if not _slots.acquire(blocking=False):
        raise CameraError("Zu viele gleichzeitige Live-Ansichten – bitte später noch einmal")
    last = "Die Kamera liefert kein Live-Bild"
    for attempt in range(START_TRIES):
        try:
            proc = subprocess.Popen(ffmpeg_cmd(item, quality), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.PIPE)
        except OSError as e:
            _slots.release()
            raise CameraError(f"ffmpeg konnte nicht gestartet werden: {e}")
        st = _Stream(proc)
        if st._first.wait(START_WAIT_S) and st.got:
            return st                                              # Platz bleibt belegt, bis st.close()
        st.close(release=False)                                    # kein Bild: ffmpeg sauber beenden (Kamera-Sitzung abmelden), Platz behalten, nochmal versuchen
        last = "Die Kamera liefert kein Live-Bild – Zugang, Netz oder die Zahl erlaubter gleichzeitiger Verbindungen der Kamera prüfen"
        time.sleep(1.0)
    _slots.release()
    raise CameraError(last)


# ---------------------------------------------------------------- Verwaltung (nur Administratoren, die Aufrufer pruefen das)
def add(name: str, host: str, user: str, password: str, port=None, channel=0, https=False, kind: str = "reolink", path_main: str = "", path_sub: str = "") -> dict:
    name = (name or "").strip()[:60]
    host = (host or "").strip()
    kind = "rtsp" if kind == "rtsp" else "reolink"
    if not host:
        raise CameraError("IP-Adresse oder Name der Kamera eingeben")
    if any(c in host for c in "/ @?#"):
        raise CameraError("Adresse: nur IP oder Rechnername, ohne http:// und ohne Pfad")
    try:
        port = int(port) if port not in (None, "") else None
        channel = int(channel or 0)
    except (TypeError, ValueError):
        raise CameraError("Port/Kanal: Zahl erwartet")
    if port is not None and not 1 <= port <= 65535:
        raise CameraError("Port: zwischen 1 und 65535")
    item = {"id": "cam-" + uuid.uuid4().hex[:8], "kind": kind, "name": name, "host": host, "user": (user or "").strip(), "password": password or "",
            "port": port, "channel": channel, "https": bool(https), "show": True, "users": []}
    if kind == "rtsp":
        item["path_main"] = (path_main or "").strip()
        item["path_sub"] = (path_sub or "").strip()
        for k in ("path_main", "path_sub"):
            if item[k] and not item[k].startswith("/"):
                item[k] = "/" + item[k]
            if " " in item[k]:
                raise CameraError("RTSP-Pfad: keine Leerzeichen")
        item["path_main"] = probe_rtsp(item)                      # Verbindung pruefen und Pfad finden
        item["model"] = "RTSP"
        if not item["name"]:
            item["name"] = f"Kamera {host}"
    else:
        try:                                                      # Verbindung pruefen, Modell/Namen uebernehmen (erst http, dann https)
            info = device_info(item)
        except CameraError as e1:
            if item["https"] or "Anmeldung" in str(e1):
                raise
            item["https"] = True
            try:
                info = device_info(item)
            except CameraError:
                raise e1
        item["model"] = info["model"]
        if not item["name"]:
            item["name"] = info["name"] or info["model"] or "Kamera"
    with _lock:
        items = load()
        items.append(item)
        _save(items)
    return item


def update(cid: str, **f) -> bool:
    with _lock:
        items = load()
        for it in items:
            if it["id"] != cid:
                continue
            if isinstance(f.get("name"), str) and f["name"].strip():
                it["name"] = f["name"].strip()[:60]
            for k in ("host", "user"):
                if isinstance(f.get(k), str) and f[k].strip():
                    it[k] = f[k].strip()
            if isinstance(f.get("password"), str) and f["password"]:
                it["password"] = f["password"]
            if f.get("port") not in (None, ""):
                try:
                    p = int(f["port"])
                except (TypeError, ValueError):
                    raise CameraError("Port: Zahl erwartet")
                if not 1 <= p <= 65535:
                    raise CameraError("Port: zwischen 1 und 65535")
                it["port"] = p
            if f.get("channel") not in (None, ""):
                try:
                    it["channel"] = int(f["channel"])
                except (TypeError, ValueError):
                    raise CameraError("Kanal: Zahl erwartet")
            for k in ("path_main", "path_sub"):
                if isinstance(f.get(k), str) and it.get("kind") == "rtsp" and (f[k].strip() or k == "path_sub"):
                    v = f[k].strip()
                    if " " in v:
                        raise CameraError("RTSP-Pfad: keine Leerzeichen")
                    it[k] = ("/" + v.lstrip("/")) if v else ""
            if isinstance(f.get("https"), bool):
                it["https"] = f["https"]
            if isinstance(f.get("show"), bool):
                it["show"] = f["show"]
            _snap_cache.pop(cid, None)
            _tokens.pop(cid, None)
            _save(items)
            return True
    return False


def remove(cid: str) -> bool:
    with _lock:
        items = load()
        keep = [x for x in items if x["id"] != cid]
        if len(keep) == len(items):
            return False
        _save(keep)
        _snap_cache.pop(cid, None)
        _tokens.pop(cid, None)
        return True


def reorder(ids: list[str]):
    with _lock:
        items = load()
        pos = {i: n for n, i in enumerate(ids)}
        items.sort(key=lambda x: pos.get(x["id"], len(ids)))
        _save(items)
