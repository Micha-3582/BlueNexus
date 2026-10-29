"""NFC-Tags: nur registrierte Handys loesen aus; Registrierung per Link und direkt; Tag-Freigabe je Handy; Loeschen; Schutzregeln."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import nfc, virtual, backup
from auth import UserStore
nfc.NFC_PATH = os.path.join(tmp, "nfc_t.json")
virtual.VIRTUAL_PATH = getattr(virtual, "VIRTUAL_PATH", None) or virtual.VIRTUAL_PATH
webapp.users = UserStore(os.path.join(tmp, "u_nfc.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("helfer", "helferpass1", permissions={"dashboard": "write", "settings_system": "write", "smarthome": "write"})
logs = []
webapp.opslog.log = lambda kind, text, **k: logs.append((kind, text))
store.module_on = lambda n, cfg=None: True
mk = lambda: webapp.app.test_client()
adm = mk(); adm.post("/login", data={"username": "admin", "password": "adminpass1"})
hlp = mk(); hlp.post("/login", data={"username": "helfer", "password": "helferpass1"})

# 1) Rechte: nur Administratoren verwalten
assert hlp.get("/api/nfc").status_code == 403 and hlp.post("/api/nfc/phones", json={"name": "x"}).status_code == 403
assert adm.get("/api/nfc").status_code == 200 and mk().get("/api/nfc").status_code in (302, 401)
print("1) Rechte OK")

# 2) Tag + Knopf anlegen, Handy ueber Link registrieren
r = adm.post("/api/nfc/tags", json={"name": "Kellerlicht", "new_button": True}); assert r.status_code == 201, r.get_json()
tag = r.get_json(); btn = next(v for v in virtual.load() if v["id"] == tag["target"]); assert btn["kind"] == "button" and btn["name"] == "Kellerlicht"
assert adm.post("/api/nfc/tags", json={"name": "", "new_button": True}).status_code == 400
phone1 = mk()
assert phone1.get("/nfc/" + tag["id"]).status_code == 403, "unregistriertes Handy"
code = adm.post("/api/nfc/pair", json={"name": "Maxs S25"}).get_json()["path"]
r = phone1.get(code); assert r.status_code == 200 and "Jetzt registrieren" in r.get_data(as_text=True) and "hn_nfc" not in r.headers.get("Set-Cookie", "")
assert phone1.get(code).status_code == 200, "Vorschau-Abruf (GET) verbraucht den Code nicht"
assert nfc.pair_peek(code.rsplit("/", 1)[1]) == "Maxs S25"
r = phone1.post(code); assert r.status_code == 200 and "registriert" in r.get_data(as_text=True)
ck = r.headers.get("Set-Cookie", ""); assert "hn_nfc=" in ck and "HttpOnly" in ck and "SameSite=Lax" in ck and "Max-Age=315360000" in ck, ck
assert mk().get(code).status_code == 410 and mk().post(code).status_code == 410, "Link nur einmal"
nfc._pair["abgelaufen"] = ("X", time.time() - 5); assert mk().get("/nfc/pair/abgelaufen").status_code == 410 and mk().post("/nfc/pair/abgelaufen").status_code == 410
d = adm.get("/api/nfc").get_json(); assert [p["name"] for p in d["phones"]] == ["Maxs S25"] and all("hash" not in p for p in d["phones"])
print("2) Registrieren OK")

# 3) Ausloesen
def pressed(): return btn["id"] in virtual.snapshot() and virtual.snapshot()[btn["id"]]["pressed"]
r = phone1.get("/nfc/" + tag["id"]); assert r.status_code == 200 and "Kellerlicht" in r.get_data(as_text=True) and pressed()
assert any("Maxs S25" in t and "Kellerlicht" in t for k, t in logs), logs
virtual.consume([btn["id"]]); n_logs = len(logs)
phone1.get("/nfc/" + tag["id"]); assert not pressed() and len(logs) == n_logs, "doppeltes Lesen zaehlt einmal"
print("3) Ausloesen OK")

# 4) Schutzregeln
nfc._last.clear()
assert phone1.head("/nfc/" + tag["id"]).status_code == 204 and not pressed()
assert phone1.get("/nfc/" + tag["id"], headers={"Sec-Fetch-Site": "cross-site", "Sec-Fetch-Dest": "document"}).status_code == 200 and pressed(), "Oeffnen aus einer Chat-App/Browseransicht (cross-site) muss gehen"
virtual.consume([btn["id"]]); nfc._last.clear()
assert phone1.get("/nfc/" + tag["id"], headers={"Sec-Fetch-Dest": "image"}).status_code == 403 and not pressed()
assert phone1.get("/nfc/" + tag["id"], headers={"Sec-Fetch-Site": "none", "Sec-Fetch-Dest": "document"}).status_code == 200 and pressed()
virtual.consume([btn["id"]]); nfc._last.clear()
bad = mk(); bad.set_cookie("hn_nfc", "geraten")
assert bad.get("/nfc/" + tag["id"]).status_code == 403 and not pressed(), "falsches Kennzeichen"
assert mk().get("/nfc/gibtsnicht").status_code == 404
store.module_on = lambda n, cfg=None: n != "smarthome"
assert phone1.get("/nfc/" + tag["id"]).status_code == 404, "Modul Smart Home aus"
store.module_on = lambda n, cfg=None: True
print("4) Schutzregeln OK")

# 5) PIN-geschuetzte Ziele sind ausgeschlossen
b2 = virtual.add("Tuer", "button", "🚪"); virtual.set_pin(b2["id"], "1234")
try: nfc.add_tag("Tuer", b2["id"]); raise SystemExit("PIN-Ziel muss abgelehnt werden")
except nfc.NfcError: pass
rr = adm.post("/api/nfc/tags", json={"name": "Tuer", "target": b2["id"]}); assert rr.status_code == 201 and rr.get_json()["target"] != b2["id"], "API ignoriert ein vorgegebenes Ziel: immer neuer Knopf"
nfc.remove_tag(rr.get_json()["id"])
assert b2["id"] not in [t["id"] for t in adm.get("/api/nfc").get_json()["targets"]]
t2 = nfc.add_tag("Licht2", btn["id"])
virtual.set_pin(btn["id"], "4321"); nfc._last.clear(); virtual.consume([btn["id"]])
webapp._pin_fails.clear()
r = phone1.get("/nfc/" + t2["id"]); h = r.get_data(as_text=True)
assert r.status_code == 200 and 'name="pin"' in h and "PIN" in h and not pressed(), "registriertes Handy: PIN-Abfrage statt Ausloesen"
anon = webapp.app.test_client(); ra = anon.get("/nfc/" + t2["id"])
assert ra.status_code == 403 and 'name="pin"' not in ra.get_data(as_text=True), "fremdes Handy sieht keine PIN-Abfrage"
rp = anon.post("/nfc/" + t2["id"], data={"pin": "4321"}); assert rp.status_code == 403 and not pressed(), "richtige PIN ohne registriertes Handy loest nichts aus"
r = phone1.post("/nfc/" + t2["id"], data={"pin": "0000"}); assert r.status_code == 403 and "falsch" in r.get_data(as_text=True).lower() and not pressed()
r = phone1.post("/nfc/" + t2["id"], data={"pin": ""}); assert r.status_code in (403, 200) and not pressed()
nfc._last.clear(); r = phone1.post("/nfc/" + t2["id"], data={"pin": "4321"}); assert r.status_code == 200 and "ausgel" in r.get_data(as_text=True).lower() and pressed(), "richtige PIN loest aus"
virtual.consume([btn["id"]]); nfc._last.clear(); webapp._pin_fails.clear()
webapp._attempts.clear()
J = {"Accept": "application/json"}                                              # PIN-Seite sendet per fetch (kein Seitenwechsel -> Fenster schliesst selbst)
rj = phone1.post("/nfc/" + t2["id"], data={"pin": "0000"}, headers=J); jj = rj.get_json()
assert rj.status_code == 403 and jj["ok"] is False and "falsch" in jj["error"].lower() and not pressed()
rj = phone1.post("/nfc/" + t2["id"], data={"pin": "4321"}, headers=J); jj = rj.get_json()
assert rj.status_code == 200 and jj["ok"] is True and jj["title"] == "Licht2" and "ausgel" in jj["text"] and pressed(), jj
assert anon.post("/nfc/" + t2["id"], data={"pin": "4321"}, headers=J).get_json()["ok"] is False
virtual.consume([btn["id"]]); webapp._pin_fails.clear(); webapp._attempts.clear() if hasattr(webapp, "_attempts") else None
for _ in range(5): phone1.post("/nfc/" + t2["id"], data={"pin": "9999"})
nfc._last.clear(); r = phone1.post("/nfc/" + t2["id"], data={"pin": "4321"}); assert r.status_code in (429, 403) and not pressed(), "nach 5 Fehlversuchen gesperrt (auch mit richtiger PIN)"
webapp._pin_fails.clear()
virtual.set_pin(btn["id"], ""); nfc.remove_tag(t2["id"])
print("5) PIN OK")

# 6) Freigabe je Handy, Loeschen
code2 = adm.post("/api/nfc/pair", json={"name": "Annas Handy"}).get_json()["path"]
phone2 = mk(); assert phone2.get(code2).status_code == 200 and phone2.post(code2).status_code == 200
ids = {p["name"]: p["id"] for p in adm.get("/api/nfc").get_json()["phones"]}
nfc._last.clear(); virtual.consume([btn["id"]])
assert phone2.get("/nfc/" + tag["id"]).status_code == 200 and pressed(), "Standard: alle registrierten Handys"
assert adm.patch("/api/nfc/tags/" + tag["id"], json={"phones": [ids["Maxs S25"]]}).status_code == 200
nfc._last.clear(); virtual.consume([btn["id"]])
r = phone2.get("/nfc/" + tag["id"]); assert r.status_code == 403 and "darf diesen Tag nicht" in r.get_data(as_text=True) and not pressed()
assert phone1.get("/nfc/" + tag["id"]).status_code == 200 and pressed()
assert adm.delete("/api/nfc/phones/" + ids["Maxs S25"]).status_code == 200
nfc._last.clear(); virtual.consume([btn["id"]])
assert phone1.get("/nfc/" + tag["id"]).status_code == 403 and not pressed(), "geloeschtes Handy"
t = next(x for x in adm.get("/api/nfc").get_json()["tags"] if x["id"] == tag["id"])
assert t["phones"] == [], "Tag nur fuer das geloeschte Handy: danach niemand (nicht alle!)"
assert phone2.get("/nfc/" + tag["id"]).status_code == 403
assert adm.patch("/api/nfc/tags/" + tag["id"], json={"phones": ["*"]}).status_code == 200 and phone2.get("/nfc/" + tag["id"]).status_code == 200
print("6) Freigabe/Loeschen OK")

# 7) Registrieren direkt im angemeldeten Browser; Schalter wird umgeschaltet; Tag loeschen; Ziel loeschen
r = adm.post("/api/nfc/phones", json={"name": "PC"}); assert r.status_code == 200 and "hn_nfc=" in r.headers.get("Set-Cookie", "")
sw = virtual.add("Lampe", "switch", "💡"); tm = virtual.add("Pumpe", "timer", "⏱️")
rr = adm.post("/api/nfc/tags", json={"name": "Lampe", "target": sw["id"]}); assert rr.status_code == 201 and next(v for v in virtual.load() if v["id"] == rr.get_json()["target"])["kind"] == "button", "neue Tags legen immer einen Knopf an"
nfc.remove_tag(rr.get_json()["id"])
d0 = adm.get("/api/nfc").get_json(); assert sw["id"] not in [t["id"] for t in d0["targets"]] and sw["id"] in [t["id"] for t in d0["known"]]
# aeltere Tags auf Schalter/Timer funktionieren weiter (hier direkt angelegt, wie vor der Vereinfachung)
dd = nfc.load(); dd["tags"].append({"id": "alt1", "name": "Lampe", "target": sw["id"], "phones": ["*"], "created": 0, "last_used": None}); nfc._save(dd); t3 = {"id": "alt1"}
nfc._last.clear(); assert adm.get("/nfc/" + t3["id"]).status_code == 200 and next(v for v in virtual.load() if v["id"] == sw["id"])["on"] is True
nfc._last.clear(); adm.get("/nfc/" + t3["id"]); assert next(v for v in virtual.load() if v["id"] == sw["id"])["on"] is False, "zweites Scannen schaltet aus"
assert adm.delete("/api/nfc/tags/" + t3["id"]).status_code == 200 and adm.get("/nfc/" + t3["id"]).status_code == 404
bw = virtual.add("Weg", "button", "x"); t4 = nfc.add_tag("Weg", bw["id"])
assert adm.delete("/api/virtual/" + bw["id"]).status_code == 400 and any(x["id"] == t4["id"] for x in nfc.load()["tags"]) and any(v["id"] == bw["id"] for v in virtual.load()), "NFC-Knopf nur ueber den Tag loeschbar"
_ub = webapp.rules.used_by; webapp.rules.used_by = lambda k, i: ["Regel X"] if i == bw["id"] else []
assert adm.delete("/api/nfc/tags/" + t4["id"]).status_code == 409 and any(x["id"] == t4["id"] for x in nfc.load()["tags"]), "in Regel verwendet: Tag bleibt"
webapp.rules.used_by = _ub
assert adm.delete("/api/nfc/tags/" + t4["id"]).status_code == 200 and not any(x["id"] == t4["id"] for x in nfc.load()["tags"]) and not any(v["id"] == bw["id"] for v in virtual.load()), "Tag loescht auch den Knopf"
print("7) Schalter/Loeschen OK")

# 8) Backup enthaelt die Registrierung; Adresse
assert "nfc.json" in backup.SETTINGS_FILES
assert adm.post("/api/nfc/base", json={"base_url": "http://192.168.50.40:5005/"}).get_json()["base_url"] == "http://192.168.50.40:5005"
assert adm.post("/api/nfc/base", json={"base_url": "ftp://x"}).status_code == 400
print("8) Backup/Adresse OK")
# 9) Installierbare Anmeldeseiten + oeffentliche Einrichtungsseite /nfc
for path in ("/login", "/nfc"):
    h = mk().get(path).get_data(as_text=True) if path != "/login" else mk().get("/login").get_data(as_text=True)
    assert 'rel="manifest"' in h and "pwa.js" in h and "apple-touch-icon" in h, path
r = mk().get("/nfc"); assert r.status_code == 200 and "Noch nicht registriert" in r.get_data(as_text=True)
assert mk().get("/nfc/").status_code == 200
webapp._attempts.clear()
codej = adm.post("/api/nfc/pair", json={"name": "JsonHandy"}).get_json()["path"]; phj = mk()
rj = phj.post(codej, headers={"Accept": "application/json"}); jj = rj.get_json()
assert rj.status_code == 200 and jj["ok"] is True and jj["title"] == "Handy registriert" and nfc.COOKIE in rj.headers.get("Set-Cookie", ""), (rj.status_code, jj)
rj2 = mk().post(codej, headers={"Accept": "application/json"}); assert rj2.status_code == 410 and rj2.get_json()["ok"] is False, "Link nur einmal gueltig (auch ueber fetch)"
code3 = adm.post("/api/nfc/pair", json={"name": "Sohn"}).get_json()["path"]; ph3 = mk(); ph3.post(code3)
assert "Sohn" in ph3.get("/nfc").get_data(as_text=True) and "registriert" in ph3.get("/nfc").get_data(as_text=True)
# Etikett-Symbol fuer neue Knoepfe, Umstellung alter
nb = adm.post("/api/nfc/tags", json={"name": "Neu", "new_button": True}).get_json()
assert next(v for v in virtual.load() if v["id"] == nb["target"])["icon"] == "🏷️"
virtual.update(nb["target"], icon="📲"); nfc.migrate_icons()
assert next(v for v in virtual.load() if v["id"] == nb["target"])["icon"] == "🏷️"
bx = virtual.add("Handgemacht", "button", "📲"); nfc.add_tag("x", bx["id"]); virtual.update(bx["id"], icon="🔔"); nfc.migrate_icons()
assert next(v for v in virtual.load() if v["id"] == bx["id"])["icon"] == "🏷️", "Tag-Knoepfe tragen immer das Etikett"
# Symbol ist fest: Aenderung ueber die API wird abgelehnt, andere Knoepfe bleiben aenderbar, Liste meldet 'nfc'
assert adm.patch("/api/virtual/" + nb["target"], json={"icon": "🔔"}).status_code == 400
assert adm.patch("/api/virtual/" + nb["target"], json={"icon": "🏷️", "show": False}).status_code == 200
other = virtual.add("Normal", "button", "🔘"); assert adm.patch("/api/virtual/" + other["id"], json={"icon": "🔔"}).status_code == 200
lst = {v["id"]: v for v in adm.get("/api/virtual").get_json()}; assert lst[nb["target"]]["nfc"] is True and lst[other["id"]]["nfc"] is False
print("9b) Symbol OK")
# Umbenennen: Tag <-> Knopf bleiben gleich benannt
tr = adm.post("/api/nfc/tags", json={"name": "Alt"}).get_json()
assert adm.patch("/api/nfc/tags/" + tr["id"], json={"name": "Neuer Name"}).status_code == 200
assert next(v for v in virtual.load() if v["id"] == tr["target"])["name"] == "Neuer Name" and next(t for t in nfc.load()["tags"] if t["id"] == tr["id"])["name"] == "Neuer Name"
r = adm.patch("/api/virtual/" + tr["target"], json={"name": "Unter Aktoren versucht"}); assert r.status_code == 400 and "NFC + QR" in r.get_json()["error"], "Umbenennen nur unter NFC + QR"
assert next(v for v in virtual.load() if v["id"] == tr["target"])["name"] == "Neuer Name"
assert adm.patch("/api/virtual/" + tr["target"], json={"name": "Neuer Name", "show": False}).status_code == 200, "gleicher Name + andere Felder gehen"
assert adm.patch("/api/nfc/tags/" + tr["id"], json={"name": "  "}).status_code == 400
print("9c) Umbenennen OK")
print("9) Installierbar/Einrichtungsseite OK")
print("NFC OK")
