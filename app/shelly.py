"""
Shelly-Anbindung: Geraete im LAN finden, anlegen, Status lesen, schalten.
Nur HTTP im lokalen Netz (kein Cloud-Zugriff, keine Zusatz-Pakete).
- Gen1 (z.B. Shelly 1, 1PM, Plug S, 2.5):  /relay/<n>?turn=on|off, /status
- Gen2/3 (Plus/Pro/Gen3):                  /rpc/Switch.Set, /rpc/Shelly.GetStatus
Jeder Schaltkanal ist ein eigener Eintrag (id = "<mac>-<kanal>").
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
import threading
from concurrent.futures import ThreadPoolExecutor

import requests

import homematic
import pins
import zigbee
import midea
import tasmota
import wled
import tuya

log = logging.getLogger("shelly")

DEVICES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shelly_devices.json")
_lock = threading.Lock()

# Auswahl fuer die Geraete-Symbole (Einstellungen); Standard = Steckdose
ICONS = [
         "🔌", "💡", "☀️", "🌞", "🌙", "⭐", "⚡", "🔋", "🔦", "🕯️", "🔥", "♨️",
         "🌡️", "❄️", "🧊", "💨", "🌀", "🌬️", "💧", "🚿", "🛁", "🚰", "🏊", "🌊",
         "🫧", "🌧️", "🧺", "🍳", "☕", "🍽️", "🧹", "🧼", "🍞", "🥶", "🔔", "📺",
         "🎧", "🖥️", "💻", "📱", "🎮", "🎵", "🔊", "📡", "🛋️", "🛏️", "🚪", "🪟",
         "🔒", "🔓", "⏰", "🚧", "🚗", "🚙", "🚐", "🛵", "🚲", "🛠️", "🔧", "🧰",
         "🏠", "🏡", "🏭", "🌿", "🪴", "🌳", "🌱", "🌻", "🎄", "🐟", "🐠", "🐔",
         "🐶", "🐱", "🎛️",
         # Taster, Schalter, Bedienelemente
         "🔘", "⏻", "🎚️", "🕹️", "🔛", "🔆", "🔅", "🛎️", "⏯️", "▶️", "⏹️", "🔁",
         # Haushalts- und Technikgeraete
         "👕", "🧦", "🍲", "🥘", "🫖", "🖨️", "📷", "📹", "🛜", "📶", "🤖", "🧯",
         "🪫", "🔭", "🧲", "🖲️", "🕰️", "🧪", "🪞", "🚽", "🧻", "🪠", "🚨", "🔑",
         # Post, Ton, Anzeigen, Tageszeiten
         "📪", "📬", "📊", "📈", "📉", "🔈", "🔇", "🔉", "🔕", "📢", "🆘", "🌅", "🌄", "💦"]
DEFAULT_ICON = ICONS[0]

PROBE_TIMEOUT = 0.8      # Subnetz-Scan (LAN-Antwort < 100 ms)
CALL_TIMEOUT = 3.0       # Status/Schalten


class ShellyError(Exception):
    pass


# ---------------------------------------------------------------- Speicher
def load_devices() -> list[dict]:
    if not os.path.exists(DEVICES_PATH):
        return []
    try:
        with open(DEVICES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(items: list[dict]):
    with _lock, open(DEVICES_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)


def _find(dev_id: str) -> dict | None:
    return next((d for d in load_devices() if d["id"] == dev_id), None)


# ---------------------------------------------------------------- Netz
def check_ip(ip: str) -> str:
    """Nur private IPv4-Adressen zulassen (kein Missbrauch als Web-Proxy)."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        raise ShellyError("Ungültige IP-Adresse")
    if addr.version != 4 or not (addr.is_private and not addr.is_loopback):
        raise ShellyError("Nur IP-Adressen aus dem lokalen Netz erlaubt")
    return str(addr)


def local_subnet() -> ipaddress.IPv4Network:
    """/24 des Netzwerks, in dem dieser Rechner haengt."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))    # sendet nichts, ermittelt nur die Quell-IP
        ip = s.getsockname()[0]
    except OSError:
        ip = "192.168.2.1"
    finally:
        s.close()
    return ipaddress.ip_network(f"{ip}/24", strict=False)


def _get(ip: str, path: str, timeout: float, auth=None):
    r = requests.get(f"http://{ip}{path}", timeout=timeout, auth=auth)
    r.raise_for_status()
    return r.json()


def probe(ip: str, timeout: float = PROBE_TIMEOUT) -> dict | None:
    """Fragt /shelly ab (ohne Login moeglich). None = kein Shelly."""
    try:
        info = _get(ip, "/shelly", timeout)
    except (requests.RequestException, ValueError):
        return None
    if not isinstance(info, dict) or not (info.get("mac") or info.get("id")):
        return None
    gen = int(info.get("gen") or 1)
    mac = str(info.get("mac") or info.get("id")).replace(":", "").upper()
    if gen >= 2:
        model = info.get("app") or info.get("model") or "Shelly"
        name = info.get("name") or info.get("id") or model
        auth = bool(info.get("auth_en"))
        channels = None       # per Status ermitteln
    else:
        model = info.get("type") or "Shelly"
        name = f"{model}-{mac[-6:]}"
        auth = bool(info.get("auth"))
        channels = int(info.get("num_outputs") or 0)
    return {"ip": ip, "gen": gen, "mac": mac, "model": model, "name": name,
            "auth": auth, "channels": channels}


def _channels_gen2(ip: str) -> list[int]:
    st = _get(ip, "/rpc/Shelly.GetStatus", CALL_TIMEOUT)
    return sorted(int(k.split(":")[1]) for k in st if k.startswith("switch:"))


def _scan_hosts(subnet: ipaddress.IPv4Network | None, extra_networks: list[str] | None) -> list[str]:
    """Zu pruefende Adressen: das eigene /24 (oder `subnet`) plus weitere Netze/VLANs (max. 8192 Adressen)."""
    nets = [subnet or local_subnet()] + [ipaddress.ip_network(n, strict=False) for n in (extra_networks or [])]
    hosts, seen = [], set()
    for net in nets:
        for h in net.hosts():
            s = str(h)
            if s not in seen:
                seen.add(s)
                hosts.append(s)
    return hosts[:8192]


def discover(subnet: ipaddress.IPv4Network | None = None, extra_networks: list[str] | None = None) -> list[dict]:
    """Scannt das Subnetz (und weitere Netze) parallel. Liefert gefundene Shellys (auch bereits angelegte)."""
    hosts = _scan_hosts(subnet, extra_networks)
    with ThreadPoolExecutor(max_workers=64) as ex:
        found = [r for r in ex.map(probe, hosts) if r]
    known = {d.get("mac") for d in load_devices()}
    for f in found:
        f["known"] = f["mac"] in known
    found.sort(key=lambda f: tuple(int(x) for x in f["ip"].split(".")))
    return found


# ---------------------------------------------------------------- Anlegen
def _apply_edit(entry: dict, edits: dict | None):
    """Vorab eingegebenen Namen/Symbol (aus der Trefferliste) uebernehmen."""
    e = (edits or {}).get(entry["id"])
    if not isinstance(e, dict):
        return
    if isinstance(e.get("name"), str) and e["name"].strip():
        entry["name"] = e["name"].strip()[:60]
    if e.get("icon") is not None:
        if e["icon"] not in ICONS:
            raise ShellyError("Unbekanntes Symbol")
        entry["icon"] = e["icon"]


def preview_public(entries: list[dict]) -> list[dict]:
    return [{k: e[k] for k in ("id", "channel", "name", "icon", "model", "ip", "known")} for e in entries]


def add_by_ip(ip: str, password: str = "", edits: dict | None = None, preview: bool = False) -> list[dict]:
    """Legt alle Schaltkanaele des Geraets an (schon vorhandene bleiben unveraendert). `edits` = {geraete-id: {name, icon}}.
    `preview=True` legt nichts an und liefert alle Kanaele mit known-Kennzeichen (fuer die Trefferliste)."""
    ip = check_ip(ip)
    info = probe(ip, CALL_TIMEOUT)
    if not info:
        if not tasmota.probe(ip, CALL_TIMEOUT, ("admin", password) if password else None) and wled.probe(ip, CALL_TIMEOUT):
            return _add_wled(ip, edits, preview)                  # weder Shelly noch Tasmota, aber WLED
        return _add_tasmota(ip, password, edits, preview)
    if info["auth"] and info["gen"] >= 2:
        raise ShellyError("Passwortgeschützte Gen2/3-Geräte werden noch nicht unterstützt "
                          "(Login in der Shelly-Weboberfläche vorübergehend abschalten)")
    if info["auth"] and not password:
        raise ShellyError("Gerät ist passwortgeschützt – Passwort angeben")
    if info["gen"] >= 2:
        try:
            channels = _channels_gen2(ip)
        except (requests.RequestException, ValueError) as e:
            raise ShellyError(f"Status nicht lesbar: {e}")
    else:
        channels = list(range(info["channels"]))
    if not channels:
        raise ShellyError(f"{info['model']} hat keinen Schaltausgang (Relais)")
    items = load_devices()
    have = {d["id"] for d in items}
    added = []
    for ch in channels:
        dev_id = f"{info['mac']}-{ch}"
        if dev_id in have and not preview:
            continue
        name = info["name"] if len(channels) == 1 else f"{info['name']} K{ch + 1}"
        entry = {"id": dev_id, "mac": info["mac"], "ip": ip, "gen": info["gen"],
                 "channel": ch, "model": info["model"], "name": name,
                 "icon": DEFAULT_ICON, "show": False,
                 "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5,
                 "user": "admin" if password else "", "password": password}
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        entry["known"] = dev_id in have
        _apply_edit(entry, edits)
        items.append(entry)
        added.append(entry)
    if preview:
        return added
    for e in added:
        e.pop("known", None)
    _save(items)
    return added


# ---------------------------------------------------------------- Tasmota
def tasmota_discover(subnet: ipaddress.IPv4Network | None = None, extra_networks: list[str] | None = None) -> list[dict]:
    """Sucht Tasmota-Geraete (ohne Passwortschutz) im eigenen /24 und in weiteren Netzen."""
    hosts = _scan_hosts(subnet, extra_networks)
    with ThreadPoolExecutor(max_workers=64) as ex:
        found = [r for r in ex.map(tasmota.probe, hosts) if r and not r.get("auth")]
        wl = [r for r in ex.map(wled.probe, hosts) if r]                  # WLED im selben Durchgang (eine Suche fuer beide)
    known = {d.get("mac") for d in load_devices() if d.get("kind") == "tasmota"}
    for f in found:
        f["known"] = f["mac"] in known
        f["channels"] = len(f["channels"])
    known_w = {d.get("mac") for d in load_devices() if d.get("kind") == "wled"}
    found += [{**w, "known": w["mac"] in known_w, "channels": 1, "wled": True} for w in wl]
    found.sort(key=lambda f: tuple(int(x) for x in f["ip"].split(".")))
    return found


def _add_tasmota(ip: str, password: str = "", edits: dict | None = None, preview: bool = False) -> list[dict]:
    info = tasmota.probe(ip, CALL_TIMEOUT, ("admin", password) if password else None)
    if not info:
        raise ShellyError("Unter dieser Adresse antwortet weder ein Shelly noch ein Tasmota")
    if info["auth"]:
        raise ShellyError("Gerät ist passwortgeschützt – Passwort angeben" if not password
                          else "Passwort abgelehnt (oder kein Tasmota-Gerät)")
    if not info["channels"]:
        raise ShellyError("Dieses Tasmota-Gerät hat keinen Relaiskanal (POWER)")
    items = load_devices()
    have = {d["id"] for d in items}
    added = []
    for ch in info["channels"]:
        dev_id = f"tasmota-{info['mac']}-{ch}"
        if dev_id in have and not preview:
            continue
        entry = {"id": dev_id, "kind": "tasmota", "mac": info["mac"], "ip": ip, "gen": 0, "channel": ch,
                 "model": info["model"], "name": info["name"] if not info["multi"] else f"{info['name']} K{ch}",
                 "icon": DEFAULT_ICON, "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5,
                 "user": "admin" if password else "", "password": password}
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        entry["known"] = dev_id in have
        _apply_edit(entry, edits)
        items.append(entry)
        added.append(entry)
    if preview:
        return added
    for e in added:
        e.pop("known", None)
    _save(items)
    return added


def _add_wled(ip: str, edits: dict | None = None, preview: bool = False) -> list[dict]:
    info = wled.probe(ip, CALL_TIMEOUT)
    if not info:
        raise ShellyError("Unter dieser Adresse antwortet weder ein Shelly noch ein Tasmota noch ein WLED")
    items = load_devices()
    have = {d["id"] for d in items}
    dev_id = f"wled-{info['mac']}"
    if dev_id in have and not preview:
        return []
    entry = {"id": dev_id, "kind": "wled", "mac": info["mac"], "ip": ip, "gen": 0, "channel": 0, "model": info["model"], "name": info["name"],
             "icon": "💡", "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "user": "", "password": ""}
    entry["users"] = []                             # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
    entry["known"] = dev_id in have
    _apply_edit(entry, edits)
    if preview:
        return [entry]
    entry.pop("known", None)
    items.append(entry)
    _save(items)
    return [entry]


# ---------------------------------------------------------------- Midea-Klimaanlagen (NetHome Plus), siehe midea.py
def midea_scan(region=None, account=None, password=None, ip=None) -> list[dict]:
    """Klimaanlagen im Heimnetz suchen (oder eine IP). Rueckgabe ohne Token/Schluessel; bereits angelegte mit known=True."""
    known = {d["id"] for d in load_devices() if d.get("kind") == "midea"}
    try:
        return midea.discover(region or midea.DEFAULT_REGION, account, password, ip, known)
    except midea.MideaError as e:
        raise ShellyError(str(e))


def add_midea(ids: list[str]) -> list[dict]:
    """Legt die gewaehlten Klimaanlagen (aus der letzten Suche, samt Token/Schluessel) an."""
    try:
        entries = midea.build_entries(ids)
    except midea.MideaError as e:
        raise ShellyError(str(e))
    items = load_devices()
    have = {d["id"] for d in items}
    added = []
    for entry in entries:
        if entry["id"] in have:
            continue
        entry.update({"show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5})
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(entry)
        added.append(entry)
    _save(items)
    return added


def _midea_dev(dev_id: str) -> dict:
    d = _find(dev_id)
    if not d:
        raise ShellyError("Gerät nicht gefunden")
    if d.get("kind") != "midea" and not (d.get("kind") == "remote" and d.get("rkind") == "midea"):
        raise ShellyError("Das gibt es nur bei Klimaanlagen (Midea)")
    return d


def midea_details(dev_id: str) -> dict:
    d = _midea_dev(dev_id)
    try:
        if d.get("kind") == "remote":                      # Klimaanlage einer fremden Instanz: der Geber fuehrt es mit seinem Zugang aus
            import share
            return share.ac_details(d)
        return midea.details(d)
    except (midea.MideaError, ValueError) as e:
        raise ShellyError(str(e))
    except Exception as e:                                 # noqa: BLE001
        if e.__class__.__name__ == "ShareError":
            raise ShellyError(str(e))
        raise


def midea_set(dev_id: str, **kw) -> dict:
    """Modus, Solltemperatur, Luefter, Schwenken, Ein/Aus (power) und eco setzen - nur die genannten."""
    d = _midea_dev(dev_id)
    if d.get("switchable") is False:
        raise ShellyError("Dieses Gerät ist nur zur Überwachung eingestellt und nicht schaltbar")
    try:
        if d.get("kind") == "remote":
            import share
            return share.ac_set(d, **kw)
        return midea.set_params(d, **kw)
    except midea.MideaError as e:
        raise ShellyError(str(e))
    except Exception as e:                                 # noqa: BLE001
        if e.__class__.__name__ == "ShareError":
            raise ShellyError(str(e))
        raise


# ---------------------------------------------------------------- Homematic / HomematicIP (ueber die OpenCCU)
def homematic_scan() -> list[dict]:
    """Schaltbare Kanaele (Schalter + Dimmer) der CCU. Bereits angelegte sind mit known=True markiert."""
    known = {d["id"] for d in load_devices() if d.get("kind") == "homematic"}
    try:
        return homematic.discover(known)
    except homematic.HomematicError as e:
        raise ShellyError(str(e))


def add_homematic(addresses: list[str]) -> list[dict]:
    """Legt die gewaehlten CCU-Kanaele an (schon vorhandene bleiben unveraendert)."""
    try:
        entries = homematic.build_entries(addresses)
    except homematic.HomematicError as e:
        raise ShellyError(str(e))
    items = load_devices()
    have = {d["id"] for d in items}
    added = []
    for entry in entries:
        if entry["id"] in have:
            continue
        entry.update({"show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5})
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(entry)
        added.append(entry)
    _save(items)
    return added


def zigbee_scan() -> list[dict]:
    """Lichter/Steckdosen des Zigbee-Gateways. Bereits angelegte sind mit known=True markiert."""
    known = {d["id"] for d in load_devices() if d.get("kind") == "zigbee"}
    try:
        return zigbee.discover(known)
    except zigbee.ZigbeeError as e:
        raise ShellyError(str(e))


def add_zigbee(ids: list[str]) -> list[dict]:
    try:
        entries = zigbee.build_entries(ids)
    except zigbee.ZigbeeError as e:
        raise ShellyError(str(e))
    items = load_devices()
    have = {d["id"] for d in items}
    added = []
    for entry in entries:
        if entry["id"] in have:
            continue
        entry.update({"show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5})
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(entry)
        added.append(entry)
    _save(items)
    return added


# ---------------------------------------------------------------- Tuya (Gosund & Co.)
def tuya_scan(networks: list[str] | None = None) -> list[dict]:
    """Tuya-Geraete (Cloud-Schluessel + LAN-Suche). Aktualisiert dabei die IPs bekannter Geraete."""
    items = load_devices()
    known = {d["dev_id"] for d in items if d.get("kind") == "tuya"}
    try:
        found = tuya.discover(known, networks)
    except tuya.TuyaError as e:
        raise ShellyError(str(e))
    by_id = {f["dev_id"]: f for f in found}
    changed = False
    for d in items:
        f = by_id.get(d.get("dev_id")) if d.get("kind") == "tuya" else None
        if f and f["ip"] and (f["ip"] != d.get("ip") or (f["version"] and f["version"] != d.get("version"))):
            d["ip"], d["version"] = f["ip"], f["version"] or d.get("version")
            changed = True
    if changed:
        _save(items)
    return found


def add_tuya(dev_id: str, ip: str = "") -> dict:
    try:
        entry = tuya.build_entry(dev_id, ip)
    except tuya.TuyaError as e:
        raise ShellyError(str(e))
    entry["id"] = f"tuya-{dev_id}-{entry['dp']}"
    entry["mac"] = None
    items = load_devices()
    if any(d["id"] == entry["id"] for d in items):
        raise ShellyError("Gerät ist schon angelegt")
    entry.update({"icon": DEFAULT_ICON, "show": False, "auto": False, "power_w": 0,
                  "min_on_min": 5, "min_off_min": 5})
    entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
    items.append(entry)
    _save(items)
    return {k: v for k, v in entry.items() if k not in ("local_key", "token", "key", "cloud_password", "cloud_account")}


def _num(v, lo, hi, what):
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        raise ShellyError(f"{what}: ungültiger Wert")
    if not lo <= n <= hi:
        raise ShellyError(f"{what}: erlaubt sind {lo} bis {hi}")
    return n


def update(dev_id: str, name: str | None = None, icon: str | None = None,
           show: bool | None = None, auto: bool | None = None, power_w=None,
           min_on_min=None, min_off_min=None, switchable: bool | None = None) -> bool:
    """Name, Symbol, Dashboard-Sichtbarkeit, Schaltbarkeit und Ueberschuss-Automatik eines Geraets aendern."""
    if icon is not None and icon not in ICONS:
        raise ShellyError("Unbekanntes Symbol")
    items = load_devices()
    for d in items:
        if d["id"] == dev_id:
            if power_w is not None:
                d["power_w"] = _num(power_w, 0, 20000, "Leistung (W)")
            if min_on_min is not None:
                d["min_on_min"] = _num(min_on_min, 0, 1440, "Mindest-Einschaltdauer")
            if min_off_min is not None:
                d["min_off_min"] = _num(min_off_min, 0, 1440, "Mindest-Pause")
            sw = d.get("switchable", True) if switchable is None else bool(switchable)
            if auto and not sw:
                raise ShellyError("Nur-Überwachung: ein nicht schaltbares Gerät kann nicht in der Automatik verwendet werden")
            d["switchable"] = sw
            if not sw:
                d["auto"] = False               # Nur-Ueberwachung: nie automatisch schalten
            if name is not None:
                d["name"] = name.strip()[:60] or d["name"]
            if icon is not None:
                d["icon"] = icon
            if show is not None:
                d["show"] = bool(show)
            if auto is not None and sw:
                d["auto"] = bool(auto)
                if auto and not d.get("prio"):      # neu in der Automatik: ans Ende der Prioritaet
                    d["prio"] = max([x.get("prio") or 0 for x in items]) + 1
            _save(items)
            return True
    return False


def set_pin(dev_id: str, pin: str | None) -> bool:
    """Sicherheits-PIN (4 Ziffern) fuer die Bedienung am Dashboard setzen/entfernen - fuer alle Geraete gleich, egal von welchem System."""
    if pin:
        try:
            pins.validate(pin)
        except pins.PinError as e:
            raise ShellyError(str(e))
    items = load_devices()
    for d in items:
        if d["id"] == dev_id:
            pins.apply(d, pin)
            _save(items)
            return True
    return False


def has_pin(dev_id: str) -> bool:
    d = _find(dev_id)
    return bool(d and d.get("pin_hash"))


def check_pin(dev_id: str, pin) -> bool:
    d = _find(dev_id)
    return True if not d else pins.check(d, pin)


def reorder(ids: list[str]) -> None:
    """Neue Reihenfolge fuer die genannten Geraete. Sie belegen nur die Plaetze, die sie
    schon hatten - nicht genannte (z.B. nicht aufs Dashboard freigegebene) behalten ihre Position."""
    items = load_devices()
    by_id = {d["id"]: d for d in items}
    ids = [i for i in ids if i in by_id]
    slots = sorted(n for n, d in enumerate(items) if d["id"] in set(ids))
    for slot, i in zip(slots, ids):
        items[slot] = by_id[i]
    _save(items)


def reorder_auto(ids: list[str]) -> None:
    """Prioritaet in der Ueberschuss-Automatik (unabhaengig von der Dashboard-Reihenfolge)."""
    items = load_devices()
    by_id = {d["id"]: d for d in items}
    for n, i in enumerate(i for i in ids if i in by_id):
        by_id[i]["prio"] = n + 1
    _save(items)


def remove(dev_id: str) -> bool:
    items = load_devices()
    keep = [d for d in items if d["id"] != dev_id]
    if len(keep) == len(items):
        return False
    _save(keep)
    return True


# ---------------------------------------------------------------- Status/Schalten
def _auth(d: dict):
    return (d.get("user"), d.get("password")) if d.get("password") else None


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': W|None}"""
    if d.get("kind") == "remote":                          # geteiltes Geraet einer fremden BlueNexus-Instanz (share.py)
        import share
        return share.status(d)
    if d.get("kind") == "tuya":
        return tuya.status(d)
    if d.get("kind") == "tasmota":
        return tasmota.status(d)
    if d.get("kind") == "wled":
        return wled.status(d)
    if d.get("kind") == "midea":
        return midea.status(d)
    if d.get("kind") == "homematic":
        return homematic.status(d)
    if d.get("kind") == "zigbee":
        return zigbee.status(d)
    try:
        if d["gen"] >= 2:
            st = _get(d["ip"], f"/rpc/Switch.GetStatus?id={d['channel']}", CALL_TIMEOUT)
            power = st.get("apower")
            return {"online": True, "on": bool(st.get("output")),
                    "power": None if power is None else round(float(power), 1)}
        st = _get(d["ip"], "/status", CALL_TIMEOUT, _auth(d))
        relay = st["relays"][d["channel"]]
        meters = st.get("meters") or []
        power = meters[d["channel"]].get("power") if d["channel"] < len(meters) else None
        return {"online": True, "on": bool(relay.get("ison")),
                "power": None if power is None else round(float(power), 1)}
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return {"online": False, "on": None, "power": None}


def set_state(dev_id: str, on: bool, timer_s: int | None = None) -> dict:
    """Schaltet ein Geraet. `timer_s` (nur beim Einschalten; Shelly, Tasmota, Homematic): eingebauter Rueckschalt-Timer des
    Geraets in Sekunden - nach Ablauf schaltet das Geraet von selbst wieder aus (0 = laufenden Timer aufheben)."""
    d = _find(dev_id)
    if not d:
        raise ShellyError("Gerät nicht gefunden")
    if d.get("switchable") is False:
        raise ShellyError("Dieses Gerät ist nur zur Überwachung eingestellt und nicht schaltbar")
    if d.get("kind") == "remote":
        import share
        try:
            share.set_state(d, on, timer_s)
        except share.ShareError as e:
            raise ShellyError(str(e))
        return status(d)
    if d.get("kind") == "tuya":
        try:
            return tuya.set_state(d, on)
        except tuya.TuyaError as e:
            raise ShellyError(str(e))
    if d.get("kind") == "homematic":
        try:
            return homematic.set_state(d, on, timer_s)
        except homematic.HomematicError as e:
            raise ShellyError(str(e))
    if d.get("kind") == "zigbee":
        try:
            return zigbee.set_state(d, on, timer_s)
        except zigbee.ZigbeeError as e:
            raise ShellyError(str(e))
    if d.get("kind") == "midea":
        try:
            midea.set_state(d, on, timer_s)
        except midea.MideaError as e:
            raise ShellyError(str(e))
        return status(d)
    if d.get("kind") == "wled":
        try:
            wled.set_state(d, on, timer_s)
        except wled.WledError as e:
            raise ShellyError(str(e))
        return status(d)
    if d.get("kind") == "tasmota":
        try:
            tasmota.set_state(d, on, timer_s)
        except tasmota.TasmotaError as e:
            raise ShellyError(str(e))
        return status(d)
    try:
        if d["gen"] >= 2:
            # Gen2/3 kennen kein "Timer 0 = aus" (toggle_after=0 wird mit HTTP 500 abgelehnt, am Plus 1PM geprueft) -> ohne Timer schalten
            extra = f"&toggle_after={int(timer_s)}" if on and timer_s else ""
            _get(d["ip"], f"/rpc/Switch.Set?id={d['channel']}&on={'true' if on else 'false'}{extra}",
                 CALL_TIMEOUT)
        else:
            extra = f"&timer={int(timer_s)}" if on and timer_s is not None else ""
            _get(d["ip"], f"/relay/{d['channel']}?turn={'on' if on else 'off'}{extra}",
                 CALL_TIMEOUT, _auth(d))
    except (requests.RequestException, ValueError) as e:
        raise ShellyError(f"Schalten fehlgeschlagen: {e}")
    return status(d)


def list_with_status(only_shown: bool = False, ids: set | None = None, live: bool = True) -> list[dict]:
    """Angelegte Geraete inkl. Live-Status (parallel abgefragt). Ohne Passwort.
    only_shown: nur die fuers Dashboard freigegebenen (Reihenfolge wie gespeichert).
    live=False: keine Abfrage der Geraete (nur Stammdaten - sofort da, z. B. fuer den Regel-Editor)."""
    items = [d for d in load_devices() if d.get("show")] if only_shown else load_devices()
    if ids is not None:                                    # nur bestimmte Geraete abfragen (schnelle Regelrunde)
        items = [d for d in items if d["id"] in ids]
    if not items:
        return []
    if live:
        with ThreadPoolExecutor(max_workers=min(16, len(items))) as ex:
            states = list(ex.map(status, items))
    else:
        states = [{} for _ in items]
    out = []
    for d, st in zip(items, states):
        pub = {k: v for k, v in d.items() if k not in ("password", "user", "local_key", "pin_hash", "pin_salt", "token", "key", "cloud_password", "cloud_account")}
        pub["pin_set"] = bool(d.get("pin_hash"))
        pub.setdefault("icon", DEFAULT_ICON)
        pub.setdefault("show", False)
        pub.setdefault("auto", False)
        pub.setdefault("switchable", True)
        pub.setdefault("prio", 0)
        pub.setdefault("power_w", 0)
        pub.setdefault("min_on_min", 5)
        pub.setdefault("min_off_min", 5)
        pub.update(st)
        out.append(pub)
    return out


def users_registry():
    """(laden, speichern) fuer die Sichtbarkeit pro Benutzer (siehe visibility.py)."""
    return load_devices, _save


def set_brightness(dev_id: str, percent) -> int:
    """Helligkeit (1-100 %) eines WLED-Geraets; schaltet es dabei ein."""
    d = _find(dev_id)
    if not d:
        raise ShellyError("Gerät nicht gefunden")
    if d.get("kind") != "wled":
        raise ShellyError("Helligkeit gibt es nur bei WLED-Geräten")
    if d.get("switchable") is False:
        raise ShellyError("Dieses Gerät ist nur zur Überwachung eingestellt und nicht schaltbar")
    try:
        return wled.set_brightness(d, percent)
    except wled.WledError as e:
        raise ShellyError(str(e))


def _wled_dev(dev_id: str) -> dict:
    d = _find(dev_id)
    if not d:
        raise ShellyError("Gerät nicht gefunden")
    if d.get("kind") != "wled":
        raise ShellyError("Das gibt es nur bei WLED-Geräten")
    return d


def wled_details(dev_id: str) -> dict:
    try:
        return wled.details(_wled_dev(dev_id))
    except wled.WledError as e:
        raise ShellyError(str(e))


def wled_save_preset(dev_id: str, name) -> dict:
    d = _wled_dev(dev_id)
    try:
        return wled.save_preset(d, name)
    except wled.WledError as e:
        raise ShellyError(str(e))


def wled_apply(dev_id: str, mode: str, preset=None, color=None, brightness=None) -> str:
    """Schritt aus einer Regel: Voreinstellung aufrufen ODER Farbe (+ optional Helligkeit) setzen. Rueckgabe: Beschreibung fuers Logbuch."""
    if mode == "preset":
        wled_set(dev_id, preset=preset)
        return f"Voreinstellung {int(preset)}"
    wled_set(dev_id, color=color)
    if brightness not in (None, ""):
        set_brightness(dev_id, brightness)
    return f"Farbe {color}" + (f", Helligkeit {int(brightness)} %" if brightness not in (None, "") else "")


def wled_set(dev_id: str, color=None, effect=None, preset=None, palette=None) -> dict:
    """Farbe, Effekt oder Voreinstellung eines WLED-Geraets setzen (es wird eingeschaltet)."""
    d = _wled_dev(dev_id)
    if d.get("switchable") is False:
        raise ShellyError("Dieses Gerät ist nur zur Überwachung eingestellt und nicht schaltbar")
    try:
        if color is not None:
            return {"color": wled.set_color(d, color)}
        if effect is not None:
            return {"effect": wled.set_effect(d, effect)}
        if palette is not None:
            return {"palette": wled.set_palette(d, palette)}
        if preset is not None:
            return {"preset": wled.set_preset(d, preset)}
    except wled.WledError as e:
        raise ShellyError(str(e))
    raise ShellyError("Nichts zu setzen (Farbe, Effekt, Palette oder Voreinstellung)")
