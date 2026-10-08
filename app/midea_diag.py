"""Diagnose fuer die Midea-Klimaanlage: zeigt, was Anlage und Cloud auf die Schluessel-Abfrage antworten.
Aufruf (im venv): ./venv/bin/python midea_diag.py <IP-der-Klimaanlage> [Region]
Fragt E-Mail und Passwort ab (Passwort wird nicht angezeigt, nichts wird gespeichert)."""
import asyncio
import getpass
import sys

from msmart.cloud import NetHomePlusCloud, SmartHomeCloud
from msmart.discover import Discover
from msmart.lan import Security


async def main(ip, region):
    print("== Suche im Netz ==")
    Discover._authenticate_device = classmethod(lambda cls, dev: asyncio.sleep(0, False))   # nur finden, noch nicht anmelden
    devs = await Discover.discover(target=ip, timeout=5, auto_connect=False)
    if not devs:
        print("Anlage antwortet nicht auf die Suche (IP richtig? gleiche Netz?)")
        return
    d = devs[0]
    print(f"id={d.id} ip={d.ip} port={d.port} version={getattr(d, 'version', '?')} type={getattr(d, 'type', '?')} sn={getattr(d, 'sn', '?')}")
    acc = input("NetHome-Plus-E-Mail (leer = Standardkonto): ").strip()
    pw = getpass.getpass("Passwort: ") if acc else None
    for name, cls in (("NetHomePlus", NetHomePlusCloud), ("SmartHome", SmartHomeCloud)):
        print(f"== {name}-Cloud ==")
        try:
            c = cls(region, account=acc or None, password=pw or None)
            await c.login()
            print("Anmeldung OK")
            try:
                r = await c._api_request("/v1/appliance/user/list/get", c._build_request_body({}))
                lst = (r or {}).get("list", [])
                print(f"  Geraete im Konto: {len(lst)}")
                for x in lst:
                    print("   ", {k: x.get(k) for k in ("id", "name", "type", "sn", "sn8", "modelNumber", "onlineStatus", "masterId", "enterpriseCode") if k in x})
                print("  Schluesselabfrage fuer jedes Geraet des Kontos (6 Byte little/big, 8 Byte little/big):")
                for x in lst:
                    for nb in (6, 8):
                        for endian in ("little", "big"):
                            u = Security.udpid(int(x["id"]).to_bytes(nb, endian)).hex()
                            try:
                                t, k = await c.get_token(u)
                                res = f"TOKEN ERHALTEN ({len(t)}/{len(k)})"
                            except Exception as e:
                                res = str(e)
                            print(f"    {x.get('name')} {nb}B {endian}: {res}")
            except Exception as e:
                print("  Geraeteliste nicht abrufbar:", e)
        except Exception as e:
            print("Anmeldung fehlgeschlagen:", e)
            continue
        for endian in ("little", "big"):
            u = Security.udpid(d.id.to_bytes(6, endian)).hex()
            try:
                t, k = await c.get_token(u)
                print(f"  {endian}: udpid {u} -> Token erhalten (Laenge {len(t)}/{len(k)})")
            except Exception as e:
                print(f"  {endian}: udpid {u} -> {e}")


asyncio.run(main(sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "DE").upper()))
