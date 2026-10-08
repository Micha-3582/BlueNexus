"""Testmodus (Umgebungsvariable BLUENEXUS_SANDBOX=1): Die App laeuft normal, darf aber das eigene Geraet NICHT verlassen.

Jede Verbindung zu einer anderen Adresse als dem eigenen Rechner wird abgewiesen - Cerbo, Homematic, Shelly, Kameras, Tibber, Telegram,
Cloudflare, Wake-on-LAN und alles andere. So kann man eine Sicherung gefahrlos einspielen und ausprobieren: es wird nichts geschaltet
oder gesendet, und die echte Anlage merkt nichts davon.
"""
import ipaddress
import os
import socket

ACTIVE = "1" in (os.environ.get("BLUENEXUS_SANDBOX"), os.environ.get("HOMENEXUS_SANDBOX"))
_done = False


def _local(addr) -> bool:
    if not isinstance(addr, tuple) or not addr:
        return True                                                  # Unix-Sockets o. Ae.
    host = addr[0]
    if isinstance(host, bytes):
        host = host.decode("ascii", "ignore")
    host = str(host or "").split("%")[0]
    if host in ("", "localhost", "::", "0.0.0.0"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False                                                 # Name, der nicht "localhost" ist


def _guard(orig, idx_addr):
    def wrapper(self, *args, **kw):
        addr = args[idx_addr(args)] if args else None
        if not _local(addr):
            raise OSError(101, "Testmodus: Verbindungen nach außen sind gesperrt (%s)" % (addr[0] if isinstance(addr, tuple) else addr))
        return orig(self, *args, **kw)
    return wrapper


def activate() -> None:
    global _done
    if not ACTIVE or _done:
        return
    _done = True
    last = lambda a: len(a) - 1                                      # sendto(data, addr) / sendto(data, flags, addr) / connect(addr)
    socket.socket.connect = _guard(socket.socket.connect, last)
    socket.socket.connect_ex = _guard(socket.socket.connect_ex, last)
    socket.socket.sendto = _guard(socket.socket.sendto, last)
