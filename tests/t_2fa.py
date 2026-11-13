"""Zwei-Faktor-Anmeldung (TOTP): Einrichten, zweistufiger Login, Wiederverwendung, Rettungscodes, Begrenzung, Ausschalten, Admin-Reset."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
import totp
webapp.users = UserStore(os.path.join(tmp, "u_2fa.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass123", permissions={"account": "write"})
webapp.opslog.log = lambda *a, **k: None
app = webapp.app
J = {"Content-Type": "application/json"}


def fresh_ip():
    webapp._attempts.clear()


def login(name="admin", pw="adminpass1"):
    c = app.test_client()
    r = c.post("/login", data={"username": name, "password": pw})
    return c, r


def logged_in(c):
    """Angemeldet = die Sitzung hat einen Benutzer (ohne eine Anfrage zu stellen, die den Zwischenzustand der Anmeldung loeschen koennte)."""
    with c.session_transaction() as s:
        return bool(s.get("user"))


# RFC-6238-Testwert (Zeit 59 -> Code 287082 bei 6 Stellen)
assert totp.code_at("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", 59 // 30) == "287082"

# 1) Ohne 2FA: Login wie bisher
c, r = login()
assert r.status_code == 302 and logged_in(c)
assert c.get("/api/account/2fa").get_json()["on"] is False

# 2) Einrichten: falsches Passwort, dann Start, dann falscher Code, dann richtiger Code
assert c.post("/api/account/2fa/start", json={"password": "falsch"}).status_code == 400
j = c.post("/api/account/2fa/start", json={"password": "adminpass1"}).get_json()
secret = j["secret"].replace(" ", "")
assert j["uri"].startswith("otpauth://totp/") and secret in j["uri"]
assert j["qr"] is None or "viewBox" in j["qr"]
assert c.get("/api/account/2fa").get_json()["on"] is False                      # noch nicht eingeschaltet
now = time.time()
assert c.post("/api/account/2fa/enable", json={"code": "000000"}).status_code == 400
cur = int(now // 30)
good = totp.code_at(secret, cur)
j = c.post("/api/account/2fa/enable", json={"code": good}).get_json()
codes = j["recovery"]
assert len(codes) == 10 and all(len(x) == 9 for x in codes)
assert c.get("/api/account/2fa").get_json() == {"on": True, "recovery_left": 10, "qr": c.get("/api/account/2fa").get_json()["qr"]}
raw = open(webapp.users.path, encoding="utf-8").read()
assert codes[0] not in raw and codes[0].replace("-", "") not in raw                # Rettungscodes nur als Hash

# 3) Login in zwei Schritten: nach dem Passwort noch NICHT angemeldet
c, r = login()
assert r.status_code == 200 and "Zwei-Faktor-Code" in r.get_data(as_text=True)
assert not logged_in(c)
# Der beim Einschalten benutzte Schritt ist verbraucht: der naechste Schritt gilt
r = c.post("/login/2fa", data={"code": good})
assert r.status_code == 401 and not logged_in(c)                                  # Wiederverwendung abgelehnt
nxt = totp.code_at(secret, cur + 1)
r = c.post("/login/2fa", data={"code": nxt})
assert r.status_code == 302 and logged_in(c), r.status_code
# derselbe Code ein zweites Mal (neue Anmeldung) -> abgelehnt
c2, r = login()
assert c2.post("/login/2fa", data={"code": nxt}).status_code == 401 and not logged_in(c2)

# 4) Direkt auf /login/2fa ohne Passwortschritt: keine Anmeldung
c3 = app.test_client()
r = c3.post("/login/2fa", data={"code": totp.code_at(secret, cur + 1)})
assert r.status_code == 401 and not logged_in(c3)

# 5) 5 falsche Codes: Sitzung verworfen, auch ein richtiger Code hilft dann nicht mehr
fresh_ip()
c4, r = login()
for i in range(4):
    assert c4.post("/login/2fa", data={"code": "111111"}).status_code == 401
r = c4.post("/login/2fa", data={"code": "111111"})
assert "von vorn" in r.get_data(as_text=True)
assert c4.post("/login/2fa", data={"code": totp.code_at(secret, cur + 1)}).status_code == 401 and not logged_in(c4)

# 6) Rettungscode: einmal
fresh_ip()
c5, r = login()
r = c5.post("/login/2fa", data={"code": codes[0]})
assert r.status_code == 302 and logged_in(c5)
fresh_ip()
c6, r = login()
assert c6.post("/login/2fa", data={"code": codes[0]}).status_code == 401 and not logged_in(c6)
assert webapp.users.recovery_left_2fa("admin") == 9

# 7) Zwischenzustand laeuft nach 5 Minuten ab
fresh_ip()
c7, r = login()
with c7.session_transaction() as s:
    s["pre2fa"] = dict(s["pre2fa"], t=time.time() - 400)
assert c7.post("/login/2fa", data={"code": codes[1]}).status_code == 401 and not logged_in(c7)

# 8) Passwort aendern laesst 2FA an; Passwort-vergessen-Weg schaltet es nicht aus
webapp.users.update_password("admin", "adminpass2")
assert webapp.users.has_2fa("admin")
fresh_ip()
c8, r = login("admin", "adminpass2")
assert not logged_in(c8) and "Zwei-Faktor-Code" in r.get_data(as_text=True)

# 9) Ausschalten braucht Passwort UND Code
fresh_ip()
c9, r = login("admin", "adminpass2")
assert c9.post("/login/2fa", data={"code": codes[2]}).status_code == 302
assert c9.post("/api/account/2fa/disable", json={"password": "adminpass2", "code": "123456"}).status_code == 400
assert c9.post("/api/account/2fa/disable", json={"password": "falsch", "code": codes[3]}).status_code == 400
assert webapp.users.has_2fa("admin")
assert c9.post("/api/account/2fa/disable", json={"password": "adminpass2", "code": codes[3]}).status_code == 200
assert not webapp.users.has_2fa("admin")
assert "totp_secret" not in open(webapp.users.path, encoding="utf-8").read().split('"anna"')[0]

# 10) Admin setzt 2FA eines anderen Kontos zurueck
fresh_ip()
ca, r = login("anna", "annapass123")
assert logged_in(ca)
j = ca.post("/api/account/2fa/start", json={"password": "annapass123"}).get_json()
sec_a = j["secret"].replace(" ", "")
assert ca.post("/api/account/2fa/enable", json={"code": totp.code_at(sec_a, int(time.time() // 30))}).status_code == 200
assert webapp.users.has_2fa("anna")
fresh_ip()
cadm, r = login("admin", "adminpass2")
assert logged_in(cadm)
us = {u["username"]: u for u in cadm.get("/api/users").get_json()["users"]}
assert us["anna"]["twofa"] is True and us["admin"]["twofa"] is False
assert cadm.patch("/api/users/anna", json={"reset_2fa": True}).status_code == 200
assert not webapp.users.has_2fa("anna")
fresh_ip()
cb, r = login("anna", "annapass123")
assert r.status_code == 302 and logged_in(cb)

# 11) Notausgang auf dem Server (reset_password.py --no-2fa)
webapp.users.set_pending_2fa("anna", totp.new_secret()); webapp.users.enable_2fa("anna", [], 1)
assert webapp.users.has_2fa("anna")
import subprocess
app_dir = os.path.join(os.path.dirname(os.path.abspath(webapp.__file__)))
src = open(os.path.join(app_dir, "reset_password.py"), encoding="utf-8").read()
assert "--no-2fa" in src and "disable_2fa" in src

# 12) Oeffentliche Wege bleiben unberuehrt (Passwort-Vergessen-Seite erreichbar)
assert app.test_client().get("/forgot").status_code == 200

print("t_2fa OK")
