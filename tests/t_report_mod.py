import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import report, opslog
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_rm.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
opslog.log("tick_error", "Durchlauf kaputt", dry=False); opslog.log("backup", "Sicherung ok", dry=False); opslog.log("battery", "Akku niedrig", dry=False)
# Energie AN: wie bisher
j = A.get("/api/report?days=3").get_json()
assert j["energy"] is True and j["current"] is not None and "tick" in {c["key"] for c in j["checks"]} and "errors" in {c["key"] for c in j["checks"]}, j
md = A.get("/api/report?format=md&days=3").get_data(as_text=True); assert "## Jetzt" in md and "## Tage" in md
kinds = {e["kind"] for e in j["events"]}; assert {"tick_error", "backup", "battery"} <= kinds, kinds
# Energie AUS
cfg["modules"] = {"energy": False, "smarthome": True, "verlauf": True, "cameras": True, "alexa": False}
j = A.get("/api/report?days=3").get_json()
assert j["energy"] is False and j["current"] is None and j["days"] == [] and j["planner"] is None and j["savings"] is None and j["pv_cal"] is None, j
keys = {c["key"] for c in j["checks"]}; assert keys == {"restarts", "files", "backups", "disk", "notify"} | ({"rules"} & keys) | ({"report"} & keys), keys
assert not (set(j["settings"]) & report.ENERGY_SETTINGS), j["settings"]
kinds = {e["kind"] for e in j["events"]}; assert "backup" in kinds and not (kinds & report.ENERGY_KINDS), kinds
md = A.get("/api/report?format=md&days=3").get_data(as_text=True)
for bad in ("## Jetzt", "## Tage", "SOC", "Strategie", "VRM", "Tibber", "Planer", "Ersparnis"): assert bad not in md, bad
assert "## Ereignisse" in md and "## Einstellungen" in md and "Sicherung ok" in md
html = A.get("/report").get_data(as_text=True); assert "Zustand der App und ihrer Dienste" in html and "Zustand von Regelung, Prognose" not in html
print("REPORT-MODUL OK")
