"""Telegram: Test senden mit eingetippten (noch nicht gespeicherten) Werten, klare Meldungen."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import notify
from auth import UserStore
notify.CRED_PATH = os.path.join(tmp, "telegram.json")
webapp.users = UserStore(os.path.join(tmp, "u_tg.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "read"})
calls = []
def fake_api(token, method, payload=None):
    calls.append((token, method, payload)); return {"ok": True, "result": []}
notify._api = fake_api
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
# nichts gespeichert, nichts eingetippt -> klare Meldung (Token fehlt)
r = c.post("/api/notify/test"); assert r.status_code == 400 and "Token fehlt" in r.get_json()["error"], r.get_json()
# nur Token getippt -> Chat-ID fehlt, mit Anleitung
r = c.post("/api/notify/test", json={"token": "123:abc"}); assert r.status_code == 400 and "Chat-ID fehlt" in r.get_json()["error"] and "Chat-ID ermitteln" in r.get_json()["error"], r.get_json()
assert not calls
# eingetippte Werte werden direkt probiert (ohne zu speichern)
r = c.post("/api/notify/test", json={"token": "123:abc", "chat_id": "987654"}); assert r.status_code == 200, r.get_json()
assert calls[-1][0] == "123:abc" and calls[-1][1] == "sendMessage" and str(calls[-1][2]["chat_id"]) == "987654"
assert not os.path.exists(notify.CRED_PATH) and not notify.configured()
# Gruppen/Kanaele (Minus) gehen, Unsinn nicht
assert c.post("/api/notify/test", json={"token": "123:abc", "chat_id": "-1001234567890"}).status_code == 200
r = c.post("/api/notify/test", json={"token": "123:abc", "chat_id": "abc"}); assert r.status_code == 400 and "Ziffern" in r.get_json()["error"]
# gespeichert -> Test ohne Angaben funktioniert wie bisher
assert c.post("/api/notify/credentials", json={"token": "123:abc", "chat_id": "987654"}).status_code == 200 and notify.configured()
n = len(calls); assert c.post("/api/notify/test").status_code == 200 and calls[-1][0] == "123:abc" and len(calls) == n + 1
# Rechte wie bisher
l = webapp.app.test_client(); l.post("/login", data={"username": "lese", "password": "lesepass123"})
assert l.post("/api/notify/test", json={"token": "x", "chat_id": "1"}).status_code == 403
# Felder fuer Akku/Tageszusammenfassung nur mit Modul Energie
cf = store.load_config(); cf["modules"] = {"energy": False, "smarthome": True, "cameras": False, "verlauf": False, "alexa": False}; store.save_config(cf)
assert c.get("/api/notify").get_json()["energy"] is False
cf["modules"]["energy"] = True; store.save_config(cf)
assert c.get("/api/notify").get_json()["energy"] is True
print("TELEGRAM TEST OK")
