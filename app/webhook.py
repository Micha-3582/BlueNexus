"""
Web-Aufruf fuer eigene Knoepfe: Beim Druecken ruft die Zentrale eine hinterlegte Adresse auf (GET oder POST), z. B. ein anderes
Smart-Home-System, einen Webhook (IFTTT, Home Assistant, ioBroker) oder ein Geraet mit HTTP-Schnittstelle.

Die Adresse bleibt geheim: Sie steht nur im Register (virtual.json), wird nie an den Browser geschickt und taucht weder im Logbuch noch in
Fehlermeldungen auf (dort steht nur der Knopfname und das Ergebnis). Angelegt/geaendert wird sie nur von Administratoren.

Schutz: nur http/https; keine Link-Local-/Metadaten-Ziele (169.254.0.0/16, fe80::/10, Multicast, 0.0.0.0); Umleitungen werden nicht verfolgt;
kurze Zeitgrenze; die Antwort wird nicht gespeichert. Im Testmodus (sandbox) sind Verbindungen nach aussen ohnehin gesperrt.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from urllib.parse import urlsplit

import requests

log = logging.getLogger("webhook")
TIMEOUT_S = 8
MAX_URL_LEN = 1000
METHODS = ("GET", "POST")

_results: dict[str, tuple[float, bool, str]] = {}      # knopf-id -> (Zeit, ok, Kurztext) - ohne Adresse
_lock = threading.Lock()


class WebhookError(ValueError):
    pass


def _bad_ip(ip) -> bool:
    return ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved and not ip.is_private


def validate(url: str) -> str:
    """Prueft die Adresse und gibt sie bereinigt zurueck (WebhookError bei Unsinn)."""
    url = (url or "").strip()
    if not url or len(url) > MAX_URL_LEN or any(c in url for c in "\r\n\t "):
        raise WebhookError("Adresse ungültig (leer, zu lang oder mit Leerzeichen)")
    if "://" not in url:
        url = "http://" + url
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise WebhookError("Die Adresse muss mit http:// oder https:// beginnen")
    try:
        parts.port                                          # ValueError bei ungueltigem Port
    except ValueError:
        raise WebhookError("Ungültiger Port in der Adresse")
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        ip = None                                           # Hostname statt IP: wird beim Aufruf aufgeloest und geprueft
    if ip is not None and _bad_ip(ip):
        raise WebhookError("Diese Zieladresse ist nicht erlaubt")
    return url


def _check_resolved(host: str, port: int) -> None:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise WebhookError("Adresse nicht auffindbar")
    for info in infos:
        if _bad_ip(ipaddress.ip_address(info[4][0].split("%")[0])):
            raise WebhookError("Diese Zieladresse ist nicht erlaubt")


def call(url: str, method: str = "GET") -> tuple[bool, str]:
    """Ruft die Adresse auf. Rueckgabe (ok, Kurztext) - der Text enthaelt nie die Adresse."""
    try:
        url = validate(url)
        parts = urlsplit(url)
        _check_resolved(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
        r = requests.request("POST" if method == "POST" else "GET", url, timeout=TIMEOUT_S, allow_redirects=False)
        ok = r.status_code < 400
        return ok, f"HTTP {r.status_code}" if not ok else "ok"
    except WebhookError as e:
        return False, str(e)
    except requests.Timeout:
        return False, "Zeitüberschreitung"
    except requests.ConnectionError:
        return False, "nicht erreichbar"
    except Exception as e:                                  # noqa: BLE001 - nie die Adresse in die Meldung lassen
        log.warning("Web-Aufruf fehlgeschlagen: %s", type(e).__name__)
        return False, "Fehler beim Aufruf"


def fire(key: str, name: str, url: str, method: str = "GET") -> None:
    """Im Hintergrund aufrufen (blockiert den Druck nicht) und das Ergebnis merken/loggen."""
    def run():
        ok, text = call(url, method)
        with _lock:
            _results[key] = (time.time(), ok, text)
        try:
            import opslog
            opslog.log("rules", f"Web-Aufruf „{name}“: {'ausgelöst' if ok else 'fehlgeschlagen – ' + text}", dry=False)
        except Exception:                                   # noqa: BLE001
            pass
    threading.Thread(target=run, daemon=True, name="webhook").start()


def result_since(key: str, t0: float, wait_s: float = 4.0):
    """Wartet kurz auf das Ergebnis eines Aufrufs, der nach t0 gestartet wurde. Rueckgabe (ok, Text) oder None (laeuft noch)."""
    end = time.time() + wait_s
    while time.time() < end:
        with _lock:
            hit = _results.get(key)
        if hit and hit[0] >= t0:
            return hit[1], hit[2]
        time.sleep(0.1)
    return None
