"""Prüfung 14.11.2026 (1.63.2): Skript-Einschleusung (XSS) über Freitext, den auch ein Konto ohne Administratorrechte setzen kann.
Gefunden im Browser-Test: (1) Die Notiz eines Ladetermins (Vorlage "Benutzer" darf Ladetermine anlegen) stand ungeschützt auf dem Dashboard,
(2) der Name eines PV-Wechselrichters stand ungeschützt in den Einstellungen, in der Einrichtung und auf der Dashboard-Kachel.
Hier: Eingaben werden auf Text und Länge begrenzt (Server), und die Stellen in den Seiten schützen Texte (Regressionswächter über den Quelltext)."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import auth
from auth import UserStore
from datetime import datetime, timedelta

webapp.users = UserStore(os.path.join(tmp, "u.json"))
webapp.users.create("admin", "adminpass1")
webapp.users.create("anna", "annapass12345", dict(auth.PRESETS["user"]))        # Vorlage "Benutzer": Dashboard schreiben
webapp.opslog.log = lambda *a, **k: None
APP_DIR = os.path.join(os.path.dirname(os.path.abspath(webapp.__file__)))


def login(name, pw):
    c = webapp.app.test_client()
    assert c.post("/login", data={"username": name, "password": pw}).status_code == 302
    return c


A, N = login("admin", "adminpass1"), login("anna", "annapass12345")

# --- Ladetermin-Notiz: nur Text, höchstens 200 Zeichen
s, e = datetime.now() + timedelta(hours=1), datetime.now() + timedelta(hours=3)
body = {"start": s.isoformat(timespec="minutes"), "end": e.isoformat(timespec="minutes")}
r = N.post("/api/ev", json={**body, "note": "x" * 500})
assert r.status_code == 201 and len(r.get_json()["note"]) == 200
r = N.post("/api/ev", json={**body, "note": {"a": "<img src=x>"}})                 # kein Text -> leer
assert r.status_code == 201 and r.get_json()["note"] == ""
r = N.post("/api/ev", json={**body, "note": 12345})
assert r.status_code == 201 and r.get_json()["note"] == ""
r = N.post("/api/ev", json={**body, "note": "  Auto laden  "})
assert r.status_code == 201 and r.get_json()["note"] == "Auto laden"

# --- PV-Wechselrichter in der Konfiguration: [{name, unit}] und nichts anderes
good = [{"name": "WR1", "unit": 80}, {"name": "WR2", "unit": "81"}]
assert A.post("/api/config", json={"pv_inverters": good}).status_code == 200
assert store.load_config()["pv_inverters"] == [{"name": "WR1", "unit": 80}, {"name": "WR2", "unit": 81}]
for bad in ("text", {"name": "x", "unit": 1}, [{"name": "x"}], [{"name": "", "unit": 1}], [{"name": "x", "unit": "<b>"}], [{"name": "x", "unit": -1}],
            [{"name": "x", "unit": 70000}], ["x"], [None], [{"name": "x", "unit": 1}] * 21):
    r = A.post("/api/config", json={"pv_inverters": bad})
    assert r.status_code == 400, (bad if not isinstance(bad, list) or len(bad) < 5 else "21 Eintraege", r.status_code)
assert store.load_config()["pv_inverters"] == [{"name": "WR1", "unit": 80}, {"name": "WR2", "unit": 81}]       # unverändert
r = A.post("/api/config", json={"pv_inverters": [{"name": "<img src=x onerror=1>" + "y" * 80, "unit": 5, "extra": "<script>"}]})
assert r.status_code == 200
saved = store.load_config()["pv_inverters"]
assert len(saved) == 1 and set(saved[0]) == {"name", "unit"} and len(saved[0]["name"]) == 40          # Länge begrenzt, keine Zusatzfelder

# --- Regressionswächter: die Stellen in den Seiten schützen Texte
read = lambda p: open(os.path.join(APP_DIR, "templates", p), encoding="utf-8").read()
idx, adm, setup = read("index.html"), read("admin.html"), read("setup.html")
assert "'<br><span class=\"muted\">' + escH(i.note) + '</span>'" in idx, "Ladetermin-Notiz muss mit escH ausgegeben werden"
assert not re.search(r"\+\s*i\.note\s*\+", idx)
assert "sun + ' ' + escH(s.name)" in idx, "Name der PV-Quelle auf der Dashboard-Kachel"
for frag in ("${escH(s.ess_text)}", "${escH(s.strategy)}", "${escH(s.pv_source || '–')}", "${escH(s.pv_note)}", "${escH(s.reason || '–')}", "${escH(d.last_error)}"):
    assert frag in idx, frag
assert re.search(r"^function escH\(t\)", idx, re.M) and "const escH" not in idx          # als Funktion: gilt auch für Code oberhalb der Definition
for name, src in (("admin.html", adm), ("setup.html", setup)):
    assert 'class="pvi-name" value="${escH(p.name||\'\')}"' in src, name
    assert 'class="pvi-unit" value="${escH(p.unit??\'\')}"' in src, name
    assert "${p.name||''}" not in src and "${p.unit??''}" not in src, name
assert re.search(r"^function escH\(t\)", setup, re.M)                                    # setup.html hat die Funktion selbst

print("t_sicherheit5 OK")
