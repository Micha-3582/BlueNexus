"""Anmelde-Cookie wird "Secure", sobald die Anfrage ueber HTTPS kommt (direkt oder ueber Cloudflare Tunnel) - im Heimnetz ueber http bleibt es ohne."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_cookie.json")); webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None
app = webapp.app


def login(headers=None, base_url=None, **kw):
    c = app.test_client()
    r = c.post("/login", data={"username": "admin", "password": "adminpass1"}, headers=headers or {}, base_url=base_url or "http://localhost", **kw)
    cookies = [h for h in r.headers.getlist("Set-Cookie") if h.startswith("session=")]
    return c, r, cookies


def has_secure(cookies):
    return any("secure" in x.lower().replace("; ", ";").split(";") or "; Secure" in x for x in cookies)


# 1) Heimnetz (http): kein Secure - sonst ginge die Anmeldung dort nicht
c, r, ck = login()
assert ck and not has_secure(ck), ck
assert any("HttpOnly" in x and "SameSite=Lax" in x for x in ck)
assert c.get("/api/rules").status_code == 200                             # Anmeldung funktioniert
print("1) http OK")

# 2) Ueber den Tunnel: X-Forwarded-Proto bzw. CF-Visitor -> Secure
for hdr in ({"X-Forwarded-Proto": "https"}, {"X-Forwarded-Proto": "https, http"}, {"CF-Visitor": '{"scheme":"https"}'}, {"CF-Visitor": '{ "scheme": "https" }'}):
    c, r, ck = login(hdr)
    assert ck and has_secure(ck) and any("HttpOnly" in x for x in ck), (hdr, ck)
for hdr in ({"X-Forwarded-Proto": "http"}, {"CF-Visitor": '{"scheme":"http"}'}):
    c, r, ck = login(hdr)
    assert ck and not has_secure(ck), (hdr, ck)
print("2) Tunnel OK")

# 3) Direktes HTTPS
c, r, ck = login(base_url="https://localhost")
assert ck and has_secure(ck), ck
print("3) https OK")

# 4) Abmelden ueber HTTPS loescht das Cookie ebenfalls mit Secure
c, r, ck = login({"X-Forwarded-Proto": "https"})
r2 = c.post("/logout", headers={"X-Forwarded-Proto": "https"}, base_url="http://localhost")
gone = [h for h in r2.headers.getlist("Set-Cookie") if h.startswith("session=")]
assert gone and "Expires=Thu, 01 Jan 1970" in gone[0] and has_secure(gone), gone
print("4) Abmelden OK")

# 5) Feste Einstellung "immer Secure" bleibt moeglich
app.config["SESSION_COOKIE_SECURE"] = True
c, r, ck = login(); assert ck and has_secure(ck), ck
app.config["SESSION_COOKIE_SECURE"] = False
c, r, ck = login(); assert ck and not has_secure(ck)
# ausserhalb einer Anfrage (z. B. Hintergrundthread) darf nichts abstuerzen
assert webapp.request_is_https() is False
print("5) Einstellung OK")
print("COOKIE OK")
