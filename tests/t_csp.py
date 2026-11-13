"""Content-Security-Policy im Meldemodus (1.63.3): Kopfzeile nur auf HTML-Seiten und nur "Report-Only" (blockiert nichts), Meldeempfaenger ohne Anmeldung,
gezaehlt statt gespeichert (keine Parameter/Anker), begrenzt; Ansehen und Zuruecksetzen nur fuer Administratoren."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth, csp
from auth import UserStore

webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("leser", "leserpass12345", {a: "read" for a in auth.AREA_IDS})
webapp.opslog.log = lambda *a, **k: None
app = webapp.app


def login(name, pw):
    c = app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


# --- Kopfzeile: nur Meldemodus, nur HTML
anon = app.test_client()
r = anon.get("/login")
assert r.status_code == 200
assert "Content-Security-Policy" not in r.headers, "es darf KEINE erzwingende Regel geben"
rep = r.headers.getlist("Content-Security-Policy-Report-Only")
assert len(rep) == 2 and any("report-uri /api/csp-report?p=a" in v for v in rep) and any("report-uri /api/csp-report?p=b" in v for v in rep), rep
a = next(v for v in rep if "?p=a" in v)
for frag in ("default-src 'self'", "connect-src 'self'", "object-src 'none'", "base-uri 'self'", "form-action 'self'", "https://cdnjs.cloudflare.com"):
    assert frag in a, frag
b = next(v for v in rep if "?p=b" in v)
assert "script-src 'self'" in b and "'unsafe-inline'" not in b                     # streng: kein Inline-Code
A = login("admin", "adminpass1")
assert A.get("/api/config").headers.get("Content-Security-Policy-Report-Only") is None   # nicht auf JSON
assert A.get("/").headers.getlist("Content-Security-Policy-Report-Only")                 # auch angemeldete Seiten

# --- Meldeempfaenger (ohne Anmeldung)
csp.clear()
report = {"csp-report": {"document-uri": "http://h/admin?token=GEHEIM#frag", "violated-directive": "script-src-attr", "effective-directive": "script-src-attr",
                         "blocked-uri": "inline", "line-number": 42, "source-file": "http://h/admin?x=SECRET", "script-sample": "showTab('a')", "disposition": "report"}}
for i in range(3):
    r = anon.post("/api/csp-report?p=b", data=json.dumps(report), content_type="application/csp-report")
    assert r.status_code == 204 and r.get_data() == b""
r = anon.post("/api/csp-report?p=a", json={"csp-report": {"document-uri": "http://h/", "effective-directive": "connect-src", "blocked-uri": "https://evil.example/x?k=1#y"}})
assert r.status_code == 204
sm = A.get("/api/csp-reports").get_json()
assert sm["policies"]["b"]["reports"] == 3 and sm["policies"]["b"]["places"] == 1 and sm["policies"]["a"]["reports"] == 1, sm["policies"]
e = next(x for x in sm["entries"] if x["p"] == "b")
assert e["n"] == 3 and e["rule"] == "script-src-attr" and e["blocked"] == "inline" and e["page"] == "/admin" and e["line"] == 42 and e["sample"] == "showTab(…)"
assert "GEHEIM" not in json.dumps(sm) and "SECRET" not in json.dumps(sm) and "frag" not in json.dumps(sm)      # Parameter und Anker nicht gespeichert
assert any(x["blocked"] == "https://evil.example/x" for x in sm["entries"])                                   # fremde Adresse nur mit Host und Pfad

# --- Beispiele enthalten nie Parameter (Kennwoerter, Schluessel): nur der Name
csp.record("b", {"document-uri": "http://h/smarthome", "effective-directive": "script-src-attr", "blocked-uri": "inline", "line-number": 7,
                 "script-sample": "foundAdd(this, '192.168.2.5', 'GEHEIMESPASSWORT')"})
csp.record("b", {"document-uri": "http://h/x", "effective-directive": "script-src-elem", "blocked-uri": "inline", "line-number": 1, "script-sample": "window.TOKEN = 'abc123geheim'"})
dump = json.dumps(A.get("/api/csp-reports").get_json()) + open(csp.PATH, encoding="utf-8").read()
assert "GEHEIMESPASSWORT" not in dump and "192.168.2.5" not in dump and "abc123geheim" not in dump
assert any(x["sample"] == "foundAdd(…)" for x in A.get("/api/csp-reports").get_json()["entries"])

# --- Unbrauchbares, Grosses, Unbekanntes: immer 204, nichts gespeichert, kein Absturz
n_before = len(csp.summary()["entries"])
for body, ct in (("kein json", "application/csp-report"), (json.dumps([1, 2]), "application/json"), (json.dumps({"csp-report": "text"}), "application/csp-report"), ("", "application/json")):
    assert anon.post("/api/csp-report", data=body, content_type=ct).status_code == 204
assert anon.post("/api/csp-report?p=zzz", json=report).status_code == 204
assert anon.post("/api/csp-report", data="x" * (csp.MAX_BODY + 10), content_type="application/csp-report").status_code == 204
assert len(csp.summary()["entries"]) == n_before
assert anon.get("/api/csp-report").status_code in (401, 405)                  # nur POST

# --- Begrenzung der Anzahl verschiedener Meldungen
csp.clear()
for i in range(csp.MAX_KEYS + 50):
    csp.record("a", {"document-uri": "http://h/p%d" % i, "effective-directive": "img-src", "blocked-uri": "https://x/%d" % i})
assert len(csp.summary(limit=1000)["entries"]) == csp.MAX_KEYS

# --- Begrenzung der Menge pro Besucher
csp._rate.clear()
codes = [anon.post("/api/csp-report?p=a", json=report).status_code for _ in range(csp.RATE_PER_MIN + 20)]
assert set(codes) == {204}                                                          # zu viele werden still ignoriert (aber nicht abgelehnt)
csp._rate.clear()

# --- Ansehen und Zuruecksetzen nur fuer Administratoren
L = login("leser", "leserpass12345")
assert anon.get("/api/csp-reports").status_code == 401
assert L.get("/api/csp-reports").status_code == 403 and L.delete("/api/csp-reports").status_code == 403
assert A.get("/api/csp-reports").status_code == 200
assert A.delete("/api/csp-reports").status_code == 200 and A.get("/api/csp-reports").get_json()["entries"] == []

# --- Die Karte ist nur fuer Administratoren in den Einstellungen
assert 'id="csp-card"' in A.get("/admin").get_data(as_text=True)
assert 'id="csp-card"' not in L.get("/admin").get_data(as_text=True)

print("t_csp OK")
