"""Zweite Nachprüfung (1.28.4): Zugänge zu Zentralen und Clouds (Homematic, Zigbee, Tuya, Midea), Alexa-Bridge-Einstellungen, Teilen (Freigaben) und
Funkthermometer ändert nur ein Administrator, auch mit Schreibrecht im Bereich (Alexa-Einstellungen und Teilen waren in der Route schon Admin-only und bleiben hier als Gegenprobe). Ansehen bleibt. Hintergrund: Beim Wechsel der Adresse der CCU blieb das
gespeicherte Passwort erhalten (es ging dann an die neue Adresse), und beim Anlegen eines Thermometers baute der Server die Konfiguration mit dem gemerkten
WLAN-Passwort und gab sie an den Browser."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth, thermo, homematic
from auth import UserStore

thermo.THERMO_PATH = os.path.join(tmp, "thermo.json"); thermo.WIFI_PATH = os.path.join(tmp, "thermo_wifi.json")
homematic.CREDENTIALS_PATH = os.path.join(tmp, "hm.json")
webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("einr", "einrpass12345", {"dashboard": "read", "smarthome_einrichten": "write", "smarthome_teilen": "write", "settings_system": "write"})


def login(name, pw):
    c = webapp.app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


A, E = login("admin", "adminpass1"), login("einr", "einrpass12345")
thermo.wifi_set("HausWLAN", "geheimes-wlan-pw")                       # ein vom Administrator gemerktes WLAN

# Konto mit Schreibrecht im Bereich, aber kein Administrator: alles 403
forbidden = [("post", "/api/homematic/credentials", {"host": "192.168.50.99", "user": "Admin"}), ("delete", "/api/homematic/credentials", None),
             ("post", "/api/zigbee/credentials", {"host": "192.168.50.98", "key": "k"}), ("delete", "/api/zigbee/gateways/gw1", None),
             ("post", "/api/tuya/credentials", {"access_id": "a", "access_secret": "b", "region": "eu"}), ("delete", "/api/tuya/credentials", None),
             ("post", "/api/midea/cloud", {"id": "midea-1", "account": "a@b.de", "password": "x"}), ("post", "/api/midea/rekey", {"id": "midea-1"}),
             ("post", "/api/alexa/settings", {"port": 8099}),
             ("post", "/api/shares", {"name": "Fremd"}), ("post", "/api/shares/s-1/token", {}), ("patch", "/api/shares/s-1", {"name": "x"}), ("delete", "/api/shares/s-1", None),
             ("post", "/api/share-item", {"share": "s-1", "item": "x", "on": True}),
             ("post", "/api/thermo", {"name": "Neu", "interval": 15, "wifi": {"ssid": "HausWLAN", "pass": ""}}), ("delete", "/api/thermo_wifi", None),
             ("patch", "/api/thermo/t1", {"name": "x"}), ("delete", "/api/thermo/t1", None), ("post", "/api/thermo/t1/calibrate", {})]
for method, url, body in forbidden:
    r = getattr(E, method)(url, json=body) if body is not None else getattr(E, method)(url)
    assert r.status_code == 403, (method, url, r.status_code)
# das gemerkte WLAN ist unberuehrt, es wurde nichts angelegt, die CCU-Daten sind nicht entstanden
assert thermo.wifi_get().get("pass") == "geheimes-wlan-pw" and thermo.listing() == [] and not os.path.exists(homematic.CREDENTIALS_PATH)

# Ansehen bleibt fuer das Konto moeglich
assert E.get("/api/thermo").status_code == 200
assert "geheimes-wlan-pw" not in E.get("/api/thermo").get_data(as_text=True)         # das Passwort wird nie ausgegeben
# Der Administrator darf weiter alles (hier Aufrufe, die ohne echte Geraete ehrlich scheitern, aber nicht 403)
for method, url, body in (("post", "/api/homematic/credentials", {"host": "8.8.8.8", "user": "Admin"}), ("post", "/api/shares", {"name": "Besuch"}),
                          ("post", "/api/alexa/settings", {"port": "abc"}), ("delete", "/api/thermo_wifi", None)):
    r = getattr(A, method)(url, json=body) if body is not None else getattr(A, method)(url)
    assert r.status_code != 403, (method, url, r.status_code)
print("SICHERHEIT 1.28.4 OK", sys.argv[1].split("/")[-1])
