import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
import notify, pushover, pwreset

webapp.users = UserStore(os.path.join(tmp, "u_pw.json"))
webapp.opslog.log = lambda *a, **k: None
app = webapp.app


def fresh():
    webapp._attempts.clear()
    pwreset._codes.clear()
    pwreset._sends.clear()


# 1) Konto anlegen zeigt den Schluessel einmal
c = app.test_client()
r = c.post("/create-account", data={"username": "chef", "firstname": "Max", "password": "chefpass123", "password2": "chefpass123"})
html = r.data.decode()
assert r.status_code == 200 and "Wiederherstellungsschlüssel" in html, r.status_code
key = re.search(r'id="key">([A-Z2-9\-]+)<', html).group(1)
assert re.fullmatch(r"[A-Z2-9]{5}(-[A-Z2-9]{5}){3}", key), key
assert webapp.users.has_recovery("chef") and "recovery_hash" not in str(webapp.users.list()), "Hash darf nie raus"
print("1) Schluessel bei Kontoanlage OK")

webapp.users.create("gast", "gastpass1234", {"dashboard": "read"})
# 2) Seite + Link
fresh()
assert b"/forgot" in app.test_client().get("/login").data
h = app.test_client().get("/forgot").data.decode()
assert "Schlüssel" in h and "use-key" in h and 'data-ch="telegram"' not in h
print("2) Seite ohne Telegram: nur Schluessel OK")

# 3) Reset per Schluessel
fresh()
cl = app.test_client()
j = cl.post("/api/forgot/reset", json={"username": "chef", "method": "key", "secret": key.lower().replace("-", " "), "password": "neuesPass123", "password2": "neuesPass123"}).get_json()
assert j.get("ok") and j.get("new_key") and j["new_key"] != key, j
assert webapp.users.verify("chef", "neuesPass123") and not webapp.users.verify("chef", "chefpass123")
assert not webapp.users.verify_recovery("chef", key) and webapp.users.verify_recovery("chef", j["new_key"])      # alter Schluessel verbraucht
key2 = j["new_key"]
bad = cl.post("/api/forgot/reset", json={"username": "chef", "method": "key", "secret": "AAAAA-AAAAA-AAAAA-AAAAA", "password": "xxxxxxxx12", "password2": "xxxxxxxx12"})
assert bad.status_code == 400 and webapp.users.verify("chef", "neuesPass123")
for body in ({"username": "chef", "method": "key", "secret": key2, "password": "kurz", "password2": "kurz"},
             {"username": "chef", "method": "key", "secret": key2, "password": "abcdefgh1", "password2": "abcdefgh2"}):
    assert cl.post("/api/forgot/reset", json=body).status_code == 400
assert cl.post("/api/forgot/reset", json={"username": "gast", "method": "key", "secret": key2, "password": "abcdefgh12", "password2": "abcdefgh12"}).status_code == 400       # Schluessel gehoert zu chef
print("3) Reset per Schluessel OK")

# 4) Telegram eingerichtet: Code
fresh()
sent = []
notify.configured = lambda: True
notify.recipients = lambda: [{"id": "main", "name": "Ich", "chat_id": "1", "system": True}]
notify.send = lambda text, *a, **k: sent.append(text)
notify.message = lambda text, *a, **k: sent.append("MSG:" + text) or True
h = app.test_client().get("/forgot").data.decode()
assert 'data-ch="telegram"' in h and 'data-ch="pushover"' not in h
cl = app.test_client()
r = cl.post("/api/forgot/send", json={"username": "unbekannt", "channel": "telegram"}).get_json()
r2 = cl.post("/api/forgot/send", json={"username": "gast", "channel": "telegram"}).get_json()          # kein Admin
assert r == r2 and r["ok"] and not sent, (r, r2, sent)                                                  # gleiche Antwort, nichts gesendet
r3 = cl.post("/api/forgot/send", json={"username": "CHEF", "channel": "telegram"}).get_json()
assert r3 == r and len(sent) == 1 and "chef" in sent[0], sent
code = re.search(r": (\d{6})\n", sent[0]).group(1)
assert cl.post("/api/forgot/send", json={"username": "chef", "channel": "signal"}).status_code == 200 and len(sent) == 1          # unbekannter Dienst: nichts
w = cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": "000000" if code != "000000" else "111111", "password": "codePass1234", "password2": "codePass1234"})
assert w.status_code == 400
ok = cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": code, "password": "codePass1234", "password2": "codePass1234"}).get_json()
assert ok.get("ok") and ok.get("new_key") is None and webapp.users.verify("chef", "codePass1234")
assert any(m.startswith("MSG:") and "zurückgesetzt" in m for m in sent)                                     # Hinweis an die Kanaele
again = cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": code, "password": "andersPass12", "password2": "andersPass12"})
assert again.status_code == 400 and webapp.users.verify("chef", "codePass1234")                              # Code nur einmal
print("4) Reset per Code OK")

# 5) Fehlversuche entwerten den Code, Sendegrenze, Abgelaufen, Nicht-Admin
fresh(); sent.clear()
cl = app.test_client()
cl.post("/api/forgot/send", json={"username": "chef", "channel": "telegram"})
code = re.search(r": (\d{6})\n", sent[-1]).group(1); wrong = "123456" if code != "123456" else "654321"
for _ in range(5):
    webapp._attempts.clear()
    cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": wrong, "password": "zzzzzzzz12", "password2": "zzzzzzzz12"})
webapp._attempts.clear()
assert cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": code, "password": "zzzzzzzz12", "password2": "zzzzzzzz12"}).status_code == 400      # nach 5 Fehlversuchen auch der richtige Code tot
fresh(); sent.clear()
for _ in range(5):
    webapp._attempts.clear(); cl.post("/api/forgot/send", json={"username": "chef", "channel": "telegram"})
assert len(sent) == 3, len(sent)                                                                              # hoechstens 3 Codes je 15 Minuten
fresh(); sent.clear(); cl.post("/api/forgot/send", json={"username": "chef", "channel": "telegram"})
code = re.search(r": (\d{6})\n", sent[-1]).group(1)
pwreset._codes["chef"]["exp"] = 0
assert cl.post("/api/forgot/reset", json={"username": "chef", "method": "code", "secret": code, "password": "zzzzzzzz12", "password2": "zzzzzzzz12"}).status_code == 400   # abgelaufen
fresh(); sent.clear()
pwreset._codes["gast"] = {"h": pwreset._hash("111111", "s"), "salt": "s", "exp": 9e12, "tries": 0}
assert cl.post("/api/forgot/reset", json={"username": "gast", "method": "code", "secret": "111111", "password": "zzzzzzzz12", "password2": "zzzzzzzz12"}).status_code == 400   # Code-Weg nur fuer Admins
print("5) Schutzmassnahmen OK")

# 6) IP-Bremse
fresh()
cl = app.test_client()
for _ in range(10):
    cl.post("/api/forgot/reset", json={"username": "chef", "method": "key", "secret": "AAAAA-AAAAA-AAAAA-AAAAA", "password": "abcdefgh12", "password2": "abcdefgh12"})
assert cl.post("/api/forgot/reset", json={"username": "chef", "method": "key", "secret": "x", "password": "abcdefgh12", "password2": "abcdefgh12"}).status_code == 429
fresh()

# 7) Einstellungen: eigener Schluessel
cl = app.test_client(); cl.post("/login", data={"username": "chef", "password": "codePass1234"})
assert cl.get("/api/recovery-key").get_json()["has"] is True
assert cl.post("/api/recovery-key", json={"password": "falsch"}).status_code == 400
old = key2
j = cl.post("/api/recovery-key", json={"password": "codePass1234"}).get_json()
assert j["ok"] and webapp.users.verify_recovery("chef", j["key"]) and not webapp.users.verify_recovery("chef", old)
assert b"rk-new" in cl.get("/admin").data
gc = app.test_client(); gc.post("/login", data={"username": "gast", "password": "gastpass1234"})
assert gc.post("/api/recovery-key", json={"password": "gastpass1234"}).status_code == 403            # ohne Recht "Konto: Schreiben"
print("PWRESET OK")
