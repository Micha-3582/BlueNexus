"""Sicherheits-Haertung: Open Redirect, Benutzernamen, Zeitverhalten der Anmeldung, Schutz-Header, Cross-Site-Sperre, Groessenlimit."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore, UserError
webapp.users = UserStore(os.path.join(tmp, "u_sec.json")); webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None
app = webapp.app

# 1) Open Redirect nach der Anmeldung
def login_to(nxt):
    c = app.test_client()
    r = c.post("/login?next=" + nxt, data={"username": "admin", "password": "adminpass1"})
    return r.status_code, r.headers.get("Location")
for evil in ("//evil.com", "//evil.com/x", "/\\evil.com", "https://evil.com", "javascript:alert(1)", "http://evil.com", "///evil.com", "/%0d%0aSet-Cookie:x=1", "evil.com", "\\\\evil.com"):
    st, loc = login_to(evil)
    assert st == 302 and loc in ("/", "http://localhost/"), (evil, st, loc)
for good in ("/rules", "/admin", "/smarthome"):
    st, loc = login_to(good)
    assert st == 302 and loc.endswith(good), (good, loc)
print("1) Weiterleitung OK")

# 2) Benutzernamen
for bad in ('<img src=x onerror=alert(1)>', 'a"b', "a'b", "<script>", "x>y", "a" * 41, "-start", "a\nb", "  "):
    try:
        webapp.users.create(bad, "langespasswort1"); raise SystemExit("Name %r muss abgelehnt werden" % bad)
    except UserError:
        pass
for ok in ("Anna", "anna.k@x.de", "Jürgen Müller", "demo", "user_1", "a" * 40):
    webapp.users.create(ok, "langespasswort1")
print("2) Benutzernamen OK")

# 3) Zeitverhalten: unbekanntes Konto braucht etwa so lange wie ein falsches Passwort (kein Raten, welche Namen es gibt)
def t_verify(user, n=4):
    t0 = time.perf_counter()
    for _ in range(n):
        webapp.users.verify(user, "falsches-passwort")
    return (time.perf_counter() - t0) / n
t_unknown, t_known = t_verify("gibt-es-nicht"), t_verify("admin")
assert t_unknown > t_known * 0.4, (t_unknown, t_known)
print(f"3) Zeitverhalten OK (unbekannt {t_unknown*1000:.0f} ms, bekannt {t_known*1000:.0f} ms)")

# 4) Schutz-Header
c = app.test_client()
r = c.get("/login")
assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "SAMEORIGIN" and r.headers["Referrer-Policy"] == "same-origin"
assert "Strict-Transport-Security" not in r.headers, "HSTS nicht ueber http"
r = c.get("/login", headers={"X-Forwarded-Proto": "https"})
assert r.headers["Strict-Transport-Security"].startswith("max-age=")
print("4) Header OK")

# 5) Cross-Site-Sperre
c = app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
assert c.post("/api/virtual", json={"name": "A", "kind": "switch"}).status_code == 201
for site in ("same-origin", "same-site", "none", None):
    h = {"Sec-Fetch-Site": site} if site else {}
    assert c.post("/api/virtual", json={"name": "B" + str(site), "kind": "switch"}, headers=h).status_code == 201, site
r = c.post("/api/virtual", json={"name": "Fremd", "kind": "switch"}, headers={"Sec-Fetch-Site": "cross-site"})
assert r.status_code == 403 and "fremden Webseite" in r.get_json()["error"]
assert not any(v["name"] == "Fremd" for v in __import__("virtual").load()), "darf nicht angelegt werden"
assert c.delete("/api/virtual/x", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
assert c.get("/preview/anna", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403              # Vorschau-Start per Link von fremder Seite
assert c.get("/api/rules", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200                    # reines Lesen/Navigation bleibt moeglich
assert app.test_client().post("/login", data={"username": "admin", "password": "adminpass1"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403       # keine Anmeldung von fremder Seite aus
print("5) Cross-Site OK")

# 6) Groessenlimit
big = json.dumps({"name": "x" * (5 * 1024 * 1024), "kind": "switch"})
r = c.post("/api/virtual", data=big, content_type="application/json")
assert r.status_code == 413, r.status_code
print("6) Groessenlimit OK")
print("SECURITY OK")
