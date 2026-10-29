"""Regel-/Automatik-Logbuch: Zaehler, Lesemarke, Leeren, Uhrensprung (Zeilen nicht zeitlich geordnet), Fehlermeldungen statt stillem Misserfolg."""
import sys, os, json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import autolog
from auth import UserStore
autolog.PATHS = {m: os.path.join(tmp, f"{m}_log.jsonl") for m in autolog.MODULES}
autolog.READ_PATH = os.path.join(tmp, "read.json")
webapp.users = UserStore(os.path.join(tmp, "u_al.json")); webapp.users.create("admin", "adminpass1")
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
now = datetime.now()
def add(module, when, text="x"):
    autolog.log(module, text, now=when)

# 1) normal: Eintraege zaehlen als ungelesen, Lesemarke setzt sie auf 0, neue kommen wieder
for i in range(3): add("rules", now - timedelta(minutes=10 - i))
assert c.get("/api/automation/unread").get_json()["rules"] == 3
assert c.post("/api/automation/log/read", json={"module": "rules"}).status_code == 200 and c.get("/api/automation/unread").get_json()["rules"] == 0
add("rules", datetime.now() + timedelta(seconds=2)); assert c.get("/api/automation/unread").get_json()["rules"] == 1
# 2) Uhrensprung: zuletzt geschriebene Zeilen haben alte Zeitstempel (Neustart ohne Uhr) - die Liste muss die jungen Eintraege trotzdem zeigen
autolog.clear("rules"); autolog.mark_read("rules", datetime.now() - timedelta(days=1))
add("rules", now - timedelta(minutes=5), "jung1"); add("rules", now - timedelta(minutes=4), "jung2")
add("rules", datetime(2020, 1, 1), "uralt")                                                         # zuletzt geschrieben, aber uralter Zeitstempel
rows = c.get("/api/automation/log?module=rules&days=30").get_json()["entries"]
assert [r["text"] for r in rows] == ["jung2", "jung1"], rows                                       # vorher: leere Liste, weil bei "uralt" abgebrochen wurde
assert c.get("/api/automation/unread").get_json()["rules"] == 2                                      # Zaehler und Liste passen zusammen
# 3) Leeren setzt den Zaehler auf 0 und meldet die Anzahl
r = c.post("/api/automation/log/clear", json={"module": "rules"}); assert r.status_code == 200 and r.get_json()["deleted"] == 3
assert c.get("/api/automation/unread").get_json()["rules"] == 0 and c.get("/api/automation/log?module=rules").get_json()["entries"] == []
# 4) Datei nicht beschreibbar (Rechte): Leeren und Lesemarke melden den Fehler, statt still "ok" zu sagen
bad_dir = os.path.join(tmp, "gesperrt"); os.makedirs(bad_dir)
autolog.PATHS["rules"] = bad_dir                                                                     # ein Verzeichnis statt einer Datei: Oeffnen zum Schreiben schlaegt fehl
r = c.post("/api/automation/log/clear", json={"module": "rules"}); assert r.status_code == 500 and "Schreibrechte" in r.get_json()["error"], r.get_data(as_text=True)
autolog.PATHS["rules"] = os.path.join(tmp, "rules_log.jsonl")
autolog.READ_PATH = bad_dir
r = c.post("/api/automation/log/read", json={"module": "rules"}); assert r.status_code == 500 and "Lesemarke" in r.get_json()["error"], r.get_data(as_text=True)
autolog.READ_PATH = os.path.join(tmp, "read.json")
assert c.post("/api/automation/log/read", json={"module": "rules"}).status_code == 200
assert c.post("/api/automation/log/read", json={"module": "quatsch"}).status_code == 400 and c.post("/api/automation/log/clear", json={"module": "quatsch"}).status_code == 400
# 5) Installation OHNE Energie-Modul (wie am Hof): das Regel-Logbuch muss trotzdem laden, als gelesen markieren und leeren
for m in ("rules",): autolog.log(m, "Hof-Eintrag", now=datetime.now())
cf = store.load_config(); old = dict(cf.get("modules") or {}); cf["modules"] = {"energy": False, "smarthome": True, "cameras": False, "verlauf": False, "alexa": False}; store.save_config(cf)
r = c.get("/api/automation/log?module=rules&days=30"); assert r.status_code == 200 and [e["text"] for e in r.get_json()["entries"]] == ["Hof-Eintrag"], r.get_data(as_text=True)    # vorher: 403 -> Seite zeigte "Keine Eintraege"
assert c.get("/api/automation/unread").get_json()["rules"] == 1
assert c.post("/api/automation/log/read", json={"module": "rules"}).status_code == 200 and c.get("/api/automation/unread").get_json()["rules"] == 0   # Zaehler faellt auf 0
autolog.log("rules", "noch einer", now=datetime.now() + timedelta(seconds=2)); assert c.get("/api/automation/unread").get_json()["rules"] == 1
assert c.post("/api/automation/log/clear", json={"module": "rules"}).status_code == 200 and c.get("/api/automation/unread").get_json()["rules"] == 0
assert c.get("/api/automation/log?module=surplus").status_code == 403                            # Ueberschuss-Automatik gibt es ohne Energie nicht
# kein Administrator: weiter gesperrt, auch mit Regel-Recht
webapp.users.create("regel", "regelpass123", {"dashboard": "write", "rules": "write", "settings_geraete": "write"})
k = webapp.app.test_client(); k.post("/login", data={"username": "regel", "password": "regelpass123"})
assert k.get("/api/automation/log?module=rules").status_code == 403 and k.post("/api/automation/log/clear", json={"module": "rules"}).status_code == 403
cf["modules"] = old; store.save_config(cf)
print("AUTOLOG OK")
