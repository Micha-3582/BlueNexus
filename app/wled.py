"""
WLED-Geraete (LED-Streifen/-Controller mit WLED-Firmware) - lokal per JSON-Schnittstelle `http://<ip>/json/...` (keine Zusatzpakete, nur `requests`).

Ein Geraet = ein Eintrag (id = "wled-<mac>"). Schalten: {"on": true/false}; Helligkeit: {"bri": 1-255} (hier in Prozent 1-100).
Beim Einschalten behaelt WLED seine zuletzt eingestellte Helligkeit/Farbe/Effekt. Einen Rueckschalt-Timer gibt es hier nicht (timer_s wird ignoriert).
"""
from __future__ import annotations

import re
import threading
import time

import requests

CALL_TIMEOUT = 3.0
PROBE_TIMEOUT = 0.8


class WledError(Exception):
    pass


_locks: dict[str, threading.Lock] = {}
_names: dict[str, tuple] = {}                            # ip -> (Zeit, Effekte, Paletten): Namenslisten aendern sich nur mit der Firmware
NAMES_TTL_S = 3600.0
BUSY_CODES = (503, 429)                                  # WLED hat wenig Speicher: pro Zeit nur eine JSON-Anfrage, sonst "Service Unavailable"


def _req(method: str, ip: str, path: str, timeout: float, body=None, retries: int = 3):
    """Anfrage an eine Lampe. Anfragen an dieselbe Lampe laufen nacheinander; antwortet WLED beschaeftigt (503/429), wird mit Pause wiederholt."""
    with _locks.setdefault(ip, threading.Lock()):
        r = None
        for attempt in range(max(1, retries)):
            r = requests.request(method, f"http://{ip}{path}", json=body, timeout=timeout)
            if r.status_code not in BUSY_CODES:
                break
            if attempt < retries - 1:
                time.sleep(0.4 * (attempt + 1))
        r.raise_for_status()
        return r


def _get(ip: str, path: str, timeout: float, retries: int = 3) -> dict:
    r = _req("GET", ip, path, timeout, retries=retries)
    data = r.json()
    if not isinstance(data, dict):
        raise ValueError("keine JSON-Antwort")
    return data


def probe(ip: str, timeout: float = PROBE_TIMEOUT) -> dict | None:
    """Fragt /json/info ab. None = kein (erreichbares) WLED."""
    try:
        info = _get(ip, "/json/info", timeout, retries=1)
    except (requests.RequestException, ValueError):
        return None
    ver, mac = info.get("ver"), str(info.get("mac") or "").replace(":", "").upper()
    if not ver or not mac or not (str(info.get("brand") or "").upper() == "WLED" or "leds" in info):
        return None
    leds = info.get("leds") if isinstance(info.get("leds"), dict) else {}
    return {"ip": ip, "mac": mac, "name": str(info.get("name") or f"WLED-{mac[-6:]}"), "model": "WLED " + str(ver),
            "leds": int(leds.get("count") or 0)}


def status(d: dict) -> dict:
    """{'online': bool, 'on': bool|None, 'power': None, 'brightness': 1-100 | None}"""
    try:
        st = _get(d["ip"], "/json/state", CALL_TIMEOUT, retries=3)
        bri = st.get("bri")
        return {"online": True, "on": bool(st.get("on")), "power": None,
                "brightness": None if not isinstance(bri, (int, float)) else max(1, min(100, int(round(bri / 2.55))))}
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {"online": False, "on": None, "power": None}


def _post(d: dict, body: dict):
    try:
        _req("POST", d["ip"], "/json/state", CALL_TIMEOUT, body=body, retries=4)
    except requests.RequestException as e:
        raise WledError(f"Schalten fehlgeschlagen: {e}")


def _get_json(d: dict, path: str):
    try:
        return _req("GET", d["ip"], path, CALL_TIMEOUT * 2, retries=5).json()
    except (requests.RequestException, ValueError) as e:
        raise WledError(f"WLED nicht erreichbar: {e}")


def details(d: dict) -> dict:
    """Fuer die Bedienung: Effektliste, Voreinstellungen (Presets) und der aktuelle Zustand (Farbe, Effekt, Voreinstellung)."""
    hit = _names.get(d["ip"])
    partial = False
    if hit and time.time() - hit[0] < NAMES_TTL_S:
        effects, palettes = hit[1], hit[2]
    else:
        effects, palettes = (hit[1], hit[2]) if hit else ([], [])         # veraltete Liste ist besser als keine
        try:
            eff = _get_json(d, "/json/eff")
            effects = [{"id": i, "name": str(n)} for i, n in enumerate(eff if isinstance(eff, list) else []) if str(n) and str(n) != "RSVD"]
            try:
                pal = _get_json(d, "/json/pal")
                palettes = [{"id": i, "name": str(n)} for i, n in enumerate(pal if isinstance(pal, list) else []) if str(n)]
            except WledError:
                pass                                  # aeltere Firmware oder gerade beschaeftigt: ohne Palettenliste weiter
            _names[d["ip"]] = (time.time(), effects, palettes)
        except WledError:
            partial = not effects                     # Effektliste (gross) nicht erhalten: Farbe, Voreinstellungen und Helligkeit gehen trotzdem
    presets = []
    try:
        pj = _get_json(d, "/presets.json")
        for k, v in (pj.items() if isinstance(pj, dict) else []):
            if str(k).isdigit() and int(k) > 0 and isinstance(v, dict) and v.get("n"):
                presets.append({"id": int(k), "name": str(v["n"])})
    except WledError:
        pass                                          # aeltere Firmware ohne presets.json: nur Farbe/Effekte
    presets.sort(key=lambda p: p["name"].lower())
    st = _get_json(d, "/json/state")
    seg = (st.get("seg") or [{}])[0] if isinstance(st.get("seg"), list) and st.get("seg") else {}
    col = (seg.get("col") or [[255, 160, 0]])[0] if isinstance(seg.get("col"), list) and seg.get("col") else [255, 160, 0]
    try:
        hexcol = "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in col[:3])
    except (TypeError, ValueError):
        hexcol = "#ffa000"
    return {"partial": partial, "effects": effects, "palettes": palettes, "palette": seg.get("pal"), "presets": presets, "color": hexcol, "effect": seg.get("fx"), "preset": st.get("ps") if isinstance(st.get("ps"), int) and st.get("ps") > 0 else None}


def set_color(d: dict, hexcolor: str) -> str:
    """Farbe (#rrggbb) des Haupt-Segments; schaltet ein."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(hexcolor or "").strip())
    if not m:
        raise WledError("Farbe: Format #rrggbb erwartet")
    v = m.group(1)
    rgb = [int(v[i:i + 2], 16) for i in (0, 2, 4)]
    _post(d, {"on": True, "seg": [{"id": 0, "col": [rgb]}]})
    return "#" + v.lower()


def set_effect(d: dict, effect) -> int:
    try:
        fx = int(effect)
    except (TypeError, ValueError):
        raise WledError("Effekt: Nummer erwartet")
    if not 0 <= fx <= 255:
        raise WledError("Effekt: Nummer zwischen 0 und 255")
    _post(d, {"on": True, "seg": [{"id": 0, "fx": fx}]})
    return fx


def set_palette(d: dict, palette) -> int:
    try:
        pal = int(palette)
    except (TypeError, ValueError):
        raise WledError("Palette: Nummer erwartet")
    if not 0 <= pal <= 255:
        raise WledError("Palette: Nummer zwischen 0 und 255")
    _post(d, {"on": True, "seg": [{"id": 0, "pal": pal}]})
    return pal


def save_preset(d: dict, name: str) -> dict:
    """Speichert den AKTUELLEN Zustand der Lampe (Farbe, Effekt, Palette, Helligkeit) als Voreinstellung (Preset) in WLED.
    Gleicher Name = vorhandenes Preset ueberschreiben, sonst den kleinsten freien Platz (1-250) nehmen."""
    nm = str(name or "").strip()[:32]
    if not nm:
        raise WledError("Name für die Voreinstellung eingeben")
    used, same = set(), None
    try:
        pj = _get_json(d, "/presets.json")
        for k, v in (pj.items() if isinstance(pj, dict) else []):
            if str(k).isdigit() and int(k) > 0 and isinstance(v, dict) and v:
                used.add(int(k))
                if str(v.get("n") or "").strip().lower() == nm.lower():
                    same = int(k)
    except WledError:
        pass
    pid = same or next((i for i in range(1, 251) if i not in used), None)
    if pid is None:
        raise WledError("Alle 250 Plätze für Voreinstellungen sind belegt")
    _post(d, {"psave": pid, "n": nm, "ib": True, "sb": True})
    return {"preset": pid, "name": nm, "overwritten": bool(same)}


def set_preset(d: dict, preset) -> int:
    try:
        ps = int(preset)
    except (TypeError, ValueError):
        raise WledError("Voreinstellung: Nummer erwartet")
    if not 1 <= ps <= 250:
        raise WledError("Voreinstellung: Nummer zwischen 1 und 250")
    _post(d, {"on": True, "ps": ps})
    return ps


def set_state(d: dict, on: bool, timer_s: int | None = None):
    """Schaltet das Geraet (timer_s wird ignoriert - WLED hat hier keinen Rueckschalt-Timer)."""
    _post(d, {"on": bool(on)})


def set_brightness(d: dict, percent) -> int:
    """Helligkeit in Prozent (0-100; 0 = aus, sonst wird eingeschaltet). Rueckgabe: gesetzter Wert."""
    try:
        p = int(round(float(percent)))
    except (TypeError, ValueError):
        raise WledError("Helligkeit: Zahl von 0 bis 100 erwartet")
    if not 0 <= p <= 100:
        raise WledError("Helligkeit zwischen 0 und 100 %")
    if p == 0:                                      # 0 % = aus (die gespeicherte Helligkeit von WLED bleibt erhalten)
        _post(d, {"on": False})
        return 0
    _post(d, {"on": True, "bri": max(1, min(255, int(round(p * 2.55))))})
    return p
