"""
Fernzugriff per Cloudflare Tunnel (Zero Trust) - ohne Port-Freigabe im Router.

Die App startet das Programm `cloudflared` (https://github.com/cloudflare/cloudflared) mit dem Tunnel-Token aus dem eigenen Cloudflare-Konto und
ueberwacht es. Den Tunnel (und die oeffentliche Adresse, z. B. steuerung.meine-domain.de -> http://localhost:<Port der App>) legt man im
Cloudflare-Dashboard an: Zero Trust -> Networks -> Connectors -> Tunnel erstellen -> "cloudflared" -> Token kopieren.

- Token in `cloudflare_tunnel.json` (nicht im Repo, nie zum Browser). Er geht per Umgebungsvariable an cloudflared (nicht in der Prozessliste).
- "enabled" gilt auch nach einem Neustart der App. Faellt cloudflared aus, startet die App es mit Wartezeit neu.
- Das Programm kommt aus dem offiziellen Cloudflare-Release auf GitHub (Linux: amd64, arm64 fuer Raspberry Pi 64 Bit, armhf/arm fuer 32 Bit)
  und liegt in app/bin/ - oder ist schon im System installiert (`cloudflared` im PATH).
"""
from __future__ import annotations

import atexit
import base64
import collections
import json
import logging
import os
import platform
import re
import sandbox
import shutil
import subprocess
import threading
import time

import requests

import store

log = logging.getLogger("tunnel")

_DIR = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(_DIR, "cloudflare_tunnel.json")
BIN_DIR = os.path.join(_DIR, "bin")
BIN_PATH = os.path.join(BIN_DIR, "cloudflared")
PID_PATH = os.path.join(_DIR, "cloudflared.pid")
RELEASE_BASE = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
ARCH_ASSET = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64", "armv7l": "armhf", "armv8l": "armhf", "armv6l": "arm"}
MAX_DOWNLOAD = 120 * 1024 * 1024
SUPERVISE_S = 5.0                                          # so oft schaut die Ueberwachung nach
BACKOFF_S = (5, 15, 60, 300)                               # Wartezeit vor dem n-ten Neustart nach einem Absturz

_lock = threading.RLock()
_proc = None                                               # laufender cloudflared-Prozess
_lines: collections.deque = collections.deque(maxlen=200)  # letzte Log-Zeilen (ohne Token)
_state = {"connections": 0, "last_error": "", "restarts": 0, "since": 0.0, "exit": None}
_supervisor = None
_stop_ev = threading.Event()


class TunnelError(Exception):
    pass


# ---------------------------------------------------------------- Zugang
def _load() -> dict:
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(d: dict) -> None:
    store._dump_json(CFG_PATH, d, indent=None)


def _clean_token(raw: str) -> str:
    """Token aus der Eingabe holen - auch wenn der ganze Befehl `cloudflared service install <token>` eingefuegt wurde."""
    parts = [p for p in str(raw or "").replace('"', " ").replace("'", " ").split() if p]
    return parts[-1] if parts else ""


def validate_token(tok: str) -> None:
    """Ein Tunnel-Token ist Base64 von {"a": Konto, "t": Tunnel-ID, "s": Geheimnis}."""
    try:
        pad = tok + "=" * (-len(tok) % 4)
        d = json.loads(base64.b64decode(pad, validate=False).decode("utf-8"))
        ok = isinstance(d, dict) and all(k in d for k in ("a", "t", "s"))
    except Exception:                                         # noqa: BLE001
        ok = False
    if not ok:
        raise TunnelError("Das ist kein gültiger Tunnel-Token. Im Cloudflare-Dashboard unter Zero Trust → Networks → Connectors → dein Tunnel → „Konfigurieren“ (bzw. beim Erstellen) steht ein langer Text, der mit „eyJ“ beginnt – den komplett einfügen.")


def has_token() -> bool:
    return bool(_load().get("token"))


def enabled() -> bool:
    c = _load()
    return bool(c.get("token") and c.get("enabled"))


def save_token(raw: str) -> None:
    tok = _clean_token(raw)
    if not tok:
        raise TunnelError("Bitte den Tunnel-Token einfügen")
    validate_token(tok)
    c = _load()
    c["token"] = tok
    _save(c)
    if _running() and c.get("enabled"):
        start()                                               # neuer Token -> neu verbinden


def clear_credentials() -> None:
    """Tunnel stoppen und Token loeschen."""
    stop()
    try:
        os.remove(CFG_PATH)
    except FileNotFoundError:
        pass


def set_enabled(on: bool) -> None:
    c = _load()
    if on and not c.get("token"):
        raise TunnelError("Erst den Tunnel-Token eintragen")
    if on and not find_binary():
        raise TunnelError("cloudflared ist noch nicht installiert – erst „cloudflared installieren“ drücken")
    c["enabled"] = bool(on)
    _save(c)
    if on:
        start()
    else:
        stop()


# ---------------------------------------------------------------- Programm
def find_binary() -> str | None:
    if os.path.isfile(BIN_PATH) and os.access(BIN_PATH, os.X_OK):
        return BIN_PATH
    return shutil.which("cloudflared")


def asset_name() -> str | None:
    if platform.system() != "Linux":
        return None
    arch = ARCH_ASSET.get(platform.machine().lower())
    return f"cloudflared-linux-{arch}" if arch else None


_ver_cache: dict = {}


def version() -> str:
    b = find_binary()
    if not b:
        return ""
    try:
        key = (b, os.path.getmtime(b))
    except OSError:
        return ""
    if key in _ver_cache:
        return _ver_cache[key]
    v = _version_uncached(b)
    if v:
        _ver_cache[key] = v
    return v


def _version_uncached(b: str) -> str:
    try:
        out = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    m = re.search(r"version\s+(\S+)", out)
    return m.group(1) if m else out.strip()[:40]


def install() -> str:
    """Laedt cloudflared aus dem offiziellen Cloudflare-Release (GitHub) nach app/bin/ und prueft, dass es laeuft. Rueckgabe: Version."""
    name = asset_name()
    if not name:
        raise TunnelError(f"Automatische Installation gibt es nur für Linux (amd64, arm64, armhf) – hier: {platform.system()} {platform.machine()}. "
                          "Bitte cloudflared von Hand installieren (developers.cloudflare.com → cloudflared).")
    os.makedirs(BIN_DIR, exist_ok=True)
    tmp = BIN_PATH + ".part"
    try:
        r = requests.get(RELEASE_BASE + name, stream=True, timeout=30, allow_redirects=True)
        r.raise_for_status()
        size = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(262144):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise TunnelError("Download zu groß – abgebrochen")
                f.write(chunk)
        if size < 1_000_000:
            raise TunnelError("Download unvollständig (Datei zu klein)")
        os.chmod(tmp, 0o755)
        os.replace(tmp, BIN_PATH)
    except requests.RequestException as e:
        raise TunnelError(f"Download fehlgeschlagen: {e}")
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    v = version()
    if not v:
        try:
            os.remove(BIN_PATH)
        except OSError:
            pass
        raise TunnelError("Das heruntergeladene Programm läuft auf diesem Gerät nicht (falsche Architektur?)")
    return v


# ---------------------------------------------------------------- Prozess
def _running() -> bool:
    return _proc is not None and _proc.poll() is None


def _redact(line: str, tok: str) -> str:
    return line.replace(tok, "***") if tok else line


def _reader(proc, tok: str) -> None:
    ERR = re.compile(r"\b(ERR|error|failed|unauthorized|invalid|refused)\b", re.I)
    try:
        for raw in proc.stdout:
            line = _redact(raw.rstrip(), tok)
            if not line:
                continue
            _lines.append(f"{time.strftime('%H:%M:%S')} {line}")
            if "Registered tunnel connection" in line:
                _state["connections"] += 1
                _state["last_error"] = ""
            elif "Unregistered tunnel connection" in line:
                _state["connections"] = max(0, _state["connections"] - 1)
            elif ERR.search(line):
                _state["last_error"] = line[:300]
    except (OSError, ValueError):
        pass


def _kill_stale() -> None:
    """Ein von einem frueheren App-Lauf uebrig gebliebenes cloudflared beenden (pm2-Neustart)."""
    try:
        with open(PID_PATH, encoding="utf-8") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmd = f.read().decode("utf-8", "replace")
    except OSError:
        cmd = ""
    if "cloudflared" in cmd:
        try:
            os.kill(pid, 15)
            time.sleep(1)
            os.kill(pid, 9)
        except OSError:
            pass
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def start() -> None:
    """cloudflared mit dem gespeicherten Token starten (ein laufender wird ersetzt)."""
    global _proc
    c = _load()
    tok, binp = c.get("token"), find_binary()
    if not tok:
        raise TunnelError("Kein Tunnel-Token gespeichert")
    if not binp:
        raise TunnelError("cloudflared ist nicht installiert")
    with _lock:
        _stop_proc()
        _kill_stale()
        env = {**os.environ, "TUNNEL_TOKEN": tok}
        try:
            proc = subprocess.Popen([binp, "tunnel", "--no-autoupdate", "run"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, text=True, bufsize=1)
        except OSError as e:
            _state["last_error"] = f"Start fehlgeschlagen: {e}"
            raise TunnelError(_state["last_error"])
        _proc = proc
        _state.update(connections=0, last_error="", since=time.time(), exit=None)
        _lines.append(f"{time.strftime('%H:%M:%S')} cloudflared gestartet (PID {proc.pid})")
        try:
            with open(PID_PATH, "w", encoding="utf-8") as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        threading.Thread(target=_reader, args=(proc, tok), daemon=True, name="cloudflared-log").start()
    _ensure_supervisor()


def _stop_proc() -> None:
    global _proc
    p = _proc
    _proc = None
    if p is None:
        return
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    _state["connections"] = 0
    try:
        os.remove(PID_PATH)
    except OSError:
        pass


def stop() -> None:
    with _lock:
        _stop_proc()
        _lines.append(f"{time.strftime('%H:%M:%S')} Tunnel gestoppt")


def _ensure_supervisor() -> None:
    global _supervisor
    if _supervisor and _supervisor.is_alive():
        return
    _stop_ev.clear()
    _supervisor = threading.Thread(target=_supervise, daemon=True, name="cloudflared-supervisor")
    _supervisor.start()


def _supervise() -> None:
    """Soll der Tunnel laufen, aber der Prozess ist weg: mit steigender Wartezeit neu starten."""
    fails = 0
    while not _stop_ev.is_set():
        _stop_ev.wait(SUPERVISE_S)
        try:
            if not enabled():
                fails = 0
                continue
            with _lock:
                alive = _running()
                if _proc is not None and not alive:
                    _state["exit"] = _proc.returncode
            if alive:
                if time.time() - _state["since"] > 120:
                    fails = 0                                  # lief stabil
                continue
            wait = BACKOFF_S[min(fails, len(BACKOFF_S) - 1)]
            _lines.append(f"{time.strftime('%H:%M:%S')} cloudflared beendet (Code {_state['exit']}) – neuer Versuch in {wait} s")
            if _stop_ev.wait(wait) or not enabled():
                continue
            _state["restarts"] += 1
            fails += 1
            start()
        except TunnelError as e:
            _state["last_error"] = str(e)
        except Exception as e:                                   # noqa: BLE001
            log.warning("Tunnel-Ueberwachung: %s", e)


def startup() -> None:
    """Beim Start der App: war der Tunnel eingeschaltet, wieder verbinden."""
    if sandbox.ACTIVE:
        return                                                      # Testmodus: kein zweiter Tunnel mit demselben Token
    _kill_stale()
    if enabled() and find_binary():
        try:
            start()
        except TunnelError as e:
            log.warning("Tunnel: %s", e)


def shutdown() -> None:
    _stop_ev.set()
    with _lock:
        _stop_proc()


# ---------------------------------------------------------------- Anzeige
def status() -> dict:
    c = _load()
    run = _running()
    conns = _state["connections"] if run else 0
    if not c.get("token"):
        text = "Noch kein Token eingetragen"
    elif not find_binary():
        text = "cloudflared ist noch nicht installiert"
    elif not c.get("enabled"):
        text = "Aus"
    elif run and conns > 0:
        text = f"Verbunden ({conns} Verbindung{'en' if conns != 1 else ''}) – von außen erreichbar"
    elif run:
        text = "Verbinde …"
    else:
        text = "Gestoppt – wird neu gestartet"
    return {"has_token": bool(c.get("token")), "enabled": bool(c.get("enabled")), "installed": bool(find_binary()), "version": version() if find_binary() else "",
            "can_install": asset_name() is not None, "asset": asset_name() or "", "running": run, "connected": conns > 0, "connections": conns,
            "text": text, "last_error": _state["last_error"], "restarts": _state["restarts"],
            "uptime_s": int(time.time() - _state["since"]) if run else 0}


def log_lines(n: int = 60) -> list[str]:
    return list(_lines)[-n:]


atexit.register(shutdown)                                  # App beendet -> cloudflared mitbeenden
