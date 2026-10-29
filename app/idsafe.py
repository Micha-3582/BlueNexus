"""Kennungen (IDs) von Geraeten, die aus Antworten fremder Geraete oder Zentralen stammen (MAC, Adresse, Seriennummer ...), duerfen nur harmlose Zeichen
enthalten: Buchstaben, Ziffern und . _ : - . Die Kennungen landen in Adressen, Dateien und in HTML-Attributen; ein Fremdgeraet im Heimnetz kann
sonst Anfuehrungszeichen oder Klammern einschmuggeln. Normale Kennungen (MAC, CCU-Adressen, Zigbee-IDs, Tuya-IDs) bleiben unveraendert."""
import re

_BAD = re.compile(r"[^A-Za-z0-9._:\-]")


def safe_id(value, limit: int = 80) -> str:
    return _BAD.sub("_", str(value if value is not None else ""))[:limit]
