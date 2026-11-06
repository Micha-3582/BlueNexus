"""
ESPHome im Geraeteregister: Geraete suchen, Eintraege anlegen, nach Neuflashen oder neuer IP-Adresse wieder zuordnen.
Taster (binary_sensor), Klimaanlagen (climate), Schalter/Relais (switch) und Messwerte (sensor).
Die Verbindung zum Geraet und seine Zustaende liegen in esphome.py; das Register selbst (laden, speichern, Status, Schalten) in shelly.py.
"""
from __future__ import annotations

import logging

import esphome
from shelly import ShellyError, _save, check_ip, load_devices

log = logging.getLogger("esphome_devices")


# ---------------------------------------------------------------- ESPHome (Hardware-Taster), siehe esphome.py
def esphome_scan(ip: str) -> list[dict]:
    """Eingaenge (Taster) eines ESPHome-Geraets unter dieser Adresse. Schon angelegte sind mit known=True markiert."""
    ip = check_ip(ip)
    try:
        info = esphome.probe(ip)
    except esphome.EsphomeError as e:
        raise ShellyError(str(e))
    relinked = esphome_relink(ip, info["entities"], info["title"])          # nach einem Neuflashen: alter Eintrag, neuer Name am Geraet -> wieder zuordnen
    if relinked:
        esphome.resync()
    items = load_devices()
    have = {d["id"] for d in items}
    reg = {d.get("entity") for d in items if d.get("kind") in ("esphome", "esphome_ac", "esphome_sw") and d.get("ip") == ip}
    again = {ent for _, ent in relinked}
    out = []
    for e in info["entities"]:
        if e["domain"] not in ("binary_sensor", "climate", "switch"):
            continue
        dev_id = esphome.entity_id(info["title"], e["entity"])
        ac = e["domain"] == "climate"
        out.append({"id": dev_id, "name": e["name"], "model": f"ESPHome · {info['title']}", "ip": ip, "entity": e["entity"],
                    "icon": "❄️" if ac else "🔌" if e["domain"] == "switch" else "🔘", "domain": e["domain"], "known": dev_id in have or e["entity"] in reg, "relinked": e["entity"] in again})
    if _esphome_follow_ip(ip, {x["id"] for x in out if x["known"]}, set()):
        esphome.resync()
    return out


def esphome_relink(ip: str, ents: list, title: str = "", fallback: bool = False, only=None) -> list:
    """Ordnet angelegte ESPHome-Eintraege (Taster und Messwerte) dieser Adresse, die das Geraet nicht mehr meldet, einem eindeutig passenden neuen Eintrag
    zu (z. B. nach neuer Firmware: "Taster" -> "Taster01 Taster"). Die Kennung bleibt - Regeln, Verlauf und Freigaben gehoeren weiter zu diesem Eintrag.
    ents: Eintraege des Geraets [{entity, name, domain, (uom)}]. fallback=True: bleibt genau ein Taster-Eintrag und ein Kandidat uebrig, werden sie
    gepaart (nur beim Hinzufuegen durch den Nutzer); only: nur diese Eintraege des Geraets kommen als Ziel in Frage. Gibt [(Kennung, neuer Eintrag)] zurueck."""
    import homematic
    done = []
    present = {e["entity"] for e in ents}
    items = load_devices()
    mine = [d for d in items if d.get("kind") in ("esphome", "esphome_ac", "esphome_sw") and d.get("ip") == ip]
    stale = [d for d in mine if d.get("entity") not in present]
    if stale:
        used = {d.get("entity") for d in mine}
        for dkind, dom in (("esphome", "binary_sensor"), ("esphome_ac", "climate"), ("esphome_sw", "switch")):         # Taster -> Eingang, Klimaanlage -> Klima-Entitaet, Schalter -> Schalter-Entitaet
            sk = [d for d in stale if d.get("kind") == dkind]
            if not sk:
                continue
            cands = [e for e in ents if e.get("domain") == dom and e["entity"] not in used and (only is None or e["entity"] in only)]
            for st, c in esphome.match_stale([{"id": d["id"], "entity": d.get("entity"), "name": d.get("name", "")} for d in sk], cands, fallback):
                for d in items:
                    if d["id"] == st["id"]:
                        d["entity"] = c["entity"]
                        if title:
                            d["model"] = f"ESPHome · {title}"
                        done.append((d["id"], c["entity"]))
        if done:
            _save(items)
    sens = homematic.load_sensors()
    smine = [x for x in sens if x.get("source") == "esphome" and x.get("ip") == ip]
    sstale = [x for x in smine if x.get("datapoint") not in present]
    if sstale:
        sused = {x.get("datapoint") for x in smine}
        scands = [e for e in ents if e.get("domain") == "sensor" and e["entity"] not in sused and (only is None or e["entity"] in only)
                  and ("uom" not in e or esphome.sensor_kind(e.get("uom", ""), e.get("name", "")) is not None)]
        changed = False
        for st, c in esphome.match_stale([{"id": x["id"], "entity": x.get("datapoint"), "name": x.get("name", "")} for x in sstale], scands):
            for x in sens:
                if x["id"] == st["id"]:
                    x["datapoint"] = c["entity"]
                    changed = True
                    done.append((x["id"], c["entity"]))
        if changed:
            homematic._save_sensors(sens)
    if done:
        log.info("ESPHome %s: %d Eintrag/Einträge neu zugeordnet (%s)", ip, len(done), ", ".join(f"{i} -> {e}" for i, e in done))
    return done


def _esphome_follow_ip(ip: str, dev_ids: set, sensor_ids: set) -> bool:
    """Hat ein schon angelegtes ESPHome-Geraet eine neue IP-Adresse (Router), genuegt es, es dort noch einmal zu suchen: die Eintraege folgen."""
    import homematic
    changed = False
    items = load_devices()
    for d in items:
        if d.get("kind") in ("esphome", "esphome_sw") and d["id"] in dev_ids and d.get("ip") != ip:
            d["ip"], changed = ip, True
    if changed:
        _save(items)
    sens, ch2 = homematic.load_sensors(), False
    for s in sens:
        if s.get("source") == "esphome" and s["id"] in sensor_ids and s.get("ip") != ip:
            s["ip"], ch2 = ip, True
    if ch2:
        homematic._save_sensors(sens)
    return changed or ch2


_esp_sensor_scan: dict = {}


def esphome_sensor_scan(ip: str) -> list[dict]:
    """Messwerte (Temperatur, Luftfeuchte, Leistung, Druck, Helligkeit, Spannung, Funkstaerke) eines ESPHome-Geraets. Schon angelegte sind mit known=True markiert."""
    import homematic
    ip = check_ip(ip)
    try:
        info = esphome.probe(ip)
    except esphome.EsphomeError as e:
        raise ShellyError(str(e))
    relinked = esphome_relink(ip, info["entities"], info["title"])
    if relinked:
        esphome.resync()
    sens_now = homematic.load_sensors()
    have = {s["id"] for s in sens_now}
    reg = {s.get("datapoint") for s in sens_now if s.get("source") == "esphome" and s.get("ip") == ip}
    out, skipped = [], 0
    for e in info["entities"]:
        if e["domain"] != "sensor":
            continue
        k = esphome.sensor_kind(e["uom"], e["name"])
        if k is None:
            skipped += 1
            continue
        kind, unit, conv = k
        sid = esphome.sensor_id(info["title"], e["entity"])
        v = e.get("value")
        if v is not None and conv:
            v = esphome._CONV[conv](v)
        out.append({"id": sid, "kind": kind, "address": info["title"], "interface": "ESPHome", "datapoint": e["entity"], "unit": unit, "binary": False,
                    "model": f"ESPHome · {info['title']}", "room": "", "ip": ip, "source": "esphome", "conv": conv or "",
                    "name": e["name"], "known": sid in have or e["entity"] in reg, "value": None if v is None else round(v, 1), "skipped": skipped})
    for x in out:
        x["skipped"] = skipped
    if _esphome_follow_ip(ip, set(), {x["id"] for x in out if x["known"]}):
        esphome.resync()
    _esp_sensor_scan.clear()
    _esp_sensor_scan.update({x["id"]: x for x in out})
    return out


def add_esphome_sensors(ids: list[str]) -> list[dict]:
    import homematic
    if not ids or any(i not in _esp_sensor_scan for i in ids):
        raise ShellyError("Bitte zuerst neu suchen")
    items = homematic.load_sensors()
    have = {s["id"] for s in items}
    added = []
    for i in ids:
        f = _esp_sensor_scan[i]
        if i in have:
            continue
        item = {k: f[k] for k in ("id", "kind", "address", "interface", "datapoint", "unit", "binary", "model", "room", "name", "source", "ip")}
        if f.get("conv"):
            item["conv"] = f["conv"]
        item["users"] = []                                        # neu: zunaechst nur fuer Administratoren sichtbar
        items.append(item)
        added.append(item)
        have.add(i)
    if added:
        homematic._save_sensors(items)
        esphome.resync()
    return added


def add_esphome(ip: str, ids: list[str]) -> list[dict]:
    """Legt die gewaehlten Eingaenge (Kennungen aus esphome_scan) als Geraete an. Der Zustand wird dabei frisch vom Geraet gelesen."""
    found = {f["id"]: f for f in esphome_scan(ip)}
    for dev_id in ids:
        if dev_id not in found:
            raise ShellyError("Dieser Eingang ist am Gerät nicht mehr zu finden – bitte noch einmal suchen")
    items = load_devices()
    have = {d["id"] for d in items}
    reg = {d.get("entity") for d in items if d.get("kind") in ("esphome", "esphome_ac", "esphome_sw") and d.get("ip") == ip}
    added = []
    want = [i for i in ids if i not in have and found[i]["entity"] not in reg and found[i].get("domain") not in ("climate", "switch")]
    if want:                                               # ein Eintrag, den das Geraet nicht mehr meldet, wird wieder verbunden statt doppelt angelegt
        rel = esphome_relink(ip, [{"entity": f["entity"], "name": f["name"], "domain": "binary_sensor"} for f in found.values()], "", True, {found[i]["entity"] for i in want})
        if rel:
            items = load_devices()
            have = {d["id"] for d in items}
            reg = {d.get("entity") for d in items if d.get("kind") in ("esphome", "esphome_ac", "esphome_sw") and d.get("ip") == ip}
            ids_re = {i for i, _ in rel}
            added.extend(d for d in items if d["id"] in ids_re)
    for dev_id in ids:
        f = found[dev_id]
        if dev_id in have or f["entity"] in reg:
            continue
        if f.get("domain") == "climate":              # Klimaanlage: schaltbarer Aktor, im Klimafenster/Regeln wie eine Midea-Anlage (rkind), aber lokal ueber ESPHome
            entry = {"id": dev_id, "kind": "esphome_ac", "rkind": "midea", "ip": f["ip"], "entity": f["entity"], "gen": 0, "channel": 0, "model": f["model"], "name": f["name"],
                     "icon": "❄️", "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "user": "", "password": "",
                     "switchable": True}
        elif f.get("domain") == "switch":             # Schalter/Relais: ganz normaler schaltbarer Aktor (Dashboard, Regeln, Automatik), lokal ueber ESPHome
            entry = {"id": dev_id, "kind": "esphome_sw", "ip": f["ip"], "entity": f["entity"], "gen": 0, "channel": 0, "model": f["model"], "name": f["name"],
                     "icon": "🔌", "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "user": "", "password": "",
                     "switchable": True}
        else:
            entry = {"id": dev_id, "kind": "esphome", "ip": f["ip"], "entity": f["entity"], "gen": 0, "channel": 0, "model": f["model"], "name": f["name"],
                     "icon": "🔘", "show": False, "auto": False, "power_w": 0, "min_on_min": 5, "min_off_min": 5, "user": "", "password": "",
                     "switchable": False}
        entry["users"] = []                         # neu angelegt: zunaechst nur fuer Administratoren sichtbar (siehe visibility.py)
        items.append(entry)
        added.append(entry)
        have.add(dev_id)
    _save(items)
    esphome.resync()
    return added
