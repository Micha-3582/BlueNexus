"""
Geraeteuebersicht (nur Administratoren): alle Geraete mit IP-Adresse, die mit BlueNexus verbunden sind -
Steckdosen/Schalter (Shelly, Tasmota, WLED, Tuya), Klimaanlagen, Kameras, Zigbee-Gateways, CCU, Wake-on-LAN-Rechner,
Cerbo GX und Funkthermometer. Nur Stammdaten aus den eigenen Dateien: es wird nichts im Netz abgefragt und nie ein
Passwort, Schluessel oder Token ausgegeben.
"""
from __future__ import annotations

import ipaddress
import logging

log = logging.getLogger("inventory")

KIND_NAMES = {"shelly": "Shelly", "tasmota": "Tasmota", "wled": "WLED", "tuya": "Tuya / Smart Life", "midea": "Klimaanlage (Midea)", "esphome": "ESPHome (Taster)"}
# Geraete HINTER einer Zentrale: keine eigene IP-Adresse (Zigbee ueber das Gateway, Homematic ueber die CCU)
BEHIND = {"zigbee": ("Zigbee (über Gateway)", "über Gateway"), "homematic": ("Homematic (über CCU)", "Adresse")}


def _ip_only(host: str) -> str:
    """'http://192.168.2.22:80' / '192.168.2.22' -> '192.168.2.22' (alles andere unveraendert)."""
    h = (host or "").strip()
    for s in ("https://", "http://"):
        if h.lower().startswith(s):
            h = h[len(s):]
    h = h.split("/")[0]
    if h.count(":") == 1:
        h = h.split(":")[0]
    return h


def _sort_key(ip: str):
    try:
        return (0, int(ipaddress.ip_address(ip)))
    except ValueError:
        return (1, 0)


def collect() -> list[dict]:
    """[{typ, name, ip, mac, detail}] sortiert nach IP-Adresse; Adressen, die doppelt vorkommen, sind mit 'doppelt' markiert."""
    rows: list[dict] = []

    def add(typ: str, name: str, ip: str = "", mac: str = "", detail: str = "") -> None:
        rows.append({"typ": typ, "name": name or "–", "ip": _ip_only(ip), "mac": (mac or "").upper(), "detail": detail or ""})

    try:
        import shelly                                           # noqa: PLC0415
        for d in shelly.load_devices():
            kind = d.get("kind") or "shelly"
            if kind in BEHIND:                                  # das Feld "ip" ist hier die Gateway-Adresse bzw. die Geraete-Adresse, keine eigene IP
                typ, label = BEHIND[kind]
                add(typ, d.get("name") or d.get("id"), "", "", " · ".join(x for x in (f"{label} {d['ip']}" if d.get("ip") else "", d.get("model")) if x))
                continue
            det = [x for x in (d.get("model"), "Cloud-Anbindung" if d.get("cloud") else "") if x]
            add(KIND_NAMES.get(kind, kind), d.get("name") or d.get("id"), d.get("ip", ""), d.get("mac", ""), " · ".join(det))
    except Exception as e:                                      # noqa: BLE001 - eine Quelle darf die Liste nicht verhindern
        log.warning("Geraeteuebersicht: Geraete nicht lesbar: %s", e)
    try:
        import camera                                           # noqa: PLC0415
        for c in camera.load():
            add("Kamera", c.get("name") or c.get("id"), c.get("host", ""), "", c.get("kind", "reolink"))
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: Kameras nicht lesbar: %s", e)
    try:
        import zigbee                                           # noqa: PLC0415
        for g in zigbee.load_gateways():
            add("Zigbee-Gateway", g.get("name") or g.get("id"), g.get("host", ""))
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: Zigbee nicht lesbar: %s", e)
    try:
        import homematic                                        # noqa: PLC0415
        c = homematic.load_credentials()
        if c.get("host"):
            add("Homematic-Zentrale (CCU)", "CCU", c["host"])
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: CCU nicht lesbar: %s", e)
    try:
        import wol                                              # noqa: PLC0415
        for w in wol.load():
            add("Rechner (Wake-on-LAN)", w.get("name") or w.get("id"), w.get("ip", ""), w.get("mac", ""))
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: Wake-on-LAN nicht lesbar: %s", e)
    try:
        import store                                            # noqa: PLC0415
        cfg = store.load_config() or {}
        if cfg.get("cerbo_host"):
            add("Victron Cerbo GX", "Cerbo GX", cfg["cerbo_host"], "", "Modbus TCP")
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: Cerbo nicht lesbar: %s", e)
    try:
        import thermo                                           # noqa: PLC0415
        for t in thermo.load():
            add("Funkthermometer", t.get("name") or t.get("id"), "", "", "WLAN, meldet sich selbst – feste IP in UniFi vergeben, wenn gewünscht")
    except Exception as e:                                      # noqa: BLE001
        log.warning("Geraeteuebersicht: Thermometer nicht lesbar: %s", e)

    count: dict[str, int] = {}
    for r in rows:
        if r["ip"]:
            count[r["ip"]] = count.get(r["ip"], 0) + 1
    for r in rows:
        r["doppelt"] = bool(r["ip"]) and count.get(r["ip"], 0) > 1
    rows.sort(key=lambda r: (_sort_key(r["ip"]), r["typ"], r["name"].lower()))
    return rows
