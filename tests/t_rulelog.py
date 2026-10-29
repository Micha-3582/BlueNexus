"""Regel-Ereignisse stehen im allgemeinen Logbuch (Kategorie Regeln); das eigene Regel-Logbuch ist weg (Weiterleitung)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import autolog, devicelog
from auth import UserStore
autolog.PATHS = {m: os.path.join(tmp, f"{m}_log.jsonl") for m in autolog.MODULES}
autolog.READ_PATH = os.path.join(tmp, "read.json")
store.module_on = lambda n, cfg=None: True
webapp.users = UserStore(os.path.join(tmp, "u_rl.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("lese", "lesepass123", {"dashboard": "write", "rules": "write", "settings_geraete": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
L = webapp.app.test_client(); L.post("/login", data={"username": "lese", "password": "lesepass123"})
entries = lambda q="": A.get("/api/devicelog" + q).get_json()["entries"]

autolog.log("rules", "Küchenlicht eingeschaltet – Tür offen", dev="Küchenlicht", action="on", rule="r1")
autolog.log("rules", "(Trockenlauf) Küchenlicht würde ausgeschaltet", dev="Küchenlicht", action="off", dry=True, rule="r1")
autolog.log("rules", "Regel „Tor“: Schritt fehlgeschlagen (weg)", dev="Tor", action="fail", rule="r2")
autolog.log("surplus", "Wasserheizer eingeschaltet", dev="Wasserheizer", action="on")            # Ueberschuss-Automatik behaelt ihr eigenes Logbuch
e = entries("?cat=regel")
assert [x["text"] for x in e] == ["Regel „Tor“: Schritt fehlgeschlagen (weg)", "(Trockenlauf) Küchenlicht würde ausgeschaltet", "Küchenlicht eingeschaltet – Tür offen"], e
assert e[0]["ok"] is False and e[0]["by"] == "Regel" and e[1]["by"] == "Regel (Trockenlauf)" and e[2]["ref"] == "rule:r1" and e[2]["name"] == "Küchenlicht" and e[2]["cat"] == "regel"
assert not any("Wasserheizer" in x["text"] for x in entries())                                  # surplus bleibt getrennt
assert len(entries()) == 3 and len(entries("?cat=aktor")) == 0                                    # "Alles" enthaelt sie, die Aktor-Ansicht nicht
assert [x["text"] for x in entries("?q=Trockenlauf")] == ["(Trockenlauf) Küchenlicht würde ausgeschaltet"]
# die alte Regel-Logbuch-Seite leitet ins allgemeine Logbuch
r = A.get("/rules-log"); assert r.status_code == 302 and r.headers["Location"].endswith("/smarthome#logbuch"), r.status_code
r2 = L.get("/rules-log"); assert r2.status_code in (302, 403) and not r2.headers.get("Location", "").endswith("#logbuch")      # Nicht-Administratoren kommen nicht ins Logbuch
page = A.get("/rules").get_data(as_text=True); assert "/rules-log" not in page and "/smarthome#logbuch" in page and 'data-log-badge="rules"' not in page
assert L.get("/api/devicelog").status_code == 403                                                  # weiter nur Administratoren
# das Betriebs-Datenmaterial (Berichte) bleibt: die alte Datei wird weiter beschrieben
assert len(autolog.recent("rules")) == 3
print("REGEL-LOGBUCH OK")
