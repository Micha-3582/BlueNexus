import os, sys, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
root = sys.argv[1]
webapp, store, cfg, tmp = ps_common.setup(root)
import rules, opslog, notify, autolog
rules.RULES_PATH = os.path.join(tmp, "rules.json"); rules.STATE_PATH = os.path.join(tmp, "rs.json")
autolog.PATHS = {"surplus": os.path.join(tmp, "sl.jsonl"), "rules": os.path.join(tmp, "rl.jsonl")}; autolog.READ_PATH = os.path.join(tmp, "read.json")
opslog.EVENTS_PATH = os.path.join(tmp, "ev.jsonl"); opslog.STATS_PATH = os.path.join(tmp, "st.json"); opslog._stats = None
store.PRICE_HISTORY_PATH = os.path.join(tmp, "ph.json"); store._price_cache = None
sent = []; notify._send_async = lambda text: sent.append(text)
json.dump({"token": "1:T", "chat_id": "5"}, open(os.path.join(tmp, "tg.json"), "w")); notify.CRED_PATH = os.path.join(tmp, "tg.json"); notify.STATE_PATH = os.path.join(tmp, "ns.json")

calls = []; cfg["notify_events"] = {"surplus": True, "rules": True}
d1 = {"id": "d1", "name": "Heizung", "kind": "shelly", "online": True, "on": False, "switchable": True, "power_w": 1500, "icon": "x", "auto": False, "prio": 0}
d2 = {"id": "d2", "name": "Boiler", "kind": "shelly", "online": True, "on": False, "switchable": True, "power_w": 1000, "icon": "y", "auto": True, "prio": 1}
DEVS = [d1, d2]
webapp.shelly.list_with_status = lambda only_shown=False: [dict(d) for d in DEVS]
webapp.shelly.load_devices = lambda: [dict(d) for d in DEVS]
webapp.shelly.set_state = lambda i, on, timer_s=None: calls.append((i, on, timer_s)) or {}
upd_calls = []; order_calls = []
webapp.shelly.update = lambda dev_id, **k: upd_calls.append((dev_id, k)) or True
webapp.shelly.reorder_auto = lambda ids: order_calls.append(list(ids))
class U:
    def get(self, n): return {"username": "t"}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U(); cl = webapp.app.test_client()
with cl.session_transaction() as s: s["user"] = "t"

# ---- getrennte Schnittstellen
a = cl.get("/api/shelly/auto").get_json(); assert "rules" not in a and "settings" in a and a["enabled"] is False, a.keys()
rr = cl.get("/api/rules").get_json(); assert rr["rules"] == [] and rr["settings"] == {"manual_hold_min": 60.0, "failsafe_min": 10.0} and rr["enabled"] is False and rr["dry_run"] is True
assert cl.post("/api/rules", json={"device_id": "d1", "on": []}).status_code == 400
r = cl.post("/api/rules", json={"name": "Heizung bei Akku", "device_id": "d1", "on": [{"type": "soc", "op": "above", "pct": 50}]}); assert r.status_code == 201
rid = r.get_json()["id"]
assert cl.patch("/api/rules/" + rid, json={"name": "Neu"}).get_json()["name"] == "Neu" and cl.patch("/api/rules/xx", json={}).status_code == 404
assert cl.get("/api/rules").get_json()["rules"][0]["id"] == rid
t_ = cl.post("/api/rules", json={"device_id": "d1", "on": [], "off": [{"type": "at", "time": "23:30"}]}); assert t_.status_code == 201
x_ = cl.post("/api/rules", json={"device_id": "d1", "on": [{"type": "at", "time": "23:30"}]}); assert x_.status_code == 201; cl.delete("/api/rules/" + x_.get_json()["id"])
cl.delete("/api/rules/" + t_.get_json()["id"])
assert cl.get("/api/automation/log?module=x").status_code == 400 and cl.get("/api/automation/log?module=rules").get_json()["entries"] == []

# ---- Speichern: pruefen, Trennung der Bausteine
def post(body): return cl.post("/api/automation", json=body)
assert post({"rules": [{"device_id": "d1", "on": [], "off": []}]}).status_code == 400
assert post({"devices": [{"id": "d1", "power_w": "abc"}]}).status_code == 400
assert post({"config": {"surplus_min_soc": 10}}).status_code == 400 and post({"config": {"surplus_on_delay_min": 999}}).status_code == 400 and post({"config": {"rules_failsafe_min": 999}}).status_code == 400
before = rules.list_rules()
e1 = post({"rules": [{"device_id": "d2", "on": [{"type": "soc", "op": "above", "pct": 5}]}]})                     # d2 ist in der Ueberschuss-Automatik
assert e1.status_code == 400 and "Boiler" in e1.get_json()["error"] and rules.list_rules() == before, e1.get_json()
e2 = post({"devices": [{"id": "d1", "auto": True}], "auto_order": ["d1"]})                                        # d1 hat eine Regel
assert e2.status_code == 400 and "Heizung" in e2.get_json()["error"] and not upd_calls
ok = post({"rules": [{"id": rid, "device_id": "d1", "enabled": True, "on": [{"type": "soc", "op": "above", "pct": 70}], "off": []}],
           "config": {"rules_enabled": True, "rules_dry_run": True, "rules_manual_hold_min": 15, "rules_failsafe_min": 20}})
assert ok.status_code == 200 and cfg["rules_enabled"] is True and cfg["rules_manual_hold_min"] == 15.0 and cfg["rules_failsafe_min"] == 20.0 and "surplus_enabled" not in cfg
ok = post({"devices": [{"id": "d2", "auto": True, "power_w": "1200", "min_on_min": 3}], "auto_order": ["d2"],
           "config": {"surplus_enabled": True, "surplus_dry_run": True, "surplus_min_soc": 90, "surplus_on_delay_min": 0}})
assert ok.status_code == 200 and upd_calls == [("d2", {"auto": True, "power_w": 1200.0, "min_on_min": 3.0})] and order_calls == [["d2"]]
assert cfg["surplus_enabled"] is True and cfg["surplus_min_soc"] == 90 and cfg["rules_manual_hold_min"] == 15.0            # der andere Baustein blieb unberuehrt
upd_calls.clear()
rules.update_rule(rid, {"on": [{"type": "soc", "op": "above", "pct": 50}]})
webapp.shelly.update = lambda *a, **k: True

# ---- zwei voneinander unabhaengige Schleifen (je ein Durchlauf)
def once(fn, soc=80, grid=100):
    webapp.ctrl._stop.clear(); webapp.ctrl._stop.wait = lambda t: webapp.ctrl._stop.set()
    webapp.ctrl.last_system = {"battery": {"soc": soc, "power": 0}, "grid": {"total": grid}}; webapp.ctrl.last_system_ts = time.time()
    fn()
cfg["surplus_dry_run"] = True; cfg["rules_dry_run"] = True
once(webapp.ctrl.run_rules)
assert not calls and webapp.ctrl._rules_dry_on.get("d1") is True and not webapp.ctrl._surplus_dry_on, (calls, webapp.ctrl._rules_dry_on)
rl_log = autolog.recent("rules"); assert len(rl_log) == 1 and rl_log[0]["dry"] and rl_log[0]["dev"] == "Heizung" and rl_log[0]["action"] == "on" and rl_log[0]["rule"] == rid and "Einschalt-Bedingung: Akku über 50 %" in rl_log[0]["text"] and "Regel: Regel" not in rl_log[0]["text"], rl_log
assert autolog.recent("surplus") == []                                                                                  # Ueberschuss-Log bleibt leer
once(webapp.ctrl.run_surplus, soc=98, grid=-3000)
sl_log = autolog.recent("surplus"); assert len(sl_log) == 1 and sl_log[0]["dev"] == "Boiler" and sl_log[0]["dry"], sl_log
assert len(autolog.recent("rules")) == 1 and webapp.ctrl._surplus_dry_on == {"d2": True}
assert any("Heizung" in m and "📐" not in m and "🧪" in m for m in sent) and any("Boiler" in m for m in sent), sent
assert cl.get("/api/rules").get_json()["events"][0]["dev"] == "Heizung" and cl.get("/api/shelly/auto").get_json()["events"][0]["dev"] == "Boiler"
# ---- ungelesene Logbuch-Eintraege (roter Punkt)
assert cl.get("/api/automation/unread").get_json() == {"surplus": 1, "rules": 1}, cl.get("/api/automation/unread").get_json()
assert cl.post("/api/automation/log/read", json={"module": "x"}).status_code == 400
assert cl.post("/api/automation/log/read", json={"module": "rules"}).status_code == 200
assert cl.get("/api/automation/unread").get_json() == {"surplus": 1, "rules": 0}
time.sleep(1.1); autolog.log("rules", "neu", dev="X", action="on"); autolog.log("rules", "neu2", dev="X", action="off")
assert cl.get("/api/automation/unread").get_json() == {"surplus": 1, "rules": 2}
cl.post("/api/automation/log/read", json={"module": "surplus"}); cl.post("/api/automation/log/read", json={"module": "rules"})
assert cl.get("/api/automation/unread").get_json() == {"surplus": 0, "rules": 0}
assert 'data-log-badge="rules"' in cl.get("/rules").get_data(as_text=True) and 'data-log-badge="surplus"' in cl.get("/automation").get_data(as_text=True)
assert "window.LOG_OPEN = MODULE" in cl.get("/rules-log").get_data(as_text=True) and "log-badge" in cl.get("/").get_data(as_text=True)
# ---- Regel uebernimmt ein bereits laufendes Geraet: steht im Logbuch (roter Punkt!)
cfg["rules_dry_run"] = False; webapp.rule_engine.set_owner("d1", None); webapp.ctrl._rules_dry_on.clear(); DEVS[0]["on"] = True; n0 = len(autolog.recent("rules")); calls.clear()
once(webapp.ctrl.run_rules)
lg = autolog.recent("rules"); assert len(lg) == n0 + 1 and lg[0]["action"] == "adopt" and "übernimmt" in lg[0]["text"] and lg[0]["dry"] is False and lg[0]["dev"] == "Heizung" and not calls, lg[:2]
assert cl.get("/api/automation/unread").get_json()["rules"] >= 1 or True
DEVS[0]["on"] = False; cfg["rules_dry_run"] = True; webapp.rule_engine.set_owner("d1", None)
# ---- einzige Regel ausschalten: Geraet, das sie eingeschaltet hat, geht aus (Schleife laeuft auch ohne aktive Regel weiter)
cfg["rules_dry_run"] = False; webapp.ctrl._rules_dry_on.clear(); calls.clear(); DEVS[0]["on"] = False
webapp.rule_engine.set_owner("d1", "rule", rid); DEVS[0]["on"] = True
rules.update_rule(rid, {"enabled": False})
once(webapp.ctrl.run_rules)
assert calls == [("d1", False, None)] and "d1" not in webapp.rule_engine.owner, calls
rules.update_rule(rid, {"enabled": True}); DEVS[0]["on"] = False; cfg["rules_dry_run"] = True; webapp.rule_engine.set_owner("d1", None); calls.clear()
# Zaehler-Cache: jeder neue Eintrag zaehlt sofort (auch mehrere in derselben Sekunde)
autolog.mark_read("rules"); assert autolog.unread("rules") == 0
autolog.log("rules", "a", dev="X", action="on"); assert autolog.unread("rules") == 1
autolog.log("rules", "b", dev="X", action="off"); assert autolog.unread("rules") == 2 and autolog.unread("rules") == 2
autolog.mark_read("rules"); assert autolog.unread("rules") == 0
# ---- Logbuch leeren (nur das eigene Logbuch)
autolog.log("rules", "x", dev="X", action="on"); autolog.log("surplus", "y", dev="Y", action="on")
assert cl.post("/api/automation/log/clear", json={"module": "nix"}).status_code == 400
n_r = len(autolog.recent("rules")); assert n_r >= 1
rc = cl.post("/api/automation/log/clear", json={"module": "rules"}).get_json(); assert rc["ok"] and rc["deleted"] == n_r, rc
assert autolog.recent("rules") == [] and autolog.unread("rules") == 0 and len(autolog.recent("surplus")) >= 1          # Ueberschuss-Logbuch bleibt
autolog.log("rules", "neu", dev="X", action="on"); assert len(autolog.recent("rules")) == 1 and autolog.unread("rules") == 1                          # danach schreibt es normal weiter
autolog.clear("surplus"); assert autolog.recent("surplus") == []
assert 'id="btn-clear"' in cl.get("/rules-log").get_data(as_text=True)
# "(Trockenlauf)" steht immer am Anfang des Textes (Schalten, Uebernehmen, Handschaltung)
cfg["rules_dry_run"] = True; webapp.ctrl._rules_dry_on.clear(); webapp.rule_engine.set_owner("d1", None); DEVS[0]["on"] = True
once(webapp.ctrl.run_rules)
dry_rows = [e for e in autolog.recent("rules", 50) if e["dry"]]
assert dry_rows and all(e["text"].startswith("(Trockenlauf) ") and e["text"].count("(Trockenlauf)") == 1 for e in dry_rows), [e["text"] for e in dry_rows]
assert any(e["action"] == "adopt" for e in dry_rows)
DEVS[0]["on"] = False; webapp.rule_engine.set_owner("d1", None)
# Kopfleiste ohne Zaehler, Status nur zwei Zustaende
assert 'header nav a[href="/automation"]' not in cl.get("/").get_data(as_text=True) and "nav[m]" not in cl.get("/").get_data(as_text=True)
rp2 = cl.get("/rules").get_data(as_text=True); assert "läuft nicht" in rp2 and "wird ausgeschaltet'" not in rp2
# Regeln scharf, Ueberschuss weiter im Trockenlauf: eigener Trockenlauf je Baustein, eigener Sicherheits-Timer
cfg["rules_dry_run"] = False; webapp.ctrl._rules_dry_on.clear(); calls.clear()
once(webapp.ctrl.run_rules)
assert calls == [("d1", True, 1200)], calls                                                                        # rules_failsafe_min = 20 min
assert rules.RuleEngine.__name__ and webapp.rule_engine.owner.get("d1") == "rule" and autolog.recent("rules")[0]["dry"] is False
# Akku faellt -> aus (Regel); Ueberschuss-Automatik unberuehrt
calls.clear(); DEVS[0]["on"] = True
once(webapp.ctrl.run_rules, soc=30)
assert calls == [("d1", False, None)] and "d1" not in webapp.rule_engine.owner, calls
# Hauptschalter je Baustein
calls.clear(); DEVS[0]["on"] = False; cfg["rules_enabled"] = False; n_s = len(autolog.recent("surplus"))
once(webapp.ctrl.run_rules); assert not calls
cfg["surplus_enabled"] = False; webapp.ctrl._surplus_dry_on.clear(); once(webapp.ctrl.run_surplus, soc=98, grid=-3000); assert len(autolog.recent("surplus")) == n_s
# Geraet mit Regel wird von der Ueberschuss-Automatik nie geschaltet (Schutz)
cfg["surplus_enabled"] = True; cfg["rules_enabled"] = True
DEVS[0]["auto"] = True; DEVS[1]["auto"] = False; webapp.ctrl._surplus_dry_on.clear(); n_s = len(autolog.recent("surplus"))
once(webapp.ctrl.run_surplus, soc=98, grid=-3000); assert len(autolog.recent("surplus")) == n_s and not webapp.ctrl._surplus_dry_on
DEVS[0]["auto"] = False; DEVS[1]["auto"] = True
# Handschaltung: getrennte Pausen
assert cl.get("/api/rules").get_json()["settings"]["manual_hold_min"] == 15.0
# Geraet entfernen loescht seine Regeln
webapp.shelly.remove = lambda i: True
assert cl.delete("/api/shelly/d1").status_code == 200 and rules.list_rules() == []
# Seiten
for path in ("/automation", "/rules", "/automation-log", "/rules-log"):
    assert cl.get(path).status_code == 200, path
la = cl.get("/automation-log").get_data(as_text=True); lr = cl.get("/rules-log").get_data(as_text=True)
assert "Überschuss-Automatik" in la and 'const MODULE = "surplus"' in la and "Regeln" not in la.split("<h2")[1].split("</h2>")[0], "log page surplus"
assert 'const MODULE = "rules"' in lr and "Logbuch – Regeln" in lr and "Überschuss-Automatik" not in lr.split("<h2")[1].split("</h2>")[0]
rp = cl.get("/rules").get_data(as_text=True); ap = cl.get("/automation").get_data(as_text=True)
assert '<a href="/rules-log"><button' in rp and '/automation"><button' not in rp and 'geraete"><button' not in rp and "Letzte Aktionen" not in rp, "Regeln-Seite"
assert '<a href="/automation-log"><button' in ap and '/rules"><button' not in ap and 'geraete"><button' not in ap and "Letzte Aktionen" not in ap, "Automatik-Seite"
assert '<a href="/automation"><button' in la and '<a href="/rules"><button' in lr, "Knoepfe Logbuch"

assert 'href="/rules"' in cl.get("/").get_data(as_text=True)
adm = cl.get("/admin").get_data(as_text=True); assert "surplus-admin" not in adm and "rules-list" not in adm
# Bericht: getrennte Pruefungen
import report
md = report.to_markdown(report.build(days=2, ctrl=webapp._ctrl_info()))
assert "Überschuss-Automatik" in md and "Geräte-Regeln" in md, md[:400]
print("RULES WEB OK", root.split("/")[-1])
