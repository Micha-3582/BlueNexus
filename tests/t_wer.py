"""Regel: bedient von Konto X + [WER] im Telegram-Text."""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import rules, devicelog, shelly
from datetime import datetime
from flask import g
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_wer.json")); webapp.users.create("admin", "adminpass1"); webapp.users.create("Friedhelm", "friedpass12", {"dashboard": "write", "rules": "write"}); webapp.users.create("Anna", "annapass123", {"dashboard": "write"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
# 1) Normalisierung
c = rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["Friedhelm", " friedhelm ", "", "ANNA"]})
assert c["by"] == ["friedhelm", "anna"], c
assert "by" not in rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": []})
assert "by" not in rules.normalize_condition({"type": "device", "device_id": "d1", "op": "above", "value": 5, "by": ["x"]})   # Leistung: kein "bedient von"
v = rules.normalize_condition({"type": "virtual", "id": "v1", "is": "pressed", "by": ["friedhelm"]}); assert v["by"] == ["friedhelm"]
# 2) Logbuch merkt sich das Konto (Anmeldename)
with webapp.app.test_request_context("/"):
    g.user = "friedhelm"; g.user_display = "Friedhelm"
    devicelog.log("aktor", "device:d1", "Toröffner", "eingeschaltet", True)
w = devicelog.who_last("device:d1"); assert w and w["user"] == "friedhelm" and devicelog.who_name(w) == "Friedhelm", w
assert devicelog.who_last("device:nix") is None
# 3) Bedingung
ctx = {"now": datetime.now(), "devices": {"d1": {"id": "d1", "name": "Toröffner", "online": True, "on": True, "power": None}}, "virtual": {"v1": {"id": "v1", "name": "Tor", "pressed": True, "on": False}}}
ok, txt = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["friedhelm"]}), ctx); assert ok is True and "Friedhelm" in txt, txt
ok, txt = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["anna"]}), ctx); assert ok is False, txt
ok, txt = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on"}), ctx); assert ok is True      # ohne Filter wie bisher
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "off", "by": ["anna"]}), ctx); assert ok is False
# Anna bedient danach -> Friedhelm-Bedingung fällt
with webapp.app.test_request_context("/"):
    g.user = "anna"; g.user_display = "Anna"
    devicelog.log("aktor", "device:d1", "Toröffner", "eingeschaltet", True)
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["friedhelm"]}), ctx); assert ok is False
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["anna"]}), ctx); assert ok is True
# Regel/System-Bedienung hat kein Konto -> Filter greift nicht
devicelog.log("aktor", "device:d1", "Toröffner", "eingeschaltet", True, by="Regel „X“")
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "d1", "is": "on", "by": ["anna"]}), ctx); assert ok is False
# virtueller Schalter
with webapp.app.test_request_context("/"):
    g.user = "friedhelm"; g.user_display = "Friedhelm"
    devicelog.log("aktor", "virtual:v1", "Tor", "gedrückt", True)
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "virtual", "id": "v1", "is": "pressed", "by": ["friedhelm"]}), ctx); assert ok is True
# 4) [WER]
rule = {"when": {"mode": "all", "conds": [{"type": "device", "device_id": "d1", "is": "on"}, {"type": "group", "mode": "all", "conds": [{"type": "virtual", "id": "v1", "is": "pressed"}]}]}}
assert webapp._fill_who("Tor von [WER] betätigt", rule) == "Tor von Friedhelm betätigt", webapp._fill_who("Tor von [WER] betätigt", rule)
assert webapp._fill_who("x [WER]", {"when": {"conds": []}}) == "x unbekannt" and webapp._fill_who("x [WER]", None) == "x unbekannt"
# 5) Pre-Merker (Regel schneller als Logbuch)
devicelog._pre["device:d9"] = ("Konto „Anna“", "anna", time.time())
w = devicelog.who_last("device:d9"); assert w["user"] == "anna"
# 6) Endpunkt + Rechte
r = A.get("/api/rules/accounts"); names = {x["user"] for x in r.get_json()}; assert r.status_code == 200 and {"admin", "friedhelm", "anna"} <= names, r.get_json()
L = webapp.app.test_client(); L.post("/login", data={"username": "Anna", "password": "annapass123"}); assert L.get("/api/rules/accounts").status_code == 403
F = webapp.app.test_client(); F.post("/login", data={"username": "Friedhelm", "password": "friedpass12"}); assert F.get("/api/rules/accounts").status_code == 200

# 7) Regel-Kette: Konto drueckt Knopf -> Regel A schaltet Taster -> Regel B (Telegram) fragt "wer?"
ruleA = {"id": "rA", "name": "Toröffner-Knopf", "when": {"mode": "all", "conds": [{"type": "virtual", "id": "vk", "is": "pressed"}]}}
ruleB = {"id": "rB", "name": "Telegram-Toröffner", "when": {"mode": "all", "conds": [{"type": "device", "device_id": "dT", "is": "on"}]}}
rules.list_rules = lambda: [ruleA, ruleB]
with webapp.app.test_request_context("/"):
    g.user = "lukas"; g.user_display = "Lukas"
    devicelog.log("aktor", "virtual:vk", "Toröffner", "gedrückt", True)
devicelog.log("aktor", "device:dT", "Taster", "eingeschaltet", True, by="Regel „Toröffner-Knopf“")
w = rules.resolve_who("device:dT"); assert w and w["user"] == "lukas", w
assert webapp._fill_who("Das Tor wurde von [WER] bedient.", ruleB) == "Das Tor wurde von Lukas bedient."
ctx2 = {"now": datetime.now(), "devices": {"dT": {"id": "dT", "name": "Taster", "online": True, "on": True, "power": None}}, "virtual": {}}
ok, txt = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "dT", "is": "on", "by": ["lukas"]}), ctx2); assert ok is True and "Lukas" in txt, txt
ok, _ = rules.eval_condition(rules.normalize_condition({"type": "device", "device_id": "dT", "is": "on", "by": ["anna"]}), ctx2); assert ok is False
# Schleife (Regel A haengt an Regel B und umgekehrt) bleibt endlich
ruleA2 = {"id": "rA", "name": "A", "when": {"conds": [{"type": "device", "device_id": "dB", "is": "on"}]}}
ruleB2 = {"id": "rB", "name": "B", "when": {"conds": [{"type": "device", "device_id": "dA", "is": "on"}]}}
rules.list_rules = lambda: [ruleA2, ruleB2]
devicelog.log("aktor", "device:dA", "A", "an", True, by="Regel „A“"); devicelog.log("aktor", "device:dB", "B", "an", True, by="Regel „B“")
assert rules.resolve_who("device:dA")["by"].startswith("Regel"), "Schleife"
# Ablauf-Schritt laeuft "im Namen" der Regel (nicht mehr System) und ersetzt [WER]
rules.list_rules = lambda: [ruleA, ruleB]
cls = next(c for c in vars(webapp).values() if isinstance(c, type) and hasattr(c, "_apply_flow"))
eng = cls.__new__(cls); seen = {}
def fake_msg(text, cfg, to=None):
    seen["text"], seen["by"] = text, devicelog.current_actor(); return True
webapp.notify.message = fake_msg
eng._apply_flow({"rule": "Telegram-Toröffner", "rule_id": "rB", "step": {"type": "notify", "text": "Tor von [WER]"}, "after_s": 0, "branch": "then"}, False, {})
assert seen["text"] == "Tor von Lukas" and seen["by"] == "Regel „Telegram-Toröffner“", seen
print("WER OK")
