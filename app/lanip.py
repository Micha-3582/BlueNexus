"""Gemeinsame Pruefung: Ist das eine Adresse aus dem lokalen Netz? (Eine Stelle fuer alle Integrationen, damit keine vergessen wird.)"""
from __future__ import annotations


def is_lan_ipv4(addr) -> bool:
    """True nur fuer private IPv4-Adressen (10.x, 172.16-31.x, 192.168.x ...). Nicht erlaubt: Loopback, 0.x.x.x und 0.0.0.0 (unter Linux ist das dieser
    Rechner selbst), Link-Local (169.254.x.x), Multicast und reservierte Bereiche - sonst liesse sich die Pruefung als Umweg zum eigenen Rechner benutzen."""
    return (addr.version == 4 and addr.is_private
            and not (addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_unspecified or addr.is_reserved)
            and addr.packed[0] != 0)


def is_lan_network(net) -> bool:
    """Ein ganzes Netz (von der ersten bis zur letzten Adresse) liegt im lokalen Netz."""
    return net.version == 4 and is_lan_ipv4(net.network_address) and is_lan_ipv4(net.broadcast_address)
