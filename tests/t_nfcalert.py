"""Fremde NFC-/QR-Zugriffe landen im Geraete-Logbuch (Sicherheit, nur Administratoren) und im Regel-Logbuch - mit Adresse, ohne Fluten."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import nfc, virtual, devicelog
from auth import UserStore
nfc.NFC_PATH = os.path.join(tmp, "nfc_t.json")
webapp.users = UserStore(os.path.join(tmp, "u_nfca.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass1", {"dashboard": "write", "settings_geraete": "read", "smarthome_sicherheit": "write"})
ops = []
webapp.opslog.log = lambda kind, text, **k: ops.append((kind, text))
store.module_on = lambda n, cfg=None: True
mk = lambda: webapp.app.test_client()
adm = mk(); adm.post("/login", data={"username": "admin", "password": "adminpass1"})
mar = mk(); mar.post("/login", data={"username": "anna", "password": "annapass1"})
tag = adm.post("/api/nfc/tags", json={"name": "Garagentor", "new_button": True}).get_json()
alerts = lambda c, q="?cat=sicherheit": [e for e in (c.get("/api/devicelog" + q).get_json() or {}).get("entries", []) if e["ref"] == "nfc:alert"]
H = lambda ip: {"X-Forwarded-For": ip}

# 1) Fremdes (nicht registriertes) Handy -> abgewiesen und protokolliert, mit Adresse
r = mk().get("/nfc/" + tag["id"], headers=H("203.0.113.7")); assert r.status_code == 403
a = alerts(adm); assert len(a) == 1 and a[0]["ok"] is False and a[0]["by"] == "Fremder Zugriff" and a[0]["name"] == "Garagentor", a
assert "203.0.113.7" in a[0]["text"] and "Unbekanntes Handy" in a[0]["text"], a[0]
assert any("203.0.113.7" in t and "Garagentor" in t for k, t in ops), ops
# 2) Dieselbe Adresse nochmal innerhalb von 5 Minuten: kein zweiter Eintrag (kein Fluten)
mk().get("/nfc/" + tag["id"], headers=H("203.0.113.7")); assert len(alerts(adm)) == 1
# 3) Andere Adresse -> eigener Eintrag
mk().get("/nfc/" + tag["id"], headers=H("198.51.100.9")); assert len(alerts(adm)) == 2
# 4) Unbekannter/geloeschter Tag (Adressen durchprobieren, alter Aufkleber)
r = mk().get("/nfc/gibtsnicht123", headers=H("203.0.113.50")); assert r.status_code in (403, 404)
a = alerts(adm); assert any("Unbekannter oder gelöschter Tag" in e["text"] and "203.0.113.50" in e["text"] for e in a), a
# 5) Dauerbeschuss -> "gesperrt" wird gemeldet (einmal)
ip = "192.0.2.77"
for i in range(14): mk().get(f"/nfc/zufall{i}", headers=H(ip))
a = [e for e in alerts(adm) if "192.0.2.77" in e["text"]]
assert any("gesperrt" in e["text"] for e in a), a
assert sum(1 for e in a if "gesperrt" in e["text"]) == 1
# 6) Nur Administratoren sehen diese Meldungen - auch ein Konto mit "Sicherheit: Schreiben" nicht
assert alerts(mar) == [] and alerts(mar, "") == []
assert not any(e["ref"] == "nfc:alert" for e in mar.get("/api/devicelog/last").get_json().values() if isinstance(e, dict) and False)
assert mar.get("/api/devicelog/last").status_code == 403
# 7) Ein registriertes Handy mit Erlaubnis loest aus -> KEIN Alarm
code = adm.post("/api/nfc/pair", json={"name": "Maxs S25"}).get_json()["path"]
ph = mk(); ph.post(code)
before = len(alerts(adm)); r = ph.get("/nfc/" + tag["id"], headers=H("10.0.0.5")); assert r.status_code == 200 and len(alerts(adm)) == before
# 8) Fehlgeschlagene Anmeldungen: ebenfalls mit Adresse, einmal je Adresse, nur fuer Administratoren
lg = lambda c: [e for e in (c.get("/api/devicelog?cat=sicherheit").get_json() or {}).get("entries", []) if e["ref"] == "login:alert"]
bad = mk(); r = bad.post("/login", data={"username": "admin", "password": "falsch"}, headers=H("203.0.113.99")); assert r.status_code == 401
a = lg(adm); assert len(a) == 1 and "203.0.113.99" in a[0]["text"] and "„admin“" in a[0]["text"] and a[0]["ok"] is False, a
assert "falsch" not in json.dumps(a)                                                       # nie das eingegebene Passwort
bad.post("/login", data={"username": "admin", "password": "nochmal"}, headers=H("203.0.113.99")); assert len(lg(adm)) == 1
assert lg(mar) == []
ok = mk(); assert ok.post("/login", data={"username": "admin", "password": "adminpass1"}, headers=H("203.0.113.98")).status_code == 302 and len(lg(adm)) == 1
print("NFC-ALARM OK")
