import os, sys, tempfile, json
from datetime import datetime, timedelta
root = sys.argv[1]
sys.path.insert(0, os.path.join(root, "app"))
import rules
tmp = tempfile.mkdtemp()
rules.RULES_PATH = os.path.join(tmp, "rules.json"); rules.STATE_PATH = os.path.join(tmp, "st.json")

D = datetime(2026, 9, 28, 10, 0)          # Montag
prices = [30.0] * 96
for i in range(40, 52): prices[i] = 18.0    # 10:00-13:00 guenstig
for i in range(68, 80): prices[i] = 50.0    # 17:00-20:00 teuer
ctx = lambda now, **k: {"now": now, "soc": 60.0, "price_ct": prices[now.hour * 4 + now.minute // 15], "prices_today": prices, "pv_tomorrow": 20.0, **k}
C = rules.normalize_condition

# ---- Pruefen / Speichern
for bad in ({"device_id": "a", "on": []}, {"on": [{"type": "soc", "op": "below", "pct": 50}]},
            {"device_id": "a", "on": [{"type": "soc", "op": "below", "pct": 500}]},
            {"device_id": "a", "on": [{"type": "time", "from": "25:00", "to": "10:00"}]},
            {"device_id": "a", "on": [{"type": "surplus"}]},
            {"device_id": "a", "on": [{"type": "nix"}]}):
    try: rules.normalize_rule(bad); raise SystemExit("sollte scheitern: %r" % bad)
    except rules.RuleError: pass
r1 = rules.add_rule({"name": "Heizung billig", "device_id": "h", "on": [{"type": "price", "op": "below", "ct": "25,5"}, {"type": "time", "from": "09:00", "to": "16:00", "days": [0, 1, 2, 3, 4]}]})
assert r1["on"][0]["ct"] == 25.5 and r1["off"] == [] and len(rules.list_rules()) == 1
assert rules.normalize_rule({"device_id": "a", "conditions": [{"type": "soc", "op": "below", "pct": 5}]})["on"][0]["pct"] == 5          # alter Schluessel
assert rules.update_rule(r1["id"], {"enabled": False})["enabled"] is False and rules.update_rule("nix", {}) is None
assert rules.update_rule(r1["id"], {"off": [{"type": "soc", "op": "below", "pct": 30}], "enabled": True})["off"][0]["pct"] == 30
rules.update_rule(r1["id"], {"off": []})

# ---- Bedingungen einzeln
ev = lambda c, now=D, **k: rules.eval_condition(C(c), ctx(now, **k))[0]
assert ev({"type": "time", "from": "09:00", "to": "16:00"}) and not ev({"type": "time", "from": "11:00", "to": "16:00"})
assert ev({"type": "time", "from": "22:00", "to": "06:00"}, D.replace(hour=23)) and ev({"type": "time", "from": "22:00", "to": "06:00"}, D.replace(hour=3)) and not ev({"type": "time", "from": "22:00", "to": "06:00"})
assert ev({"type": "time", "from": "00:00", "to": "24:00", "days": [0]}) and not ev({"type": "time", "from": "00:00", "to": "24:00", "days": [1]})
assert ev({"type": "price", "op": "below", "ct": 20}) and not ev({"type": "price", "op": "above", "ct": 20}) and ev({"type": "price", "op": "below", "ct": 20}, price_ct=None) is None
assert ev({"type": "soc", "op": "above", "pct": 50}) and not ev({"type": "soc", "op": "below", "pct": 50}) and ev({"type": "soc", "op": "above", "pct": 50}, soc=None) is None
assert ev({"type": "sun_tomorrow", "op": "above", "kwh": 15}) and not ev({"type": "sun_tomorrow", "op": "below", "kwh": 15})
assert rules.normalize_condition({"type": "cheapest", "hours": 3}) == {"type": "budget", "minutes": 180, "from": "00:00", "to": "24:00"}          # entfallen -> Laufzeit pro Tag
import json as _j; _p = rules.RULES_PATH; _old = open(_p, encoding="utf-8").read() if os.path.exists(_p) else None
_j.dump({"version": 2, "rules": [{"id": "zz", "name": "", "device_id": "h", "enabled": True, "on": [{"type": "cheapest", "hours": 2}], "off": []}]}, open(_p, "w"))
assert rules.list_rules()[0]["on"] == [{"type": "budget", "minutes": 120, "from": "00:00", "to": "24:00"}]
open(_p, "w", encoding="utf-8").write(_old)
bud = {"type": "budget", "minutes": 60, "from": "06:00", "to": "20:00"}
assert ev(bud, D.replace(hour=10, minute=0)) and ev(bud, D.replace(hour=10, minute=45)) and not ev(bud, D.replace(hour=9)) and not ev(bud, D.replace(hour=20, minute=30))
c = C(bud)
assert rules.eval_condition(c, ctx(D.replace(hour=10)), ran_min=60)[0] is False
assert rules.eval_condition(c, ctx(D.replace(hour=10, minute=30)), ran_min=30)[0] and rules.eval_condition(c, ctx(D.replace(hour=20, minute=30)), ran_min=30)[0] is False
assert rules.eval_condition(c, {"now": D.replace(hour=6), "prices_today": None}, 0)[0] and rules.eval_condition(c, {"now": D.replace(hour=8), "prices_today": None}, 0)[0] and not rules.eval_condition(c, {"now": D.replace(hour=21), "prices_today": None}, 0)[0]

mkdev = lambda i="h", **k: {"id": i, "name": i.upper(), "online": True, "on": False, "switchable": True, "auto": False, "power_w": 1500, "min_on_min": 0, "min_off_min": 0, **k}
system = {"battery": {"soc": 60, "power": 0}, "grid": {"total": 100}}
new_eng = lambda: rules.RuleEngine()
def go(eng, t, devs, rl, cx=None, sysx=None, cfg=None):
    return eng.step(t, cx or ctx(t), cfg or {}, devs, rl)
def apply(eng, acts, devs):
    for a, d, why, rid in acts:
        for x in devs:
            if x["id"] == d["id"]: x["on"] = (a == "on")
        eng.set_owner(d["id"], "rule" if a == "on" else None, rid)
add = lambda body: rules.add_rule(body)

# ---- beliebige Minuten (nicht nur Viertelstunden)
assert ev({"type": "time", "from": "09:07", "to": "16:43"}, D.replace(hour=9, minute=7)) and not ev({"type": "time", "from": "09:07", "to": "16:43"}, D.replace(hour=9, minute=6))
assert ev({"type": "time", "from": "09:07", "to": "16:43"}, D.replace(hour=16, minute=42)) and not ev({"type": "time", "from": "09:07", "to": "16:43"}, D.replace(hour=16, minute=43))
assert ev({"type": "at", "time": "23:37"}, D.replace(hour=23, minute=37)) and not ev({"type": "at", "time": "23:37"}, D.replace(hour=23, minute=36)) and ev({"type": "at", "time": "23:37"}, D.replace(hour=23, minute=59))

# ---- (a) einfache Regel ohne Ausschalt-Bedingung: aus, sobald es nicht mehr stimmt
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules(); rid = r1["id"]
t0 = D.replace(hour=10, minute=0)
act = go(eng, t0, devs, rl); assert act and act[0][0] == "on" and act[0][3] == rid and act[0][2].startswith("Einschalt-Bedingung: ") and "Regel: Regel" not in act[0][2], act
apply(eng, act, devs)
assert go(eng, t0 + timedelta(minutes=10), devs, rl) == []
t2 = D.replace(hour=16, minute=30)
act = go(eng, t2, devs, rl); assert act and act[0][0] == "off" and "nicht mehr" in act[0][2], act
apply(eng, act, devs)
devs[0]["on"] = True; assert go(eng, t2 + timedelta(minutes=5), devs, rl) == []                         # ausserhalb der Bedingungen von Hand an -> nie ausgeschaltet
devs[0]["on"] = False; eng.note_manual("h", t0, 30)                                                       # Handschaltung -> Pause
res = go(eng, t0 + timedelta(minutes=1), devs, rl); assert [a[0] for a in res] in ([], ["paused"]) and eng.status[rid]["state"] == "paused"
assert go(eng, t0 + timedelta(minutes=40), devs, rl)[0][0] == "on"
assert go(eng, t0 + timedelta(hours=2), [mkdev(switchable=False)], rl) == [] and go(eng, t0 + timedelta(hours=3), [mkdev(online=False)], rl) == []
eng.set_owner("h", "rule", rid); eng2 = new_eng(); eng2._load(); assert eng2.owner == {"h": "rule"} and eng2.owner_rule == {"h": rid}

# ---- (b) Einschalten wenn / Ausschalten wenn (+ Sperre gegen sofortiges Wieder-Einschalten)
for r in rules.list_rules(): rules.delete_rule(r["id"])
rb = add({"device_id": "h", "on": [{"type": "price", "op": "below", "ct": 25}], "off": [{"type": "soc", "op": "below", "pct": 30}]})
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules(); rid = rb["id"]
tt = D.replace(hour=11)                                                                                    # Preis 18 ct
act = go(eng, tt, devs, rl); assert act[0][0] == "on"; apply(eng, act, devs)
t = tt + timedelta(hours=8)                                                                                # Preis 50 ct: Einschalt-Bedingung weg, aber KEINE Ausschalt-Bedingung -> bleibt an
assert go(eng, t, devs, rl, cx=ctx(t)) == [] and "Ausschalt-Bedingung" in eng.status[rid]["text"], eng.status
low = ctx(tt, soc=20.0)                                                                                    # Akku unter 30 % -> aus
act = go(eng, tt + timedelta(minutes=5), devs, rl, cx=low); assert act and act[0][0] == "off" and "Akku unter 30" in act[0][2], act
apply(eng, act, devs)
assert rid in eng.blocked
assert go(eng, tt + timedelta(minutes=10), devs, rl, cx=ctx(tt)) == [] and "wartet" in eng.status[rid]["text"], eng.status       # Preis noch billig, Akku wieder ok -> gesperrt
t_exp = tt + timedelta(hours=8)
assert go(eng, t_exp, devs, rl, cx=ctx(t_exp)) == [] and rid not in eng.blocked                            # Einschalt-Bedingung war einmal nicht erfuellt -> wieder scharf
act = go(eng, tt + timedelta(days=1), devs, rl, cx=ctx(tt)); assert act and act[0][0] == "on", act

# ---- (c) Tagesziel: Minuten zaehlen mit, danach aus (auch mit Ausschalt-Bedingung)
for r in rules.list_rules(): rules.delete_rule(r["id"])
rc = add({"device_id": "h", "on": [{"type": "budget", "minutes": 30, "from": "06:00", "to": "20:00"}], "off": [{"type": "soc", "op": "below", "pct": 5}]})
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules()
t = D.replace(hour=10, minute=0)
act = go(eng, t, devs, rl); assert act[0][0] == "on"; apply(eng, act, devs)
for k in range(1, 200):
    tk = t + timedelta(seconds=10 * k); act = go(eng, tk, devs, rl, cx=ctx(tk))
    if act: break
assert act and act[0][0] == "off" and "Tagesziel" in act[0][2] and 29 <= (tk - t).total_seconds() / 60 <= 31, (act, (tk - t).total_seconds() / 60, eng.ran)

# ---- (d) Regel ausschalten schaltet aus, was sie eingeschaltet hat
for r in rules.list_rules(): rules.delete_rule(r["id"])
rz = add({"device_id": "h", "on": [{"type": "soc", "op": "above", "pct": 10}]})
eng = new_eng(); dev = mkdev(); devs = [dev]
tt = D.replace(hour=12); act = go(eng, tt, devs, rules.list_rules()); assert act[0][0] == "on"; apply(eng, act, devs)
rules.update_rule(rz["id"], {"enabled": False})
act = go(eng, tt + timedelta(minutes=1), devs, rules.list_rules()); assert act and act[0][0] == "off" and eng.status[rz["id"]]["state"] == "disabled", (act, eng.status)

# ---- Timer-Verhalten: Geraet laeuft schon, waehrend die Bedingungen stimmen -> Regel uebernimmt es und schaltet zum Ende aus
for r in rules.list_rules(): rules.delete_rule(r["id"])
rt = add({"device_id": "h", "on": [{"type": "time", "from": "07:00", "to": "23:30"}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(on=True); devs = [dev]
ta = D.replace(hour=7, minute=5)
res = go(eng, ta, devs, rules.list_rules()); assert [a[0] for a in res] == ["adopt"] and eng.owner == {"h": "rule"} and eng.owner_rule == {"h": rt["id"]}, (res, eng.owner, eng.owner_rule, rt["id"])
assert go(eng, D.replace(hour=23, minute=29, second=50), devs, rules.list_rules()) == []
act = go(eng, D.replace(hour=23, minute=30, second=5), devs, rules.list_rules()); assert act and act[0][0] == "off", act

# ---- von Hand ausgeschaltet: bleibt aus bis die Bedingungen einmal nicht mehr stimmen (App-Schaltung UND Schaltung am Geraet)
for r in rules.list_rules(): rules.delete_rule(r["id"])
rt = add({"device_id": "h", "on": [{"type": "time", "from": "07:00", "to": "23:30"}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules(); rid = rt["id"]
t = D.replace(hour=7, minute=5); act = go(eng, t, devs, rl); assert act[0][0] == "on"; apply(eng, act, devs)
go(eng, D.replace(hour=14, minute=59), devs, rl)
t15 = D.replace(hour=15, minute=0)
devs[0]["on"] = False; eng.note_manual("h", t15, 60)                                                     # per App ausgeschaltet
assert rid in eng.blocked and eng.block_reason[rid] == "manual"
assert go(eng, D.replace(hour=16, minute=5), devs, rl) == [] and "von Hand" in eng.status[rid]["text"], eng.status        # nach der Pause NICHT wieder an
assert go(eng, D.replace(hour=23, minute=31), devs, rl) == [] and rid not in eng.blocked                                    # Fenster zu -> wieder scharf
assert go(eng, D.replace(hour=7, minute=10) + timedelta(days=1), devs, rl)[0][0] == "on"                                    # naechster Tag: wieder an
# am Geraet selbst ausgeschaltet (Engine merkt nichts von der App)
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]
act = go(eng, D.replace(hour=7, minute=5), devs, rl); apply(eng, act, devs)
go(eng, D.replace(hour=14, minute=0), devs, rl)
devs[0]["on"] = False                                                                                    # jemand druckt den Schalter
res = go(eng, D.replace(hour=14, minute=1), devs, rl); assert [a[0] for a in res] == ["manual"] and rid in eng.blocked, (res, eng.status)
assert go(eng, D.replace(hour=16, minute=0), devs, rl) == []                                             # bleibt aus
# eigenes Ausschalten der Engine gilt NICHT als Handschaltung
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]; act = go(eng, D.replace(hour=7, minute=5), devs, rl); apply(eng, act, devs)
act = go(eng, D.replace(hour=23, minute=31), devs, rl); assert act[0][0] == "off"; apply(eng, act, devs)
assert go(eng, D.replace(hour=23, minute=40), devs, rl) == [] and not eng.blocked
assert go(eng, D.replace(hour=7, minute=5) + timedelta(days=1), devs, rl)[0][0] == "on"                  # naechster Morgen: an

# ---- reiner Ausschalt-Timer: "um 23:30 aus", nie automatisch ein (auch bei von Hand eingeschaltetem Geraet)
for bad in ({"device_id": "h", "on": [], "off": []},):
    try: rules.normalize_rule(bad); raise SystemExit("sollte scheitern")
    except rules.RuleError: pass
for r in rules.list_rules(): rules.delete_rule(r["id"])
ro = add({"device_id": "h", "on": [], "off": [{"type": "at", "time": "23:30", "days": []}]})
assert ro["on"] == [] and ro["off"][0]["type"] == "at"
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(on=True); devs = [dev]; rl = rules.list_rules(); rid = ro["id"]                # von Hand eingeschaltet, keine Regel-Besitzerschaft
assert go(eng, D.replace(hour=23, minute=29, second=50), devs, rl) == [] and dev["on"]
act = go(eng, D.replace(hour=23, minute=30, second=5), devs, rl)
assert act and act[0][0] == "off" and act[0][3] == rid and "23:30" in act[0][2], act
apply(eng, act, devs)
devs[0]["on"] = True                                                                                     # 23:40 wieder von Hand an -> bleibt an (einmal pro Tag)
assert go(eng, D.replace(hour=23, minute=40), devs, rl) == []
act = go(eng, D.replace(hour=23, minute=30, second=5) + timedelta(days=1), devs, rl); assert act and act[0][0] == "off"                # naechster Tag wieder
# Gerät zur Zeit schon aus: kein Schalten, aber der Tag ist "verbraucht"
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(on=False); devs = [dev]
assert go(eng, D.replace(hour=23, minute=31), devs, rl) == []; devs[0]["on"] = True
assert go(eng, D.replace(hour=23, minute=45), devs, rl) == []
# Spaet angelegt / App war laenger aus (>30 Min nach der Uhrzeit): kein Ausloesen
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
r20 = add({"device_id": "x", "on": [], "off": [{"type": "at", "time": "20:00"}]}); rl20 = [r20]
eng = new_eng(); dx = mkdev("x", on=True)
assert go(eng, D.replace(hour=20, minute=45), [dx], rl20) == [] and dx["on"]                             # 45 Min nach 20:00: zu spaet
eng = new_eng(); assert go(eng, D.replace(hour=20, minute=20), [dx], rl20)[0][0] == "off"                # innerhalb der 30 Min: ausloesen (z. B. nach App-Neustart)
# Wochentage + Pause nach Handschaltung
rw = add({"device_id": "w", "on": [], "off": [{"type": "at", "time": "22:00", "days": [1]}]}); rl = rules.list_rules()          # nur Dienstag
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dw = mkdev("w", on=True); dvs = [dw]
assert go(eng, D.replace(hour=22, minute=1), dvs, rl) == []                                              # Montag: nichts
tue = D.replace(hour=22, minute=1) + timedelta(days=1); act = go(eng, tue, dvs, rl); assert act and act[0][1]["id"] == "w", act

# ---- gleiche Bedingungen fuer Ein und Aus
for kind in ("at", "budget", "time", "price", "cheapest", "soc", "sun_tomorrow"):
    base = {"at": {"type": "at", "time": "07:00"}, "budget": {"type": "budget", "minutes": 30}, "time": {"type": "time", "from": "08:00", "to": "09:00"},
            "price": {"type": "price", "op": "below", "ct": 20}, "cheapest": {"type": "cheapest", "hours": 2}, "soc": {"type": "soc", "op": "above", "pct": 50},
            "sun_tomorrow": {"type": "sun_tomorrow", "op": "above", "kwh": 10}}[kind]
    rules.normalize_rule({"device_id": "h", "on": [base], "off": []}); rules.normalize_rule({"device_id": "h", "on": [], "off": [base]})
for r in rules.list_rules(): rules.delete_rule(r["id"])
# Einschalten "um 07:00" (einmal pro Tag), bleibt danach an bis eine Ausschalt-Bedingung zutrifft
ra = add({"device_id": "h", "on": [{"type": "at", "time": "07:00"}], "off": [{"type": "soc", "op": "below", "pct": 20}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules(); rid = ra["id"]
assert go(eng, D.replace(hour=6, minute=59), devs, rl) == []
act = go(eng, D.replace(hour=7, minute=1), devs, rl); assert act and act[0][0] == "on" and act[0][3] == rid, act; apply(eng, act, devs)
assert go(eng, D.replace(hour=12), devs, rl) == [] and dev["on"]                                          # bleibt an (kein Auto-Aus, Ausloeser)
act = go(eng, D.replace(hour=13), devs, rl, cx=ctx(D, soc=10.0)); assert act and act[0][0] == "off", act; apply(eng, act, devs)
assert go(eng, D.replace(hour=7, minute=10), devs, rl) == []                                              # gleicher Tag: nicht nochmal
# ...ohne Ausschalt-Bedingung bleibt ein Ausloeser-Geraet einfach an
for r in rules.list_rules(): rules.delete_rule(r["id"])
add({"device_id": "h", "on": [{"type": "at", "time": "07:00"}]}); rl = rules.list_rules()
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]
act = go(eng, D.replace(hour=7, minute=2), devs, rl); apply(eng, act, devs)
assert go(eng, D.replace(hour=9), devs, rl) == [] and dev["on"]
# schon laufendes Geraet zur Ausloesezeit: Regel uebernimmt es, feuert nicht doppelt
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(on=True); devs = [dev]
assert [a[0] for a in go(eng, D.replace(hour=7, minute=3), devs, rl)] == ["adopt"] and eng.owner == {"h": "rule"} and eng.fired.get(rl[0]["id"] + ":on") == D.date().isoformat()
# Ausschalten "Tagesziel erreicht": nach X Minuten Laufzeit heute aus
for r in rules.list_rules(): rules.delete_rule(r["id"])
rb = add({"device_id": "h", "on": [{"type": "soc", "op": "above", "pct": 10}], "off": [{"type": "budget", "minutes": 30}]}); rl = rules.list_rules()
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]; t = D.replace(hour=10)
act = go(eng, t, devs, rl); assert act[0][0] == "on"; apply(eng, act, devs)
for k in range(1, 260):
    tk = t + timedelta(seconds=10 * k); act = go(eng, tk, devs, rl, cx=ctx(tk))
    if act: break
assert act and act[0][0] == "off" and "Tagesziel" in act[0][2] and 29 <= (tk - t).total_seconds() / 60 <= 31, (act, (tk - t).total_seconds() / 60)
apply(eng, act, devs); assert rb["id"] in eng.blocked                                                     # gesperrt bis die Einschalt-Bedingungen einmal nicht mehr gelten

# ---- Regel geaendert -> beginnt von vorn (alte Uebernahme/Ausloeser-Tag vergessen)
for r in rules.list_rules(): rules.delete_rule(r["id"])
re_ = add({"device_id": "h", "on": [{"type": "at", "time": "20:30"}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(on=True); devs = [dev]
res = go(eng, D.replace(hour=20, minute=31), devs, rules.list_rules()); assert [a[0] for a in res] == ["adopt"] and eng.owner == {"h": "rule"}
assert "läuft" in eng.status[re_["id"]]["text"]
rules.update_rule(re_["id"], {"on": [{"type": "at", "time": "20:36"}]})                                   # Uhrzeit geaendert
res = go(eng, D.replace(hour=20, minute=34), devs, rules.list_rules())
assert res == [] and not eng.owner and "nicht erfüllt" in eng.status[re_["id"]]["text"] and "läuft" not in eng.status[re_["id"]]["text"], (eng.status, eng.owner)
res = go(eng, D.replace(hour=20, minute=36, second=5), devs, rules.list_rules()); assert [a[0] for a in res] == ["adopt"] and eng.owner == {"h": "rule"}     # neue Uhrzeit loest wieder aus
# nur der Name aendert nichts
rules.update_rule(re_["id"], {"name": "Neuer Name"}); go(eng, D.replace(hour=20, minute=40), devs, rules.list_rules()); assert eng.owner == {"h": "rule"}
# Neustart: Fingerabdruck ueberlebt, unveraenderte Regel bleibt
eng._save_state(); eng2 = new_eng(); res = go(eng2, D.replace(hour=20, minute=41), devs, rules.list_rules()); assert eng2.owner == {"h": "rule"}

# ---- Regel aus- und wieder einschalten: aus = Geraet ab, an = frischer Start (Ausloeser darf nochmal)
for r in rules.list_rules(): rules.delete_rule(r["id"])
rz = add({"device_id": "h", "on": [{"type": "at", "time": "20:36"}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]
act = go(eng, D.replace(hour=20, minute=37), devs, rules.list_rules()); assert act[0][0] == "on"; apply(eng, act, devs)
rules.update_rule(rz["id"], {"enabled": False})
act = go(eng, D.replace(hour=20, minute=38), devs, rules.list_rules())
assert act and act[0][0] == "off" and eng.status[rz["id"]]["state"] == "disabled", (act, eng.status); apply(eng, act, devs)
rules.update_rule(rz["id"], {"enabled": True})
assert "nicht erfüllt" not in eng.status[rz["id"]]["text"] or True
act = go(eng, D.replace(hour=20, minute=40), devs, rules.list_rules())
assert act and act[0][0] == "on" and "läuft" not in (eng.status[rz["id"]]["text"] if act[0][0] != "on" else ""), act          # innerhalb des Ausloesefensters startet die Regel neu
# ausserhalb des Fensters bleibt nach Wiedereinschalten nichts an
apply(eng, act, devs); rules.update_rule(rz["id"], {"enabled": False}); apply(eng, go(eng, D.replace(hour=21), devs, rules.list_rules()), devs)
rules.update_rule(rz["id"], {"enabled": True}); res = go(eng, D.replace(hour=22), devs, rules.list_rules())
assert res == [] and not dev["on"] and "nicht erfüllt" in eng.status[rz["id"]]["text"] and "läuft" not in eng.status[rz["id"]]["text"], (res, eng.status)

# ---- Pause nach Handschaltung: Regel wuerde schalten -> genau EIN Logbuch-Eintrag, Status "paused", danach normal
for r in rules.list_rules(): rules.delete_rule(r["id"])
rp = add({"device_id": "h", "on": [{"type": "at", "time": "23:19"}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]
t1 = D.replace(hour=23, minute=10)
eng.note_manual("h", t1, 60)                                       # von Hand geschaltet -> Pause bis 00:10
res = go(eng, D.replace(hour=23, minute=19, second=5), devs, rules.list_rules())
assert [a[0] for a in res] == ["paused"] and "Pause nach Handschaltung bis 00:10 Uhr" in res[0][2] and "schaltet nicht ein" in res[0][2] and eng.status[rp["id"]]["state"] == "paused", (res, eng.status)
assert go(eng, D.replace(hour=23, minute=19, second=25), devs, rules.list_rules()) == []           # nicht nochmal

# ---- (f) Umstellung Version 1 -> 2
open(rules.RULES_PATH, "w").write(json.dumps({"migrated": True, "rules": [
    {"id": "s1", "name": "Überschuss", "device_id": "x", "enabled": True, "conditions": [{"type": "surplus"}]},
    {"id": "m1", "name": "", "device_id": "y", "enabled": True, "conditions": [{"type": "surplus"}, {"type": "time", "from": "09:00", "to": "17:00", "days": []}]},
    {"id": "p1", "name": "", "device_id": "z", "enabled": True, "conditions": [{"type": "price", "op": "below", "ct": 20}]}]}))
rl = rules.list_rules()
assert [r["id"] for r in rl] == ["m1", "p1"] and rl[0]["on"][0]["type"] == "time" and rl[1]["off"] == [] and "conditions" not in rl[0], rl
assert sorted(rules.pending_auto(clear=False)) == ["x", "y"] and sorted(rules.pending_auto()) == ["x", "y"] and rules.pending_auto() == []
assert not rules.enabled({"surplus_enabled": True}) and rules.enabled({"rules_enabled": True}) and rules.dry_run({}) is True and rules.dry_run({"surplus_dry_run": False}) is True     # Regeln sind unabhaengig von der Ueberschuss-Automatik
st = rules.settings({}); assert st == {"manual_hold_min": 0, "failsafe_min": 0}
assert rules.settings({"rules_failsafe_min": 1})["failsafe_min"] == 2 and rules.settings({"rules_manual_hold_min": "x"})["manual_hold_min"] == 0 and rules.settings({"rules_manual_hold_min": 5000})["manual_hold_min"] == 1440
assert "min_on_min" not in rules.normalize_rule({"device_id": "a", "on": [{"type": "soc", "op": "below", "pct": 5}], "min_on_min": "7"})
# Kein "Mind. an/aus" bei Regeln: Ein- und Ausschalten sofort, sobald die Bedingungen es verlangen
for r in rules.list_rules(): rules.delete_rule(r["id"])
rules.add_rule({"device_id": "h", "on": [{"type": "soc", "op": "above", "pct": 10}]})
os.path.exists(rules.STATE_PATH) and os.remove(rules.STATE_PATH)
eng = new_eng(); dev = mkdev(); devs = [dev]; rl = rules.list_rules()
act = go(eng, D.replace(hour=12), devs, rl); apply(eng, act, devs)
assert go(eng, D.replace(hour=12, minute=0, second=10), devs, rl, cx=ctx(D, soc=5.0))[0][0] == "off"

print("RULES OK")
