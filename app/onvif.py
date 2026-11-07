"""
ONVIF-Ereignisse fuer Kameras OHNE Reolink-HTTP-Schnittstelle (z. B. Reolink Lumus 2K: nur Port 9000, RTSP 554 und ONVIF 8000).

Die Kamera meldet Bewegung und KI-Erkennungen (Person, Fahrzeug, Tier) als ONVIF-Ereignisse. BlueNexus haelt dazu pro Kamera ein Abo ("PullPoint") in einem
Hintergrund-Thread (mit Wiederverbindung und wachsender Wartezeit) und merkt sich den letzten Zustand. camera.motion_states() liefert diesen Zustand fuer
Kameras vom Typ RTSP; die vorhandenen Kamera-Sensoren (Regeln, Dashboard, Logbuch) lesen ihn wie bisher ab. Keine Zusatzpakete, nur `requests`.

Ablauf je Verbindung: Kamerauhr lesen (ohne Anmeldung, fuer den Zeitstempel der Anmeldung) -> Ereignisdienst erfragen (GetCapabilities) ->
CreatePullPointSubscription -> PullMessages (5 s Wartezeit) in einer Schleife. Die erste Antwort enthaelt den Anfangszustand aller Ereignisarten; welche
Ereignisarten das sind, bestimmt, welche Sensoren die Kamera anbietet ("support"). Anmeldung: WS-Security UsernameToken (Passwort-Digest).
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("onvif")

PORT = 8000
SUB_S = 900                  # Laufzeit des Abos; danach wird es neu angelegt
PULL_S = 5                   # Wartezeit je PullMessages
STALE_S = 40                 # laenger keine Antwort der Kamera -> "nicht erreichbar"
FIRST_WAIT_S = 8.0           # so lange wartet der erste Abruf auf den Anfangszustand
_ACTION_PULL = "http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest"
# Ereignisart (Ende des Themas) -> Schluessel wie bei camera.motion_states()
TOPICS = {"RuleEngine/CellMotionDetector/Motion": ("md", "IsMotion"), "RuleEngine/MyRuleDetector/PeopleDetect": ("people", "State"),
          "RuleEngine/MyRuleDetector/VehicleDetect": ("vehicle", "State"), "RuleEngine/MyRuleDetector/DogCatDetect": ("dog_cat", "State")}

_lock = threading.Lock()
_workers: dict[str, "_Worker"] = {}


class OnvifError(Exception):
    pass


def _header(user: str, password: str, off: float, action: str, to: str) -> str:
    nonce = secrets.token_bytes(16)
    created = (datetime.now(timezone.utc) + timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    dig = base64.b64encode(hashlib.sha1(nonce + created.encode() + password.encode()).digest()).decode()
    wsa = (f'<wsa:Action xmlns:wsa="http://www.w3.org/2005/08/addressing" s:mustUnderstand="1">{action}</wsa:Action>'
           f'<wsa:To xmlns:wsa="http://www.w3.org/2005/08/addressing" s:mustUnderstand="1">{to}</wsa:To>') if action else ""
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return ('<s:Header>' + wsa + '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken>'
            f'<wsse:Username>{esc(user)}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{dig}</wsse:Password>'
            f'<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>')


def _soap(url: str, body: str, item: dict, off: float = 0.0, auth: bool = True, action: str = "", timeout: float = 15) -> str:
    xml = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
           + (_header(item.get("user", ""), item.get("password", ""), off, action, url) if auth else "") + f"<s:Body>{body}</s:Body></s:Envelope>")
    try:
        r = requests.post(url, data=xml.encode(), headers={"Content-Type": "application/soap+xml; charset=utf-8"}, timeout=timeout)
    except requests.RequestException as e:
        raise OnvifError(f"Kamera nicht erreichbar ({e.__class__.__name__})")
    if r.status_code in (401, 403) or (r.status_code == 400 and "NotAuthorized" in r.text) or "Sender not Authorized" in r.text:
        raise OnvifError("Anmeldung an der Kamera fehlgeschlagen – Benutzer/Passwort prüfen")
    if r.status_code != 200:
        raise OnvifError(f"Die Kamera meldet einen Fehler (ONVIF HTTP {r.status_code})")
    return r.text


def parse_messages(xml: str) -> list[tuple[str, bool]]:
    """[(Schluessel, aktiv)] aus einer PullMessages-Antwort; unbekannte Ereignisarten werden uebergangen."""
    out = []
    for msg in re.findall(r"<(?:\w+:)?NotificationMessage.*?</(?:\w+:)?NotificationMessage>", xml, re.S):
        t = re.search(r"<(?:\w+:)?Topic[^>]*>([^<]+)<", msg)
        if not t:
            continue
        topic = t.group(1).strip().split(":", 1)[-1]
        spec = TOPICS.get(topic)
        if not spec:
            continue
        val = None
        for a, b in re.findall(r'<(?:\w+:)?SimpleItem\s+Name="([^"]+)"\s+Value="([^"]*)"', msg) + [(y, x) for x, y in re.findall(r'<(?:\w+:)?SimpleItem\s+Value="([^"]*)"\s+Name="([^"]+)"', msg)]:
            if a == spec[1]:
                val = b.strip().lower() in ("true", "1")
        if val is not None:
            out.append((spec[0], val))
    return out


class _Worker(threading.Thread):
    def __init__(self, cid: str, getter):
        super().__init__(name=f"onvif-{cid}", daemon=True)
        self.cid, self.getter = cid, getter
        self.state: dict[str, bool] = {}
        self.support: set[str] = set()
        self.ok_at = 0.0                       # letzte erfolgreiche Antwort
        self.error: str = ""                   # letzter Fehler (leer = in Ordnung)
        self.ready = threading.Event()         # Anfangszustand liegt vor (oder erster Fehler)
        self.stop = False

    def _item(self):
        it = self.getter(self.cid)
        if not it:
            self.stop = True
        return it

    def run(self):
        wait = 2.0
        while not self.stop:
            item = self._item()
            if not item:
                break
            try:
                self._session(item)
                wait = 2.0
            except OnvifError as e:
                self.error = str(e)
                self.ready.set()
                log.info("[onvif] %s: %s", item.get("name"), e)
            except Exception as e:                                                   # nie den Thread verlieren
                self.error = f"Unerwartete Antwort der Kamera ({e.__class__.__name__})"
                self.ready.set()
            for _ in range(int(wait * 2)):
                if self.stop:
                    return
                time.sleep(0.5)
            wait = min(wait * 2, 30.0)

    def _session(self, item: dict):
        base = f"http://{item['host']}:{int(item.get('onvif_port') or PORT)}"
        off = 0.0
        try:                                                                         # Kamerauhr (ohne Anmeldung) fuer den Zeitstempel
            x = _soap(base + "/onvif/device_service", '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>', item, auth=False)
            m = re.search(r"<(?:\w+:)?UTCDateTime>.*?<(?:\w+:)?Hour>(\d+)<.*?<(?:\w+:)?Minute>(\d+)<.*?<(?:\w+:)?Second>(\d+)<.*?<(?:\w+:)?Year>(\d+)<.*?<(?:\w+:)?Month>(\d+)<.*?<(?:\w+:)?Day>(\d+)<", x, re.S)
            if m:
                h, mi, s, y, mo, d = map(int, m.groups())
                off = (datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc) - datetime.now(timezone.utc)).total_seconds()
        except OnvifError as e:
            if "nicht erreichbar" in str(e):
                raise
        x = _soap(base + "/onvif/device_service", '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>All</Category></GetCapabilities>', item, off)
        m = re.search(r"<(?:\w+:)?Events>\s*<(?:\w+:)?XAddr>([^<]+)<", x)
        ev = re.sub(r"^http://[^/]+", base, m.group(1).strip()) if m else base + "/onvif/event_service"
        x = _soap(ev, f'<CreatePullPointSubscription xmlns="http://www.onvif.org/ver10/events/wsdl"><InitialTerminationTime>PT{SUB_S}S</InitialTerminationTime></CreatePullPointSubscription>', item, off)
        m = re.search(r"<(?:\w+:)?Address[^>]*>([^<]+)<", x)
        if not m:
            raise OnvifError("Die Kamera liefert kein ONVIF-Abo")
        sub = re.sub(r"^http://[^/]+", base, m.group(1).strip())
        until = time.time() + SUB_S - 30
        self.state, self.support = {}, set()
        while not self.stop and time.time() < until:
            x = _soap(sub, f'<PullMessages xmlns="http://www.onvif.org/ver10/events/wsdl"><Timeout>PT{PULL_S}S</Timeout><MessageLimit>50</MessageLimit></PullMessages>',
                      item, off, action=_ACTION_PULL, timeout=PULL_S + 12)
            for key, on in parse_messages(x):
                self.state[key] = on
                self.support.add(key)
            self.ok_at, self.error = time.time(), ""
            if self.support:
                self.ready.set()
            if not self._item():
                return


def _worker(item: dict, getter) -> _Worker:
    with _lock:
        w = _workers.get(item["id"])
        if w is None or not w.is_alive():
            w = _Worker(item["id"], getter)
            _workers[item["id"]] = w
            w.start()
        return w


def states(item: dict, getter, wait: float = FIRST_WAIT_S) -> dict:
    """{"md": bool, ..., "support": {...}} einer ONVIF-Kamera aus dem Abo. Wirft OnvifError, wenn die Kamera nicht antwortet."""
    w = _worker(item, getter)
    if not w.ready.is_set():
        w.ready.wait(wait)
    if not w.support:
        raise OnvifError(w.error or "Die Kamera meldet keine Bewegungs-Ereignisse (ONVIF)")
    if time.time() - w.ok_at > STALE_S:
        raise OnvifError(w.error or "Kamera nicht erreichbar (ONVIF)")
    return {**w.state, "support": set(w.support)}


def forget(cid: str) -> None:
    with _lock:
        w = _workers.pop(cid, None)
    if w:
        w.stop = True
