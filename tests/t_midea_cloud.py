"""Midea-Klimaanlage ueber die NetHome-Plus-Cloud (midea-beautiful-air): Suche per Konto, Anlegen, Zustand, Setzen, Geheimnisse."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import midea, shelly
import midea_beautiful as mb

shelly.DEVICES_PATH = os.path.join(tmp, "dev_midea_cloud.json")
if os.path.exists(shelly.DEVICES_PATH):
    os.remove(shelly.DEVICES_PATH)

S = {"on": True, "mode": 2, "target": 24.0, "fan": 60, "vert": 0, "horz": 0, "eco": 0, "indoor": 26.5, "outdoor": 18.0, "offline": False}
CALLS = {"send": 0, "list": 0, "connect": []}


def frame():
    d = bytearray(25)
    d[0] = 0xC0
    d[1] = 1 if S["on"] else 0
    t = int(S["target"])
    d[2] = (S["mode"] << 5) | ((t - 16) & 0x0F) | (0x10 if S["target"] - t else 0)
    d[3] = S["fan"]
    d[7] = (S["vert"] << 2) | S["horz"]
    d[9] = 0x10 if S["eco"] else 0
    d[11] = int(S["indoor"] * 2 + 50)
    d[12] = int(S["outdoor"] * 2 + 50)
    return bytes(9) + bytes([3]) + bytes(d)


class FakeCloud:
    max_retries = 2
    request_timeout = 8

    def list_appliances(self, force=False):
        CALLS["list"] += 1
        return [{"id": "142936511665569", "name": "Wohnzimmer", "sn": "SN", "type": "0xAC", "modelNumber": "-84"},
                {"id": "5", "name": "Entfeuchter", "sn": "SN2", "type": "0xA1", "modelNumber": "1"}]

    def appliance_transparent_send(self, appliance_id, data):
        CALLS["send"] += 1
        d = bytes(data)
        i = d.find(b"\xaa", 16)
        b = d[i:]
        if b[10] == 0x40:                                     # Setzen: wie die echte Anlage den Zustand uebernehmen
            S["on"] = bool(b[11] & 1)
            S["mode"] = b[12] >> 5
            S["target"] = (b[12] & 0x0F) + 16 + (0.5 if b[12] & 0x10 else 0)
            S["fan"] = b[13]
            S["vert"] = 1 if b[17] & 0x0C else 0
            S["horz"] = 1 if b[17] & 0x03 else 0
            S["eco"] = 1 if b[19] & 0x80 else 0
        if S["offline"]:
            return []
        return [frame()]


def fake_connect(account, password, **kw):
    CALLS["connect"].append((account, password))
    if password != "richtig":
        # die Anmeldung scheitert in der Bibliothek selbst; Fehlversuche merkt die Schranke (midea._install_login_gate)
        from midea_beautiful.cloud import MideaCloud
        from midea_beautiful.midea import DEFAULT_APP_ID, DEFAULT_APPKEY, DEFAULT_HMACKEY, DEFAULT_IOTKEY, DEFAULT_PROXIED, DEFAULT_SIGNKEY
        MideaCloud(appkey=DEFAULT_APPKEY, account=account, password=password, appid=DEFAULT_APP_ID, hmac_key=DEFAULT_HMACKEY, iot_key=DEFAULT_IOTKEY,
                   proxied=DEFAULT_PROXIED, sign_key=DEFAULT_SIGNKEY)._login_proxied()
    return FakeCloud()


LOGINS = []                                                 # Anmeldungen, die wirklich bei Midea ankommen (hinter der Schranke)
def _bad_login(self):
    from midea_beautiful.exceptions import AuthenticationError
    LOGINS.append(self._account)
    raise AuthenticationError("Account or password incorrect")
from midea_beautiful.cloud import MideaCloud as _MC
_MC._login_proxied = _MC._login_non_proxied = _bad_login
if hasattr(_MC, "_bnx_gated"): del _MC._bnx_gated
midea._install_login_gate(mb)
mb.connect_to_cloud = fake_connect
midea.STATUS_TTL_S = 0.3; midea.CLOUD_STATUS_TTL_S = 0.3; midea.FAIL_TTL_S = 0.3

# 1+2) Anlage mit Konto (die Suche ueber das Konto gibt es nicht mehr, die Suche laeuft lokal): Eintrag direkt anlegen, Zugangsdaten nirgends oeffentlich
import json
shelly._save([{"id": "midea-142936511665569", "kind": "midea", "cloud": True, "cloud_account": "mail@x.de", "cloud_password": "richtig", "device_id": 142936511665569,
               "name": "Wohnzimmer", "icon": "❄️", "ip": "", "gen": 0, "channel": 0, "model": "Midea Klimaanlage (Cloud)", "users": []}])
dev = shelly.load_devices()[0]; DID = dev["id"]
lst = shelly.list_with_status(ids={DID}, live=False)[0]
assert "cloud_password" not in lst and "cloud_account" not in lst and lst["kind"] == "midea"
assert "richtig" not in json.dumps(lst) and "mail@x.de" not in json.dumps(lst)
print("1+2) Anlegen OK")

# 3) Zustand
st = shelly.status(dev)
assert st["online"] is True and st["on"] is True and st["mode"] == "cool" and st["target_c"] == 24.0 and st["indoor_c"] == 26.5 and st["outdoor_c"] == 18.0 and st["fan"] == "medium", st
assert st["info"] == "Kühlen · Soll 24 °C · innen 26,5 °C · außen 18 °C", st["info"]
n = CALLS["send"]; shelly.status(dev); shelly.status(dev); assert CALLS["send"] == n, "Zwischenspeicher"
S["offline"] = True; time.sleep(0.4)
off = shelly.status(dev); assert "info" in off or off["online"] is False, off        # die Bibliothek wertet erst nach mehreren Fehlschlaegen als offline
S["offline"] = False; time.sleep(0.4)
assert shelly.status(dev)["online"] is True
print("3) Zustand OK")

# 4) Setzen
r = shelly.set_state(DID, False)
assert r["on"] is False and S["on"] is False and S["mode"] == 2 and S["target"] == 24.0
r = shelly.midea_set(DID, power=True, mode="heat", target=22.5, fan="low", swing="vertical", eco=True)
assert S["on"] and S["mode"] == 4 and S["target"] == 22.5 and S["fan"] == 40 and S["vert"] == 1 and S["horz"] == 0 and S["eco"] == 1, S
assert r["mode"] == "heat" and r["target_c"] == 22.5 and r["fan"] == "low" and r["swing"] == "vertical" and r["eco"] is True, r
shelly.midea_set(DID, target=26.2)
assert S["target"] == 26.0 and S["eco"] == 1 and S["mode"] == 4 and S["fan"] == 40, ("Rest bleibt, Eco bleibt", S)
shelly.midea_set(DID, swing="off", eco=False); assert S["vert"] == 0 and S["eco"] == 0
for kw in ({"target": 5}, {"target": 40}, {"mode": "kaffee"}, {"fan": "turbo"}, {}):
    try:
        shelly.midea_set(DID, **kw); raise SystemExit("sollte scheitern %r" % kw)
    except shelly.ShellyError:
        pass
d = shelly.midea_details(DID)
assert [m["key"] for m in d["modes"]] == ["auto", "cool", "dry", "heat", "fan_only"] and d["min"] == 16 and d["max"] == 31 and d["supports_eco"] and d["state"]["info"], d
print("4) Setzen OK")

# 5) Cloud-Fehler beim Setzen -> klare Meldung
midea._cdevs.clear(); midea._clouds.clear(); midea._login_fail.clear(); midea._good.clear(); midea._cache.clear()      # ohne letzten guten Zustand (sonst deckt die Schonfrist einen Aussetzer ab)
dev2 = {**dev, "cloud_password": "falsch"}
try:
    shelly.status(dev2)
    s2 = shelly.status(dev2); assert s2["online"] is False and "Anmeldung" in s2["error"], s2
except Exception as e:
    raise SystemExit("unerwartet %r" % e)
shelly.status({**dev2, "id": "midea-x"}); time.sleep(0.4); shelly.status(dev2)
assert LOGINS == [], "automatische Abfragen melden sich nie bei Midea an (sonst sperrt Midea das Konto)"
assert "automatische Anmeldung ist abgeschaltet" in shelly.status(dev2)["error"], shelly.status(dev2)
print("5) Fehler OK")
print("MIDEA CLOUD OK")
