"""Zwei-Faktor-Anmeldung (TOTP, RFC 6238) ohne Fremdbibliothek.

Kompatibel mit Google Authenticator, Microsoft Authenticator, Aegis, 2FAS,
Bitwarden usw.: SHA-1, 6 Stellen, 30 Sekunden.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP = 30
DIGITS = 6
RECOVERY_COUNT = 10


def new_secret() -> str:
    """20 Zufallsbytes als Base32 (ohne Füllzeichen)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _key(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def code_at(secret: str, step: int) -> str:
    mac = hmac.new(_key(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(num).zfill(DIGITS)


def verify(secret: str, code: str, last_step: int = 0, now: float = None):
    """Prüft einen Code im Fenster ±1 Schritt (Uhrabweichung).

    Gibt den gültigen Schritt zurück oder None. Ein Schritt, der nicht größer ist
    als ``last_step``, gilt als schon benutzt (Wiederverwendung wird abgelehnt)."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS:
        return None
    cur = int((time.time() if now is None else now) // STEP)
    for step in (cur - 1, cur, cur + 1):
        if step > last_step and hmac.compare_digest(code_at(secret, step), code):
            return step
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "BlueNexus") -> str:
    return (f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_svg(text: str):
    """QR-Code als Inline-SVG (segno). None, wenn segno fehlt -- dann bleibt der Textschlüssel."""
    try:
        import segno
    except ImportError:
        return None
    svg = segno.make(text, error="m").svg_inline(scale=5, border=4, dark="#000000", light="#ffffff")
    # Ohne viewBox schneidet die Größenangabe per CSS den Code ab statt ihn zu skalieren
    import re
    m = re.match(r'<svg width="(\d+)" height="(\d+)"', svg)
    if m:
        svg = svg.replace("<svg ", '<svg viewBox="0 0 %s %s" ' % (m.group(1), m.group(2)), 1)
    return svg


# ----- Rettungscodes -------------------------------------------------------
def new_recovery_codes() -> list:
    """10 Einmalcodes im Format abcd-efgh (ohne verwechselbare Zeichen)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return ["".join(secrets.choice(alphabet) for _ in range(4)) + "-" + "".join(secrets.choice(alphabet) for _ in range(4))
            for _ in range(RECOVERY_COUNT)]


def hash_recovery(code: str) -> str:
    norm = "".join(ch for ch in (code or "").lower() if ch.isalnum())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()
