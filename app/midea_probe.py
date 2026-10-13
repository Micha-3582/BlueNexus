"""Messung fuer eine lokal gesteuerte Midea-Klimaanlage: wie lange brauchen Verbindung, Anmeldung und Befehle wirklich?
Aufruf (im App-Ordner, BlueNexus vorher anhalten, damit nichts dazwischenfunkt):
    ../venv/bin/python midea_probe.py 192.168.2.232            nur lesen
    ../venv/bin/python midea_probe.py 192.168.2.232 schalten   zusaetzlich einmal umschalten und zurueck
Liest Token/Schluessel aus shelly_devices.json (nichts davon wird angezeigt)."""
import asyncio
import json
import logging
import os
import socket
import sys
import time

from msmart.device import AirConditioner as AC

HERE = os.path.dirname(os.path.abspath(__file__))


def entry_for(ip):
    with open(os.path.join(HERE, "shelly_devices.json"), encoding="utf-8") as f:
        for d in json.load(f):
            if d.get("kind") == "midea" and d.get("ip") == ip and not d.get("cloud"):
                return d
    sys.exit(f"Keine lokale Klimaanlage mit IP {ip} in shelly_devices.json")


def tcp(ip, port):
    t = time.time()
    s = socket.socket()
    s.settimeout(8)
    try:
        s.connect((ip, port))
        return f"{time.time() - t:.2f} s"
    except Exception as e:
        return f"FEHLER nach {time.time() - t:.1f} s ({e})"
    finally:
        s.close()


async def timed(label, coro):
    t = time.time()
    try:
        r = await coro
        print(f"  {label:34} {time.time() - t:5.1f} s  ok")
        return r
    except Exception as e:
        print(f"  {label:34} {time.time() - t:5.1f} s  FEHLER {e.__class__.__name__}: {e}")
        return None


async def main(ip, toggle):
    e = entry_for(ip)
    port = int(e.get("port") or 6444)
    print(f"{e.get('name')} ({ip}), Protokoll V{e.get('version')}")
    print("TCP-Verbindung (5x):", ", ".join(tcp(ip, port) for _ in range(5)))
    dev = AC(ip=ip, port=port, device_id=int(e["device_id"]), version=e.get("version"))
    await timed("Anmeldung (inkl. 1 s Pause)", dev.authenticate(e["token"], e["key"]))
    await timed("Fähigkeiten abfragen", dev.get_capabilities())
    for i in range(3):
        await timed(f"Zustand lesen #{i + 1}", dev.refresh())
        print(f"     online={dev.online} an={dev.power_state} innen={dev.indoor_temperature}")
    for pause in (20, 60):
        print(f"  … {pause} s Pause (Verbindung bleibt offen) …")
        await asyncio.sleep(pause)
        await timed(f"Zustand lesen nach {pause} s", dev.refresh())
        print(f"     online={dev.online}")
    if toggle:
        was = dev.power_state
        dev.power_state = not was
        await timed(f"Schalten → {'an' if not was else 'aus'}", dev.apply())
        print(f"     online={dev.online} an={dev.power_state}")
        await asyncio.sleep(5)
        await timed("Zustand lesen", dev.refresh())
        dev.power_state = was
        await timed(f"Zurückschalten → {'an' if was else 'aus'}", dev.apply())
        print(f"     online={dev.online} an={dev.power_state}")
    dev._lan._disconnect()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    logging.basicConfig(level=logging.WARNING, format="     %(levelname)s %(name)s: %(message)s")
    asyncio.run(main(sys.argv[1], len(sys.argv) > 2 and sys.argv[2] == "schalten"))
