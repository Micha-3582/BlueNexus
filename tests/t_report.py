import os, sys, json
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
root = sys.argv[1]
webapp, store, cfg, tmp = ps_common.setup(root)
import opslog, notify, report, vrm
opslog.EVENTS_PATH = os.path.join(tmp, "ev.jsonl"); opslog.STATS_PATH = os.path.join(tmp, "st.json"); opslog._stats = None
notify.CRED_PATH = os.path.join(tmp, "tg.json"); notify.STATE_PATH = os.path.join(tmp, "ns.json")
store.PRICE_HISTORY_PATH = os.path.join(tmp, "ph.json"); store._price_cache = None
store.BACKUP_DIR = os.path.join(tmp, "backups"); os.makedirs(store.BACKUP_DIR); open(os.path.join(store.BACKUP_DIR, "history.json-2026-09-26.json"), "w").write("{}")
store.HISTORY_PATH = os.path.join(tmp, "h.json"); store.MONTHLY_PATH = os.path.join(tmp, "m.json"); store.SOLAR_LOG_PATH = os.path.join(tmp, "s.json")
store.PLANSIM_LOG_PATH = os.path.join(tmp, "ps.json") if hasattr(store, "PLANSIM_LOG_PATH") else None
sent = []; notify._send_async = lambda text: sent.append(text)
json.dump({"token": "1:T", "chat_id": "5"}, open(notify.CRED_PATH, "w"))
vrm.CREDENTIALS_PATH = os.path.join(tmp, "vrm.json"); json.dump({"token": "T", "installation_id": "1"}, open(vrm.CREDENTIALS_PATH, "w"))
cfg.update({"app_display_name": "Testanlage", "dry_run": False, "poll_seconds": 300})
ctrl = webapp.ctrl

# ---- opslog: Ereignisse, Kuerzen, Zaehler
opslog.log("startup", "Steuerung gestartet"); opslog.log("tick_error", "Cerbo nicht erreichbar")
ev = opslog.recent(10); assert [e["kind"] for e in ev] == ["tick_error", "startup"]
assert opslog.recent(10, {"startup"})[0]["text"] == "Steuerung gestartet"
opslog.MAX_EVENT_BYTES = 2000
for i in range(120): opslog.log("ess", f"Wechsel {i}", n=i)
assert os.path.getsize(opslog.EVENTS_PATH) < 2600 and opslog.recent(1)[0]["n"] == 119      # aelteste fallen weg, neueste bleiben
opslog.MAX_EVENT_BYTES = 3_000_000
t0 = datetime.now().replace(hour=10, minute=0, second=0)
opslog.note_tick(True, t0); opslog.note_tick(True, t0 + timedelta(seconds=300)); opslog.note_tick(True, t0 + timedelta(seconds=300 + 1500)); opslog.note_tick(False, t0 + timedelta(seconds=2000))
day = opslog.stats_days()[t0.date().isoformat()]
assert day["ticks_ok"] == 3 and day["ticks_err"] == 1 and day["max_gap_s"] == 1500, day
opslog.count("src_vrm", 5, now=t0); opslog.flush(); opslog._stats = None
assert opslog.stats_days()[t0.date().isoformat()]["src_vrm"] == 5                            # ueberlebt Neustart

# ---- Hooks im Tick
opslog.EVENTS_PATH = os.path.join(tmp, "ev2.jsonl"); opslog.STATS_PATH = os.path.join(tmp, "st2.json"); opslog._stats = None
webapp.Cerbo.read_ess_mode = lambda self: 9        # Plan will Ruhe (10) -> Umschaltung
ctrl.safe_tick()
today = datetime.now().date().isoformat()
d = opslog.stats_days()[today]
assert d["ticks_ok"] == 1 and d.get("src_vrm") == 1 and d.get("tibber_live") == 1, d
assert d.get("ess_writes") == 1 and any(e["kind"] == "ess" for e in opslog.recent(20)), (d, opslog.recent(5))    # Fake-Cerbo steht auf 10, Plan wechselt/bleibt
ctrl.tick = lambda: (_ for _ in ()).throw(RuntimeError("Tibber down")); ctrl.safe_tick(); ctrl.safe_tick()
errs = opslog.recent(20, {"tick_error"}); assert len(errs) == 1 and errs[0]["text"] == "Tibber down"          # nicht bei jedem Durchlauf
assert opslog.stats_days()[today]["ticks_err"] == 2
del ctrl.tick; ctrl.safe_tick(); assert opslog.recent(3)[0]["kind"] in ("tick_ok", "ess") and any(e["kind"] == "tick_ok" for e in opslog.recent(10))

# ---- Bericht
r = report.build(days=3, ctrl=webapp._ctrl_info())
keys = {c["key"]: c for c in r["checks"]}
assert keys["tick"]["status"] == "ok" and keys["dry_run"]["status"] == "ok" and keys["vrm"]["status"] == "ok", {k: (v["status"], v["detail"]) for k, v in keys.items()}
assert keys["errors"]["status"] in ("warn", "fail") and "heute 2" in keys["errors"]["detail"]            # die zwei gefakten Fehler
assert r["verdict"] in ("warn", "fail") and r["app"] == "Testanlage"
md = report.to_markdown(r)
assert "# Betriebsbericht – Testanlage" in md and "## Ergebnis" in md and "Tibber down" in md and "## Tage" in md and "## Einstellungen" in md, md[:400]
cfg["dry_run"] = True
r2 = report.build(days=3, ctrl=webapp._ctrl_info()); assert {c["key"]: c for c in r2["checks"]}["dry_run"]["status"] == "warn"
# alte Durchlaeufe -> Regelung nicht mehr aktuell
c2 = webapp._ctrl_info(); c2["last_tick"] = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
assert {c["key"]: c for c in report.build(ctrl=c2)["checks"]}["tick"]["status"] == "fail"
# defekte Datei wird erkannt
open(os.path.join(tmp, "h.json"), "w").write("{kaputt")
# (Datei liegt nicht im App-Ordner -> Pruefung betrachtet nur store._DIR; hier nur: Bericht bricht nicht)
report.build(ctrl=webapp._ctrl_info())

# Planer-Zeile nutzt die Restwert-bereinigten Kosten
c3 = webapp._ctrl_info()
if c3.get("plansim") and c3["plansim"].get("available"):
    assert "Unterschied inkl. Akku-Restwert" in report.to_markdown(report.build(ctrl=c3))

# ---- Endpunkte
class U:
    def get(self, n): return {"username": "t"}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U()
c = webapp.app.test_client()
with c.session_transaction() as s: s["user"] = "t"
j = c.get("/api/report?days=3").get_json(); assert j["verdict"] in ("ok", "warn", "fail") and j["checks"] and "days" in j
t = c.get("/api/report?format=md&days=3"); assert t.status_code == 200 and "text/plain" in t.headers["Content-Type"] and "Betriebsbericht" in t.get_data(as_text=True)
assert c.get("/report").status_code == 200
# ---- Telegram-Tageszusammenfassung enthaelt Kurz-Systemcheck
store.energy_week_summary = lambda now=None, **k: {"days": [{"day": "x", "solar": 20.0, "verbrauch": 25.0, "import": 5.0, "export": 1.0, "autarky": 80.0, "cost_eur": 1.5}]}
cfg.update({"notify_events": {"summary": True}, "notify_summary_hour": 0})
sent.clear(); notify.daily_summary(cfg, datetime.now(), extra=ctrl._report_line)
assert len(sent) == 1 and "Tagesbilanz" in sent[0] and "🩺 Systemcheck" in sent[0], sent
print("REPORT OK", root.split("/")[-1])
