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
import re
import socket
import threading
import time
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


def tasmota_sensor_scan(extra_networks: list[str] | None = None, ip: str | None = None) -> list[dict]:
    """Messwerte aller Tasmota-Geraete im Netz (auch ohne Relais, z. B. Selbstbau mit DS18B20) zum Anlegen als Sensoren.
    Mit `ip`: nur dieses eine Geraet, mit genauer Fehlermeldung (falls die Suche es nicht findet)."""
    import homematic
    known_ids = {s["id"] for s in homematic.load_sensors()}
    pw = {d.get("mac"): d.get("password") for d in load_devices() if d.get("kind") == "tasmota" and d.get("password")}
    if ip:
        ip = check_ip(ip)
        auth = None
        info = tasmota.probe(ip, 4.0, auth)
        if not info:
            raise ShellyError("Unter dieser Adresse antwortet kein Tasmota-Gerät (Adresse stimmt? Gerät erreichbar?)")
        if info.get("auth"):
            mac_pw = next((d.get("password") for d in load_devices() if d.get("kind") == "tasmota" and d.get("ip") == ip and d.get("password")), "")
            info = tasmota.probe(ip, 4.0, ("admin", mac_pw)) if mac_pw else None
            if not info or info.get("auth"):
                raise ShellyError("Das Gerät ist passwortgeschützt. Messwerte lassen sich nur lesen, wenn es auch als Schalter mit Passwort angelegt ist oder in Tasmota kein Passwort (WebPassword) gesetzt ist.")
        found = [info]
    else:
        hosts = _scan_hosts(None, extra_networks)
        for d in load_devices():                                 # bekannte Geraete auch ausserhalb der durchsuchten Netze
            if d.get("kind") == "tasmota" and d.get("ip") and d["ip"] not in hosts:
                hosts.append(d["ip"])
        with ThreadPoolExecutor(max_workers=48) as ex:
            found = [r for r in ex.map(lambda h: tasmota.probe(h, 2.0), hosts) if r]          # laenger warten als bei der Geraetesuche: Selbstbauten antworten oft langsam
    out = []
    for f in found:
        auth = ("admin", pw[f["mac"]]) if f.get("auth") and pw.get(f["mac"]) else None
        if f.get("auth"):
            f = tasmota.probe(f["ip"], CALL_TIMEOUT, auth) if auth else None
        if not f or f.get("auth"):
            continue
        try:
            vals = tasmota.sensor_metrics(f["ip"], 4.0 if ip else CALL_TIMEOUT, auth)
        except tasmota.TasmotaError as e:
            if ip:
                raise ShellyError(f"Das Gerät antwortet nicht auf die Messwert-Abfrage ({e})")
            continue
        if ip and not vals:
            raise ShellyError("Das Gerät meldet keine Messwerte (kein Fühler erkannt). In Tasmota unter Konfiguration → Gerät konfigurieren den Fühler (z. B. DS18B20) einem Pin zuordnen.")
        for dp in sorted(vals):
            probe_name, key = dp.rsplit(".", 1)
            kind, label, unit = tasmota._METRICS[key]
            sid = "tasS-" + f["mac"] + "-" + re.sub(r"[^A-Za-z0-9]+", "-", dp).strip("-")
            out.append({"id": sid, "kind": kind, "address": f["mac"], "interface": "Tasmota", "datapoint": dp, "unit": unit, "binary": False,
                        "model": f["model"] + " · " + f["ip"], "room": "", "ip": f["ip"], "source": "tasmota",
                        "name": f["name"] + " – " + ("" if probe_name == "ENERGY" else probe_name + " ") + label,
                        "known": sid in known_ids, "value": vals[dp]})
    out.sort(key=lambda x: (x["model"], x["name"]))
    _sensor_scan.clear()
    _sensor_scan.update({x["id"]: x for x in out})
    return out


_sensor_scan: dict = {}


def add_tasmota_sensors(ids: list[str]) -> list[dict]:
    import homematic
    if any(i not in _sensor_scan for i in ids):
        raise ShellyError("Bitte zuerst neu suchen")
    items = homematic.load_sensors()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _sensor_scan[i]
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "kind", "address", "interface", "datapoint", "unit", "binary", "model", "room", "name", "source", "ip")}
        item["model"] = item["model"].split(" · ")[0]
        item["users"] = []                                        # neu: zunaechst nur fuer Administratoren sichtbar
        items.append(item)
        added.append(item)
    if added:
        homematic._save_sensors(items)
    return added


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


def midea_cloud_renew(dev_id: str, account: str, password: str) -> int:
    """Neue NetHome-Plus-Zugangsdaten (E-Mail/Passwort) fuer eine Cloud-Klimaanlage und alle anderen Cloud-Klimaanlagen desselben Kontos.
    Die Zugangsdaten werden vorher mit einer echten Anmeldung geprueft (dabei wird die Anlage des Kontos gefunden). Gibt die Zahl der Geraete zurueck."""
    d = _midea_dev(dev_id)
    if d.get("kind") != "midea" or not d.get("cloud"):
        raise ShellyError("Das gibt es nur bei Klimaanlagen, die über die Midea-Cloud laufen")
    account, password = (account or "").strip(), password or ""
    if not account or not password:
        raise ShellyError("E-Mail und Passwort des NetHome-Plus-Kontos eingeben")
    midea.cloud_forget({account})                                      # nicht eine alte, noch gemerkte Anmeldung mit anderem Passwort wiederverwenden
    try:
        found = midea._cloud_list(account, password)                 # echte Anmeldung (von Hand: ohne Wartezeit)
    except midea.MideaError as e:
        raise ShellyError(str(e))
    if int(d.get("device_id", 0)) not in {int(x["device_id"]) for x in found}:
        raise ShellyError("Diese Klimaanlage gehört nicht zu diesem Konto – anderes NetHome-Plus-Konto?")
    old = d.get("cloud_account")
    items, hit = load_devices(), []
    for x in items:
        if x.get("kind") == "midea" and x.get("cloud") and x.get("cloud_account") == old:
            x["cloud_account"], x["cloud_password"] = account, password
            hit.append(x["id"])
    _save(items)
    midea.cloud_forget({old, account}, hit)
    return len(hit)


def midea_to_local(dev_id: str, region=None, account=None, password=None) -> dict:
    """Cloud-Klimaanlagen eines Kontos auf lokale Steuerung umstellen (einmalige Anmeldung fuer Token/Schluessel, danach nie wieder Cloud).
    ID, Name, Raum, Regeln, Freigaben und Dashboard bleiben erhalten."""
    d = _midea_dev(dev_id)
    if d.get("kind") != "midea" or not d.get("cloud"):
        raise ShellyError("Diese Klimaanlage läuft schon lokal")
    acc, pw = d.get("cloud_account"), d.get("cloud_password")
    new_acc, new_pw = (account or "").strip(), password or ""            # neu eingegeben (z. B. nach Passwort-Reset), sonst die gespeicherten
    items = load_devices()
    group = [x for x in items if x.get("kind") == "midea" and x.get("cloud") and x.get("cloud_account") == acc]
    try:
        res = midea.local_keys(region or midea.DEFAULT_REGION, new_acc or acc, new_pw or pw, [x["device_id"] for x in group])
    except midea.MideaError as e:
        raise ShellyError(str(e))
    done, missing = [], []
    for x in group:
        r = res.get(int(x["device_id"]))
        if not r:
            missing.append(x.get("name") or x["id"])
            continue
        x.update(r)
        x["cloud"] = False
        x.pop("cloud_account", None)
        x.pop("cloud_password", None)
        done.append(x["id"])
    if done:
        _save(items)
        midea.cloud_forget(set() if missing else {acc}, done)
    return {"done": len(done), "missing": missing}


def midea_rekey(dev_id: str, account: str, password: str, region=None) -> dict:
    """Neue Token/Schluessel fuer eine lokale Klimaanlage (z. B. nach neuem Koppeln in der App). IP wird dabei mit aktualisiert."""
    d = _midea_dev(dev_id)
    if d.get("kind") != "midea" or d.get("cloud"):
        raise ShellyError("Das gibt es nur bei lokal gesteuerten Klimaanlagen")
    account, password = (account or "").strip(), password or ""
    if not account or not password:
        raise ShellyError("E-Mail und Passwort des MSmartHome-Kontos eingeben")
    try:
        res = midea.local_keys(region or midea.DEFAULT_REGION, account, password, [d["device_id"]])
    except midea.MideaError as e:
        raise ShellyError(str(e))
    r = res.get(int(d["device_id"]))
    if not r:
        raise ShellyError("Kein Schlüssel – ist die Anlage in diesem MSmartHome-Konto eingetragen?")
    items = load_devices()
    for x in items:
        if x["id"] == dev_id:
            x.update(r)
    _save(items)
    midea.cloud_forget(set(), [dev_id])                                # neue Verbindung baut _get_dev beim naechsten Zugriff (schliesst die alte)
    return {"ip": r["ip"]}


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
           min_on_min=None, min_off_min=None, switchable: bool | None = None, ip: str | None = None) -> bool:
    """Name, Symbol, Dashboard-Sichtbarkeit, Schaltbarkeit, Ueberschuss-Automatik und (bei Geraeten im Heimnetz) die IP-Adresse eines Geraets aendern."""
    if icon is not None and icon not in ICONS:
        raise ShellyError("Unbekanntes Symbol")
    new_ip = check_ip(ip) if ip is not None else None             # vorher pruefen: bei Fehler wird nichts veraendert
    items = load_devices()
    for d in items:
        if d["id"] == dev_id:
            if new_ip is not None:
                if d.get("kind") == "remote" or d.get("cloud") or not d.get("ip"):
                    raise ShellyError("Dieses Gerät hat keine eigene IP-Adresse (Cloud, Gateway oder geteilt) – hier gibt es nichts zu ändern")
                same = [x for x in items if x is d or (d.get("mac") and x.get("mac") == d.get("mac") and x.get("kind") == d.get("kind"))]       # mehrere Kanaele eines Geraets teilen die Adresse
                for x in same:
                    x["ip"] = new_ip
                if d.get("kind") == "tasmota" and d.get("mac"):               # Messwert-Sensoren desselben Geraets folgen der neuen Adresse
                    import homematic
                    sens = homematic.load_sensors()
                    moved = [s for s in sens if s.get("source") == "tasmota" and s.get("address") == d["mac"]]
                    for s in moved:
                        s["ip"] = new_ip
                    if moved:
                        homematic._save_sensors(sens)
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


_down: dict = {}                       # Geraete-ID -> (Ruhe bis, letzter Offline-Zustand, Fehlversuche in Folge): kurz nicht neu versuchen
DOWN_BACKOFF_S = 12.0                  # nach dem 1. Fehlschlag; verdoppelt sich je weiterem Fehlschlag bis DOWN_BACKOFF_MAX_S
DOWN_BACKOFF_MAX_S = 60.0
_st_cache: dict = {}                   # Geraete-ID -> (Zeit, Zustand): letzter bekannter Zustand fuer die Oberflaeche
_st_bg: set = set()                    # Geraete, die gerade im Hintergrund aufgefrischt werden
_st_lock = threading.Lock()
_st_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="shelly-status")


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': W|None}. Ein Geraet, das gerade nicht geantwortet hat, wird fuer DOWN_BACKOFF_S Sekunden nicht erneut
    abgefragt (sonst wartet JEDER Abruf - Dashboard, Geraeteliste, Regeln - jedes Mal die ganze Zeitueberschreitung ab)."""
    key = d.get("id")
    hit = _down.get(key)
    if hit and hit[0] > time.time():
        return dict(hit[1])
    st = _status_live(d)
    if key is not None:
        if st.get("online") is False:
            fails = (hit[2] if hit else 0) + 1
            _down[key] = (time.time() + min(DOWN_BACKOFF_MAX_S, DOWN_BACKOFF_S * 2 ** (fails - 1)), dict(st), fails)
        else:
            _down.pop(key, None)
        _st_cache[key] = (time.time(), dict(st))
    return st


STALE_OK_S = 120.0


def _refresh_bg(d: dict) -> None:
    key = d.get("id")
    with _st_lock:
        if key in _st_bg:
            return
        _st_bg.add(key)

    def run():
        try:
            status(d)
        except Exception:                                     # noqa: BLE001
            pass
        finally:
            with _st_lock:
                _st_bg.discard(key)
    _st_pool.submit(run)


def status_cached(d: dict, max_age: float = 5.0) -> dict:
    """Zustand fuer die Oberflaeche, ohne auf langsame oder ausgefallene Geraete zu warten: ist der letzte bekannte Zustand juenger als max_age,
    wird er genommen; ist er aelter (bis STALE_OK_S), kommt er sofort und das Geraet wird im Hintergrund aufgefrischt (die naechste Anzeige ist aktuell);
    erst ohne brauchbaren Stand wird wirklich gewartet. Regeln und Automatik fragen weiter live ab (status)."""
    key, now = d.get("id"), time.time()
    hit = _st_cache.get(key)
    if hit and now - hit[0] <= max_age:
        return dict(hit[1])
    if hit and now - hit[0] <= STALE_OK_S:
        _refresh_bg(d)
        st = dict(hit[1])
        st["stale"] = True                                    # Anzeige weiss: Aufrischung laeuft, gleich nochmal nachsehen
        return st
    return status(d)


def _status_live(d: dict) -> dict:
    """Fragt das Geraet wirklich ab."""
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
    _down.pop(dev_id, None)                                  # wer schaltet, will den echten Zustand sehen: Ruhezeit nach einem Offline-Befund aufheben
    _st_cache.pop(dev_id, None)                              # und der gemerkte Zustand gilt nicht mehr (naechste Anzeige fragt neu)
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
            return tasmota.set_state(d, on, timer_s)             # Zustand aus der Antwort des Befehls: kein zweiter Abruf (schont das Geraet, schnellere Rueckmeldung)
        except tasmota.TasmotaError as e:
            raise ShellyError(str(e))
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


SENSOR_PRESETS = {                                                    # Schluessel -> (Sensorart, "an" bedeutet Wahr?)
    "contact_closed": ("contact", False),      # an = geschlossen (Wahr = offen, deshalb umgekehrt)
    "contact_open": ("contact", True),
    "lock_locked": ("lock", True),
    "lock_unlocked": ("lock", False),
    "motion": ("motion", True),
    "presence": ("presence", True),
    "input": ("input", True),
}


def device_as_sensor(dev_id: str, preset: str, name: str | None = None, lock_switch: bool = True) -> dict:
    """Zustand eines Geraets (z. B. Tasmota-Relais, das nur den Torzustand meldet) zusaetzlich als Sensor anlegen: erscheint bei den Sensoren
    (Dashboard, Regeln, Logbuch) mit passenden Worten (offen/geschlossen ...). lock_switch: das Geraet danach nicht mehr schaltbar (nur Anzeige)."""
    import homematic
    if preset not in SENSOR_PRESETS:
        raise ShellyError("Unbekannte Art")
    items = load_devices()
    d = next((x for x in items if x["id"] == dev_id), None)
    if not d or d.get("kind") == "remote":
        raise ShellyError("Gerät nicht gefunden (oder von einer anderen Anlage geteilt)")
    sid = "devS-" + dev_id
    sens = homematic.load_sensors()
    if any(s["id"] == sid for s in sens):
        raise ShellyError("Für dieses Gerät gibt es schon einen Sensor")
    kind, on_true = SENSOR_PRESETS[preset]
    nm = (name or "").strip()[:60] or d.get("name") or dev_id
    sen = {"id": sid, "kind": kind, "source": "device", "address": dev_id, "interface": "device", "datapoint": "", "binary": True, "unit": "", "model": d.get("model") or "Gerät",
           "room": "", "name": nm, "show": True, "users": []}
    if kind == "contact":
        sen["invert"] = not on_true               # Wahr bedeutet "offen"; "an = geschlossen" heisst: Zustand an -> Sensor "geschlossen" = umkehren
    elif not on_true:
        sen["invert"] = True
    sens.append(sen)
    homematic._save_sensors(sens)
    d["as_sensor"] = sid
    if lock_switch:
        d["switchable"] = False
    _save(items)
    return sen


def sensor_preset_of(sen: dict) -> str:
    """Welche Auswahl (Preset) beschreibt diesen Sensor? (fuer das Aendern-Formular)"""
    kind, inv = sen.get("kind"), bool(sen.get("invert"))
    if kind == "contact":
        return "contact_closed" if inv else "contact_open"
    if kind == "lock":
        return "lock_unlocked" if inv else "lock_locked"
    return kind if kind in SENSOR_PRESETS else "input"


def device_sensor_update(dev_id: str, preset: str | None = None, name: str | None = None) -> dict:
    """Bedeutung/Name des zu einem Geraet angelegten Sensors aendern."""
    import homematic
    d = _find(dev_id)
    sens = homematic.load_sensors()
    sen = next((s for s in sens if s["id"] == (d or {}).get("as_sensor")), None)
    if not d or not sen:
        raise ShellyError("Zu diesem Gerät gibt es keinen Sensor")
    if preset:
        if preset not in SENSOR_PRESETS:
            raise ShellyError("Unbekannte Art")
        kind, on_true = SENSOR_PRESETS[preset]
        sen["kind"] = kind
        sen.pop("invert", None)
        if kind == "contact":
            sen["invert"] = not on_true
        elif not on_true:
            sen["invert"] = True
    if name is not None and name.strip():
        sen["name"] = name.strip()[:60]
    homematic._save_sensors(sens)
    homematic._value_cache.pop(sen["id"], None)
    return sen


def device_sensor_remove(dev_id: str, unlock: bool = True) -> None:
    """Den zu einem Geraet angelegten Sensor entfernen; unlock: das Geraet wieder schaltbar machen."""
    import homematic
    items = load_devices()
    d = next((x for x in items if x["id"] == dev_id), None)
    if not d or not d.get("as_sensor"):
        raise ShellyError("Zu diesem Gerät gibt es keinen Sensor")
    homematic._save_sensors([s for s in homematic.load_sensors() if s["id"] != d["as_sensor"]])
    d.pop("as_sensor", None)
    if unlock:
        d["switchable"] = True
    _save(items)


def device_sensor_forget(sensor_id: str) -> None:
    """Der Sensor wurde in der Sensorliste entfernt: die Verknuepfung am Geraet loesen (das Geraet bleibt wie es ist)."""
    items = load_devices()
    ch = False
    for d in items:
        if d.get("as_sensor") == sensor_id:
            d.pop("as_sensor", None)
            ch = True
    if ch:
        _save(items)


def tasmota_hook_set(dev_id: str, base: str | None) -> dict:
    """Meldung von Schaltvorgaengen (z. B. Lichtschranke, Taster am Geraet) ein-/ausschalten. base = "IP:Port" von BlueNexus im Heimnetz (None = ausschalten).
    Gilt fuer alle Relaiskanaele desselben Geraets."""
    import secrets
    items = load_devices()
    d = next((x for x in items if x["id"] == dev_id), None)
    if not d or d.get("kind") != "tasmota":
        raise ShellyError("Das geht nur bei Tasmota-Geräten")
    same = [x for x in items if x.get("kind") == "tasmota" and x.get("mac") == d.get("mac")]
    try:
        if base is None:
            tasmota.hook_disable(d)
            for x in same:
                x.pop("hook", None)
        else:
            token = d.get("hook_token") or secrets.token_urlsafe(12)
            tasmota.hook_enable(d, d["mac"], sorted(int(x.get("channel") or 1) for x in same), base, token)
            for x in same:
                x["hook"], x["hook_token"] = True, token
    except tasmota.TasmotaError as e:
        raise ShellyError(f"Das Gerät hat die Einstellung abgelehnt: {e}")
    except requests.RequestException as e:
        raise ShellyError(f"Gerät nicht erreichbar: {e.__class__.__name__}")
    _save(items)
    return {"hook": base is not None}


def list_with_status(only_shown: bool = False, ids: set | None = None, live: bool = True, max_age: float | None = None) -> list[dict]:
    """Angelegte Geraete inkl. Live-Status (parallel abgefragt). Ohne Passwort.
    only_shown: nur die fuers Dashboard freigegebenen (Reihenfolge wie gespeichert).
    live=False: keine Abfrage der Geraete (nur Stammdaten - sofort da, z. B. fuer den Regel-Editor).
    max_age: fuer die Oberflaeche - letzter bekannter Zustand (hoechstens so alt) statt auf jedes Geraet zu warten, siehe status_cached."""
    items = [d for d in load_devices() if d.get("show")] if only_shown else load_devices()
    if ids is not None:                                    # nur bestimmte Geraete abfragen (schnelle Regelrunde)
        items = [d for d in items if d["id"] in ids]
    if not items:
        return []
    if live:
        with ThreadPoolExecutor(max_workers=min(16, len(items))) as ex:
            states = list(ex.map(status if max_age is None else (lambda d: status_cached(d, max_age)), items))
    else:
        states = [{} for _ in items]
    out = []
    for d, st in zip(items, states):
        pub = {k: v for k, v in d.items() if k not in ("password", "user", "local_key", "pin_hash", "pin_salt", "token", "key", "cloud_password", "cloud_account", "hook_token")}
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
