"""Prüfung 13.11.2026 (1.63.1):
F-2: Der Filter "nur lokales Netz" lässt weder 0.0.0.0 / 0.x.x.x (unter Linux = dieser Rechner), noch Link-Local (169.254.x.x), Multicast, Loopback
     noch Öffentliches durch - in ALLEN Integrationen (eine gemeinsame Prüfung, lanip.py).
F-1: GET /api/config zeigt Konten ohne passendes Recht weder die IP-Bereiche der Geräte-Suche noch die Vertragskosten (Administrator und berechtigte Konten
     sehen sie weiter; Speichern läuft unverändert)."""
import sys, os, ipaddress
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth, shelly, homematic, zigbee, midea, tuya, wol, lanip
from auth import UserStore

BAD = ["0.0.0.0", "0.1.2.3", "169.254.169.254", "169.254.0.1", "127.0.0.1", "127.9.9.9", "224.0.0.1", "239.255.255.250", "8.8.8.8", "100.64.0.1", "240.0.0.1",
       "255.255.255.255", "::1", "evil.example.com", "192.168.2.5@evil.com", "2130706433", ""]
GOOD = ["192.168.2.5", "10.0.0.7", "172.16.4.9", "172.31.255.1", "192.168.178.1"]


def rejects(fn, *a):
    try:
        fn(*a)
    except Exception:
        return True
    return False


# --- Die gemeinsame Funktion
for h in GOOD:
    assert lanip.is_lan_ipv4(ipaddress.ip_address(h)), h
for h in BAD:
    try:
        a = ipaddress.ip_address(h)
    except ValueError:
        continue
    assert not lanip.is_lan_ipv4(a), h
assert lanip.is_lan_network(ipaddress.ip_network("192.168.2.0/24"))
assert lanip.is_lan_network(ipaddress.ip_network("10.0.0.0/20"))
for n in ("169.254.0.0/20", "0.0.0.0/20", "127.0.0.0/24", "8.8.8.0/24", "224.0.0.0/20"):
    assert not lanip.is_lan_network(ipaddress.ip_network(n)), n

# --- Jede Integration nimmt die guten Adressen an und weist die schlechten ab
for h in GOOD:
    assert shelly.check_ip(h) == h
    assert homematic._split_host(h)[1] == h
    assert zigbee._split_host(h)[0] == h
    assert midea._check_target(h) == h
    assert wol._ip(h, "IP") == h
for h in BAD:
    assert rejects(shelly.check_ip, h), ("shelly", h)
    assert rejects(homematic._split_host, h), ("homematic", h)
    assert rejects(zigbee._split_host, h), ("zigbee", h)
    if h:                                                                   # leer = "keine Adresse" (bei Midea/WOL erlaubt)
        assert rejects(midea._check_target, h), ("midea", h)
        if h != "255.255.255.255":
            assert rejects(wol._ip, h, "IP"), ("wol", h)
assert wol._ip("255.255.255.255", "Broadcast", True) == "255.255.255.255"   # Broadcast bleibt dort erlaubt, wo er gebraucht wird
assert rejects(wol._ip, "255.255.255.255", "IP")                            # als Rechner-Adresse nicht
assert tuya.parse_networks("192.168.2.0/24, 10.1.0.0/20") == ["192.168.2.0/24", "10.1.0.0/20"]
for n in ("169.254.0.0/20", "0.0.0.0/20", "127.0.0.0/24", "8.8.8.0/24"):
    assert rejects(tuya.parse_networks, n), ("tuya-netz", n)

# --- Und über die Oberfläche (Konto mit "Geräte einrichten", kein Administrator): kein Umweg zum eigenen Rechner
webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("einr", "einrpass12345", {"dashboard": "read", "smarthome_einrichten": "write"})
webapp.users.create("tarif", "tarifpass12345", {"dashboard": "read", "settings_tarif": "read"})
webapp.users.create("nix", "nixpass1234567", {"dashboard": "read"})
webapp.opslog.log = lambda *a, **k: None


def login(name, pw):
    c = webapp.app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


A, E, T, N = login("admin", "adminpass1"), login("einr", "einrpass12345"), login("tarif", "tarifpass12345"), login("nix", "nixpass1234567")
for h in ("0.0.0.0", "169.254.169.254"):
    r = E.post("/api/esphome/scan", json={"ip": h})
    assert r.status_code in (400, 422), (h, r.status_code, r.get_data(as_text=True)[:100])
    r = E.post("/api/tuya/add", json={"id": "abc", "ip": h})
    assert r.status_code == 400, (h, r.status_code)

# --- F-1: Konfiguration lesen
c0 = store.load_config()
c0.update({"cerbo_host": "192.168.2.30", "tibber_token": "TOKEN-GEHEIM", "scan_networks": "192.168.2.0/24, 10.0.5.0/24",
           "contract_fee_month_eur": 14.9, "grid_fee_day_eur": 0.3, "meter_fee_day_eur": 0.1, "section14a_credit_day_eur": 0.05, "vat_percent": 19.0,
           "pv_inverters": [{"name": "WR1", "unit": 80}]})
store.save_config(c0)
FEES = ("contract_fee_month_eur", "grid_fee_day_eur", "meter_fee_day_eur", "section14a_credit_day_eur", "vat_percent")

ja = A.get("/api/config").get_json()                                      # Administrator: alles wie bisher
assert ja["scan_networks"] == "192.168.2.0/24, 10.0.5.0/24" and ja["contract_fee_month_eur"] == 14.9 and ja["cerbo_host"] == "192.168.2.30"
assert ja["pv_inverters"] == [{"name": "WR1", "unit": 80}]

je = E.get("/api/config").get_json()                                      # "Geräte einrichten": IP-Bereiche ja, Kosten nein, Geheimnisse nein
assert je["scan_networks"] == "192.168.2.0/24, 10.0.5.0/24"
assert all(f not in je for f in FEES), [f for f in FEES if f in je]
assert je["tibber_token"] == "" and je["cerbo_host"] == ""

jt = T.get("/api/config").get_json()                                      # "Tarif lesen": Kosten ja, IP-Bereiche nein
assert jt["contract_fee_month_eur"] == 14.9 and jt["vat_percent"] == 19.0
assert jt["scan_networks"] == "" and jt["scan_networks_set"] is True

jn = N.get("/api/config").get_json()                                      # nur Dashboard: weder noch
assert jn["scan_networks"] == "" and jn["scan_networks_set"] is True
assert all(f not in jn for f in FEES)
assert jn["pv_inverters"] == [{"name": "WR1", "unit": 80}]                # nur Name und Modbus-Nummer, keine Adresse: bleibt (Dashboard-Anzeige)
assert "TOKEN-GEHEIM" not in str(jn) and "192.168.2.30" not in str(jn) and "192.168.2.0/24" not in str(jn)

# --- Speichern bleibt unverändert: das Konto ohne Recht verändert nichts (auch nicht mit den ausgeblendeten Werten), der Administrator darf
r = N.post("/api/config", json={"scan_networks": "", "contract_fee_month_eur": None, "vat_percent": "", "cerbo_host": "", "tibber_token": ""})
assert r.status_code == 200
after = store.load_config()
assert after["scan_networks"] == "192.168.2.0/24, 10.0.5.0/24" and after["contract_fee_month_eur"] == 14.9 and after["cerbo_host"] == "192.168.2.30"
assert A.post("/api/config", json={"contract_fee_month_eur": 15.5, "vat_percent": 7.0}).status_code == 200
after = store.load_config()
assert after["contract_fee_month_eur"] == 15.5 and after["vat_percent"] == 7.0

print("t_sicherheit4 OK")
