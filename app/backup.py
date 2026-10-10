"""Sicherung und Wiederherstellung aller Einstellungen als EINE verschluesselte Datei (ohne Terminal/SSH).

Die Sicherung enthaelt Konten, Zugangsdaten, Geraete, Regeln usw. - deshalb ist sie immer mit einem Passwort verschluesselt
(AES-256-GCM, Schluessel per scrypt aus dem Passwort). Format: b"BNXB1" + Salz(16) + Nonce(12) + verschluesselter ZIP + Tag(16).
"""
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime

import store

MAGIC = b"BNXB1"
LEGACY_MAGIC = b"HNXB1"                      # Sicherungen aus der Zeit vor der Umbenennung bleiben einspielbar
FORMAT = 1
MIN_PASSWORD = 8
MAX_UNPACKED = 2 * 1024 ** 3                      # Schutz vor ZIP-Bomben

# Einstellungen, Konten, Geraete, Regeln - immer dabei
SETTINGS_FILES = [
    "config.json", "users.json", "secret.key",
    "shelly_devices.json", "tuya_cloud.json", "homematic.json", "homematic_sensors.json", "homematic_setpoints.json",
    "homematic_locks.json", "homematic_sounds.json", "homematic_blinds.json", "zigbee.json", "wol.json", "cameras.json",
    "virtual.json", "shares.json", "sources.json", "alexa.json", "nfc.json", "rules.json", "telegram.json", "pushover.json", "cloudflare_tunnel.json", "vrm_cloud.json",
    "ev_schedules.json", "contract_periods.json", "verlauf_series.json", "verlauf_charts.json",
]
# Zeitreihen und Historie - wahlweise
DATA_FILES = [
    "state.json", "history.json", "energy.json", "charge_log.json", "solar_log.json", "monthly_summary.json",
    "price_history.json", "savings_days.json", "battery_watchdog.json", "forecast_hours.json", "fixed_cost_repair.json",
    "verlauf.db",
]
DATA_DIRS = ["history_archive"]
_ARCHIVE_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")


class BackupError(Exception):
    pass


def _crypto():
    try:
        from Crypto.Cipher import AES
        from Crypto.Protocol.KDF import scrypt
        from Crypto.Random import get_random_bytes
    except ImportError:
        raise BackupError("Das Verschlüsselungs-Paket (pycryptodome) fehlt – bitte die App aktualisieren/neu installieren.")
    return AES, scrypt, get_random_bytes


def _key(password: str, salt: bytes) -> bytes:
    _, scrypt, _ = _crypto()
    return scrypt(password.encode("utf-8"), salt, 32, N=2 ** 15, r=8, p=1)


def _encrypt(data: bytes, password: str) -> bytes:
    AES, _, rnd = _crypto()
    salt, nonce = rnd(16), rnd(12)
    c = AES.new(_key(password, salt), AES.MODE_GCM, nonce=nonce)
    c.update(MAGIC)
    ct, tag = c.encrypt_and_digest(data)
    return MAGIC + salt + nonce + ct + tag


def _decrypt(blob: bytes, password: str) -> bytes:
    AES, _, _ = _crypto()
    magic = MAGIC if blob.startswith(MAGIC) else (LEGACY_MAGIC if blob.startswith(LEGACY_MAGIC) else None)
    if magic is None or len(blob) < len(magic) + 16 + 12 + 16:
        raise BackupError("Das ist keine Sicherungsdatei dieser App.")
    salt, nonce = blob[5:21], blob[21:33]
    ct, tag = blob[33:-16], blob[-16:]
    c = AES.new(_key(password, salt), AES.MODE_GCM, nonce=nonce)
    c.update(magic)
    try:
        return c.decrypt_and_verify(ct, tag)
    except ValueError:
        raise BackupError("Passwort falsch oder die Datei ist beschädigt.")


def _sqlite_copy(src: str, dst: str) -> None:
    """Konsistente Kopie einer laufenden SQLite-Datenbank (auch mit WAL)."""
    a = sqlite3.connect("file:%s?mode=ro" % src.replace("\\", "/"), uri=True, timeout=30)
    try:
        b = sqlite3.connect(dst)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()


def create_backup(password: str, include_data: bool, base_dir: str) -> tuple:
    """Gibt (Bytes, Dateiname) zurueck."""
    if len(password or "") < MIN_PASSWORD:
        raise BackupError("Das Sicherungs-Passwort braucht mindestens %d Zeichen." % MIN_PASSWORD)
    names = list(SETTINGS_FILES) + (DATA_FILES if include_data else [])
    buf = io.BytesIO()
    added = []
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for n in names:
            p = os.path.join(base_dir, n)
            if not os.path.isfile(p):
                continue
            if n.endswith(".db"):
                t = os.path.join(tmp, n)
                try:
                    _sqlite_copy(p, t)
                except sqlite3.Error:
                    continue
                p = t
            z.write(p, n)
            added.append(n)
        if include_data:
            for d in DATA_DIRS:
                dp = os.path.join(base_dir, d)
                if os.path.isdir(dp):
                    for f in sorted(os.listdir(dp)):
                        if _ARCHIVE_NAME.fullmatch(f) and os.path.isfile(os.path.join(dp, f)):
                            z.write(os.path.join(dp, f), d + "/" + f)
                            added.append(d + "/" + f)
        cfg = store.load_config()
        manifest = {"format": FORMAT, "app": store.default_app_name(cfg), "version": _version(base_dir),
                    "created": datetime.now().isoformat(timespec="seconds"), "include_data": bool(include_data), "files": added}
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    safe = re.sub(r"[^A-Za-z0-9]+", "-", store.default_app_name(cfg)).strip("-") or "BlueNexus"
    return _encrypt(buf.getvalue(), password), "%s-Sicherung-%s.bnx" % (safe, stamp)


def _version(base_dir: str) -> str:
    try:
        with open(os.path.join(base_dir, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _allowed(name: str) -> bool:
    if name in SETTINGS_FILES or name in DATA_FILES:
        return True
    parts = name.split("/")
    return len(parts) == 2 and parts[0] in DATA_DIRS and bool(_ARCHIVE_NAME.fullmatch(parts[1]))


def _open(blob: bytes, password: str) -> zipfile.ZipFile:
    raw = _decrypt(blob, password)
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise BackupError("Die Sicherung ist beschädigt.")
    if int(manifest.get("format", 0)) > FORMAT:
        raise BackupError("Die Sicherung stammt von einer neueren App-Version – bitte erst diese App aktualisieren.")
    if sum(i.file_size for i in z.infolist()) > MAX_UNPACKED:
        raise BackupError("Die Sicherung ist unplausibel groß.")
    return z


def inspect_backup(blob: bytes, password: str) -> dict:
    z = _open(blob, password)
    m = json.loads(z.read("manifest.json").decode("utf-8"))
    files = [n for n in m.get("files", []) if _allowed(n)]
    cfg = {}
    if "config.json" in files:
        try:
            cfg = json.loads(z.read("config.json").decode("utf-8"))
        except ValueError:
            cfg = {}
    users = []
    if "users.json" in files:
        try:
            users = sorted((json.loads(z.read("users.json").decode("utf-8")).get("users") or {}).keys())
        except ValueError:
            pass
    return {"app": m.get("app", ""), "version": m.get("version", ""), "created": m.get("created", ""),
            "include_data": bool(m.get("include_data")), "count": len(files), "users": users,
            "history_files": len([n for n in files if n in DATA_FILES or n.startswith("history_archive/")])}


def restore_backup(blob: bytes, password: str, base_dir: str) -> dict:
    """Spielt die Sicherung ein. Vorher wird der aktuelle Stand in app/backups/ gesichert (falls es etwas zu sichern gibt)."""
    z = _open(blob, password)
    m = json.loads(z.read("manifest.json").decode("utf-8"))
    files = [n for n in m.get("files", []) if _allowed(n) and n in z.namelist()]
    if "config.json" not in files or "users.json" not in files:
        raise BackupError("Die Sicherung enthält keine Einstellungen und Konten – so kann sie nicht eingespielt werden.")
    for n in files:                                                       # Inhalt vorab pruefen: JSON muss lesbar sein
        if n.endswith(".json"):
            try:
                json.loads(z.read(n).decode("utf-8"))
            except ValueError:
                raise BackupError("Die Datei %s in der Sicherung ist beschädigt." % n)
    pre = _snapshot_before(base_dir)
    written, failed = [], []
    for n in files:
        dst = os.path.join(base_dir, *n.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".restore.tmp"
        try:
            with z.open(n) as src, open(tmp, "wb") as out:
                shutil.copyfileobj(src, out)
            if n == "verlauf.db":
                _replace_db(tmp, dst)
            else:
                os.replace(tmp, dst)
            store.secure_file(dst)
            written.append(n)
        except OSError as e:
            failed.append("%s (%s)" % (n, e))
            try:
                os.remove(tmp)
            except OSError:
                pass
    return {"written": len(written), "failed": failed, "previous": pre}


def _replace_db(tmp: str, dst: str) -> None:
    """Die Verlaufs-Datenbank ist (vor allem unter Windows) von der laufenden Aufzeichnung geoeffnet: Verbindung schliessen und ein paar Mal versuchen."""
    last = None
    for _ in range(10):
        try:
            import verlauf
            verlauf.close()
        except Exception:                                             # noqa: BLE001
            pass
        try:
            for ext in ("-wal", "-shm"):
                if os.path.exists(dst + ext):
                    os.remove(dst + ext)
            os.replace(tmp, dst)
            return
        except OSError as e:
            last = e
            time.sleep(0.4)
    raise last


def _snapshot_before(base_dir: str):
    """Sichert den bisherigen Stand (unverschluesselt, nur fuer den Besitzer lesbar) - Rueckweg, falls die falsche Sicherung eingespielt wurde."""
    have = [n for n in SETTINGS_FILES if os.path.isfile(os.path.join(base_dir, n))]
    if not have:
        return None
    d = os.path.join(base_dir, "backups")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "vor-wiederherstellung-%s.zip" % time.strftime("%Y%m%d-%H%M%S"))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n in have:
            z.write(os.path.join(base_dir, n), n)
    store.secure_file(path)
    return os.path.basename(path)
