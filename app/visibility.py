"""
Sichtbarkeit einzelner Geraete/Schalter/Sensoren fuer bestimmte Benutzer.

Jeder Eintrag der Register (Aktoren, Sensoren, eigene Schalter/Knoepfe, Wake-on-LAN-Ziele) kann ein Feld "users" tragen:
  - fehlt es / ist None -> jeder Benutzer mit Dashboard-Zugriff sieht den Eintrag (Standard)
  - Liste von Benutzernamen (klein geschrieben) -> nur diese Benutzer sehen und bedienen ihn
  - leere Liste -> niemand ausser den Administratoren (Benutzerverwaltung = Schreiben)
Administratoren sehen immer alles. Das Feld legt nur ein Administrator fest.
Reine Logik, keine Ein-/Ausgabe.
"""
from __future__ import annotations


def normalize(value) -> list | None:
    """None = fuer alle sichtbar. Sonst eine sortierte Liste eindeutiger, klein geschriebener Benutzernamen."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("users: Liste von Benutzernamen oder null erwartet")
    return sorted({str(u).strip().lower() for u in value if str(u).strip()})


def can_see(item: dict, username: str, is_admin: bool) -> bool:
    if is_admin:
        return True
    users = item.get("users")
    return users is None or (username or "").strip().lower() in users


def apply(items: list[dict], item_id: str, users) -> bool:
    """Setzt/loescht das Feld im geladenen Register (Aufrufer speichert). True = Eintrag gefunden."""
    users = normalize(users)
    for it in items:
        if it.get("id") == item_id:
            if users is None:
                it.pop("users", None)
            else:
                it["users"] = users
            return True
    return False


def rename_user(items: list[dict], old: str, new: str) -> bool:
    """Benennt einen Benutzer in allen Eintraegen um (z. B. wenn er seinen Namen aendert). True = etwas geaendert."""
    old, new, changed = old.strip().lower(), new.strip().lower(), False
    for it in items:
        us = it.get("users")
        if isinstance(us, list) and old in us:
            it["users"] = sorted({new if u == old else u for u in us})
            changed = True
    return changed


def drop_user(items: list[dict], name: str) -> bool:
    """Entfernt einen geloeschten Benutzer aus allen Listen (die Eintraege bleiben eingeschraenkt, auch wenn die Liste leer wird)."""
    name, changed = name.strip().lower(), False
    for it in items:
        us = it.get("users")
        if isinstance(us, list) and name in us:
            it["users"] = [u for u in us if u != name]
            changed = True
    return changed
