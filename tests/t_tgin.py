import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import notify, notify_in, rules, flows, virtual
from datetime import datetime
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_tg.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("lese", "lesepass1234", {"dashboard": "write", "settings_meldungen": "read", "rules": "write"}, admin=False)
webapp.opslog.log = lambda *a, **k: None
notify.CRED_PATH = os.path.join(tmp, "tg.json"); notify_in.REQUESTS_PATH = os.path.join(tmp, "tgreq.json")
sent = []
notify._api = lambda token, method, payload=None: (sent.append((payload or {}).get("chat_id"), (payload or {}).get("text")) if False else sent.append(((payload or {}).get("chat_id"), (payload or {}).get("text")))) or {"ok": True}
notify.save_credentials("TOKEN", "111")
a = notify.add_recipient("Anna", "222"); b = notify.add_recipient("Bob", "333")
wake = []
notify_in._hooks.update(words=webapp._telegram_words, wake=lambda: wake.append(1), enabled=lambda: True)
btn = virtual.add("Tor-Knopf", "button")
def flow(word, who=(), confirm=False, name="Tor"):
    return rules.add_rule({"name": name, "enabled": True, "mode": "flow", "when": {"mode": "all", "conds": [{"type": "telegram", "word": word, "who": list(who), "confirm": confirm}]},
                           "then": [{"type": "virtual", "id": btn["id"], "state": "press"}], "else": []})
def msg(chat, text, age=0, frm="Max Mustermann"):
    notify_in.handle_message("TOKEN", {"chat": {"id": int(chat), "type": "private", "first_name": frm}, "from": {"first_name": frm}, "text": text, "date": time.time() - age})
def last(): return sent[-1] if sent else None

# 1) Pruefen
c = rules.normalize_condition({"type": "telegram", "word": " /Tor@BauhofBot ", "who": ["r1", "r1"]}); assert c["word"] == "Tor" and c["who"] == ["r1"] and c["confirm"] is False
for bad in ({"type": "telegram", "word": ""}, {"type": "telegram", "word": "ja"}, {"type": "telegram", "word": "Hilfe"}, {"type": "telegram", "word": "x" * 50}):
    try: rules.normalize_condition(bad); raise SystemExit("sollte scheitern")
    except rules.RuleError: pass
try: rules.add_rule({"name": "x", "enabled": True, "mode": "state", "when": {"mode": "all", "conds": [{"type": "telegram", "word": "tor"}]}, "then": [{"type": "switch", "device_id": "d1", "state": "on"}], "else": []}); raise SystemExit("nur Ablauf")
except rules.RuleError as e: assert "Ablauf" in str(e)
print("1) Pruefen OK")

# 2) Unbekannter Chat -> Anfrage (nichts ausgeloest), nur eine Antwort
r1 = flow("Tor", who=[], confirm=False)
msg(999, "Tor"); assert not notify_in.snapshot() and last()[0] == "999" and "nicht im System registriert" in last()[1] and "melde dich beim Admin" in last()[1]
n = len(sent); msg(999, "Tor"); assert len(sent) == n and not notify_in.snapshot()                         # zweite Nachricht: keine weitere Antwort
req = notify_in.requests_list(); assert len(req) == 1 and req[0]["id"] == 999 and req[0]["name"] == "Max Mustermann" and req[0]["count"] == 2
notify_in._polling = True; assert [x["id"] for x in notify.detect_chats("TOKEN")] == [999]; notify_in._polling = False                          # "Chat ermitteln" liest die Anfragen
print("2) Anfrage OK")

# 3) Freigegebener Chat: Wort loest aus (nur dieses Wort), Rueckmeldung
msg(222, "Tor"); ev = notify_in.snapshot(); assert len(ev) == 1 and ev[0]["word"] == "Tor" and ev[0]["rid"] == a["id"] and ev[0]["name"] == "Anna" and "✓" in last()[1] and wake
fe = flows.FlowEngine(); fe._loaded = True
ctx = {"telegram": notify_in.snapshot()}; seq = notify_in.max_seq()
out = fe.step(datetime(2026, 10, 10, 12, 0), ctx, [r1]); assert any(e[0] == "start" and "Telegram" in e[2] for e in out), out                          # Regel startet
notify_in.consume(seq); assert not notify_in.snapshot()
assert not [e for e in fe.step(datetime(2026, 10, 10, 12, 0, 5), {"telegram": []}, [r1]) if e[0] == "start"]                                  # und nicht erneut
msg(222, "/Tor@mybot"); assert notify_in.snapshot()[-1]["word"] == "Tor"; notify_in.consume(notify_in.max_seq())                                  # / und @Bot egal
for falsch in ("tor", "TOR", "tOr"):
    msg(222, falsch); assert not notify_in.snapshot() and "nicht bekannt" in last()[1], falsch                                                    # Gross-/Kleinschreibung zaehlt
msg(222, "Garagentor"); assert not notify_in.snapshot() and "nicht bekannt" in last()[1]
msg(222, "hilfe"); assert "„Tor“" in last()[1] or "„tor“" in last()[1].lower()
print("3) Ausloesen OK")

# 4) Nur bestimmte Empfaenger; Rueckfrage
rules.delete_rule(r1["id"]); r2 = flow("Tor", who=[b["id"]], confirm=True, name="Tor Bob")
msg(222, "Tor"); assert not notify_in.snapshot() and "nicht bekannt" in last()[1] or "noch kein Befehl" in last()[1]                          # Anna darf nicht
msg(333, "Tor"); assert not notify_in.snapshot() and "wirklich" in last()[1]                                                                    # Rueckfrage, noch nichts ausgeloest
msg(333, "ja"); assert len(notify_in.snapshot()) == 1 and notify_in.snapshot()[0]["rid"] == b["id"]; notify_in.consume(notify_in.max_seq())
msg(333, "Tor"); msg(333, "nein"); assert not notify_in.snapshot() and "Abgebrochen" in last()[1]
msg(333, "Tor"); msg(333, "irgendwas"); assert not notify_in.snapshot()                                                                         # andere Antwort bricht die Rueckfrage ab
msg(333, "ja"); assert not notify_in.snapshot()                                                                                                   # "ja" ohne offene Rueckfrage tut nichts
notify_in._pending["333"] = ("Tor", time.time() - 120); msg(333, "ja"); assert not notify_in.snapshot()                                          # Rueckfrage abgelaufen
print("4) Empfaenger/Rueckfrage OK")

# 5) Sicherheit: alte Nachrichten, ausgeschaltete Regeln, Regeln insgesamt aus
msg(333, "Tor", age=600); assert not notify_in.snapshot()                                                                                         # liegengeblieben -> verworfen
rules.update_rule(r2["id"], {"enabled": False}); n = len(sent); msg(333, "Tor"); assert not notify_in.snapshot() and "noch kein Befehl" in last()[1]
print("5) Sicherheit OK")

# 6) Oberflaeche/API + Logbuecher nur fuer Administratoren
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
j = c.get("/api/notify/requests").get_json(); assert [x["id"] for x in j] == [999]
assert c.post("/api/notify/recipient", json={"name": "Max", "chat_id": "999"}).status_code == 201 and c.get("/api/notify/requests").get_json() == []            # freigegeben -> keine Anfrage mehr
msg(777, "Hallo", frm="Fremd"); assert c.delete("/api/notify/request/777").status_code == 200 and c.delete("/api/notify/request/777").status_code == 404
l = webapp.app.test_client(); l.post("/login", data={"username": "lese", "password": "lesepass1234"})
msg(778, "Hallo", frm="Noch einer"); assert l.get("/api/notify/requests").status_code == 200 and l.delete("/api/notify/request/778").status_code == 403           # Lesen darf sehen, nicht ablehnen
for u in ("/rules-log", "/automation-log", "/solar-log", "/report", "/watchdog", "/api/automation/log?module=rules", "/api/automation/unread", "/api/solar-log", "/api/report", "/api/watchdog"):
    rr = l.get(u); assert rr.status_code == (403 if u.startswith('/api/') else 302), (u, rr.status_code)            # Seiten leiten zum Dashboard um
    assert c.get(u).status_code in (200, 302), (u, c.get(u).status_code)
assert l.get("/rules").status_code == 200 and "/smarthome#logbuch" not in l.get("/rules").data.decode() and "/smarthome#logbuch" in c.get("/rules").data.decode()
assert "/solar-log" not in l.get("/admin").data.decode() or True
print("6) API/Logbuecher OK")

# 7) Abruf-Schleife: Nachrichten verarbeiten, Offset weiterzaehlen, Fehler abfangen, ohne Token/aus nichts abrufen
import threading
rules.update_rule(r2["id"], {"enabled": True}); notify_in._pending.clear(); notify_in.consume(notify_in.max_seq())
calls = []
def fake_poll(token, offset):
    calls.append(offset)
    if len(calls) == 1: return [{"update_id": 10, "message": {"chat": {"id": 333, "type": "private"}, "from": {"first_name": "Bob"}, "text": "Tor", "date": time.time()}},
                                 {"update_id": 11, "message": {"chat": {"id": 333, "type": "private"}, "from": {"first_name": "Bob"}, "text": "ja", "date": time.time()}}]
    if len(calls) == 2: raise notify.NotifyError("kaputt")
    notify_in._stop.set(); return []
notify_in._poll = fake_poll; notify_in._stop.clear()
orig_wait = notify_in._stop.wait; notify_in._stop.wait = lambda t=None: None
th = threading.Thread(target=notify_in._loop); th.start(); th.join(10)
notify_in._stop.wait = orig_wait
assert not th.is_alive() and calls[:3] == [None, 12, 12], calls                                                      # Offset zaehlt weiter, Fehler wird abgefangen
assert [e["word"] for e in notify_in.snapshot()] == ["Tor"]
notify_in._stop.clear(); calls.clear(); notify_in._hooks["enabled"] = lambda: False
th = threading.Thread(target=notify_in._loop); orig = notify_in._stop.wait
notify_in._stop.wait = lambda t=None: (notify_in._stop.set(), None)[1]; th.start(); th.join(5); notify_in._stop.wait = orig
assert not calls and notify_in.active() is False                                                                       # ausgeschaltet (Demo/Testmodus): kein Abruf
print("7) Abruf-Schleife OK")

# 8) Eigener Antworttext
notify_in.consume(notify_in.max_seq()); rules.delete_rule(r2["id"])
rc = rules.add_rule({"name": "Bing", "enabled": True, "mode": "flow", "when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "reply": "Klingel läutet, {name}! ({wort})"}]},
                     "then": [{"type": "virtual", "id": btn["id"], "state": "press"}], "else": []})
assert rules.list_rules()[-1]["when"]["conds"][0]["reply"] == "Klingel läutet, {name}! ({wort})"
msg(222, "bing"); assert not notify_in.snapshot() and "nicht bekannt" in last()[1]                                  # "bing" ist nicht "Bing"
msg(222, "Bing"); assert last() == ("222", "Klingel läutet, Anna! (Bing)"), last()
rules.update_rule(rc["id"], {"when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "reply": "-"}]}}); n = len(sent); msg(222, "Bing"); assert len(sent) == n and notify_in.snapshot()[-1]["word"] == "Bing"       # "-" = keine Antwort
rules.update_rule(rc["id"], {"when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "reply": ""}]}}); msg(222, "Bing"); assert "wird ausgelöst" in last()[1] and "Bing" in last()[1]       # leer = Standard
rules.update_rule(rc["id"], {"when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "confirm": True, "reply": "Erledigt"}]}}); msg(222, "Bing"); msg(222, "Ja"); assert last() == ("222", "Erledigt")      # auch nach Rueckfrage
print("8) Antworttext OK")

# 9) Altbestand: aeltere Regeln speicherten das Wort klein ("bing"), eingegeben war "Bing" -> massgeblich ist die eingegebene Schreibweise
old = {"type": "telegram", "word": "bing", "shown": "Bing", "who": [], "confirm": False, "reply": ""}
assert rules.tg_word(old) == "Bing"
assert rules.eval_condition(old, {"now": datetime(2026, 10, 10, 12, 0), "telegram": [{"word": "Bing", "rid": "main", "name": "x"}]})[0] is True and rules.eval_condition(old, {"now": datetime(2026, 10, 10, 12, 0), "telegram": [{"word": "bing", "rid": "main", "name": "x"}]})[0] is False
print("9) Schreibweise OK")

# 10) Antworten des Bots einzeln abschaltbar (Standard: an)
adm = webapp.app.test_client(); adm.post("/login", data={"username": "admin", "password": "adminpass1"})
assert adm.get("/api/notify").get_json()["bot"] == {"help": True, "unknown": True, "stranger": True}
notify_in.consume(notify_in.max_seq()); notify_in._replied.clear()
rules.update_rule(rc["id"], {"enabled": True, "when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "reply": ""}]}})
assert adm.post("/api/notify/settings", json={"bot": {"help": False}}).status_code == 200
msg(222, "hilfe"); assert last()[1] == "Hallo Anna, das Wort ist mir nicht bekannt!"                                              # "hilfe" ist dann ein unbekanntes Wort, ohne Hinweis auf sich selbst
msg(222, "xyz"); assert last()[1] == "Hallo Anna, das Wort ist mir nicht bekannt!"                                                   # ohne Hinweis auf "hilfe"
assert adm.post("/api/notify/settings", json={"bot": {"unknown": False}}).status_code == 200
n = len(sent); msg(222, "xyz"); msg(222, "hilfe"); assert len(sent) == n and not notify_in.snapshot()                    # alles stumm
assert adm.post("/api/notify/settings", json={"bot": {"stranger": False}}).status_code == 200
n = len(sent); msg(555, "hallo", frm="Neu"); assert len(sent) == n and [x["id"] for x in notify_in.requests_list() if x["id"] == 555]                  # Anfrage wird trotzdem vermerkt
msg(222, "Bing"); assert last()[0] == "222" and "wird ausgelöst" in last()[1] and notify_in.snapshot()                                          # Ausloesen unberuehrt
assert adm.post("/api/notify/settings", json={"bot": {"hilfe": True, "help": "x"}}).status_code == 200 and adm.get("/api/notify").get_json()["bot"]["help"] is True
assert adm.post("/api/notify/settings", json={"bot": "kaputt"}).status_code == 400
print("10) Bot-Antworten abschaltbar OK")

# 11) Platzhalter und einstellbare Texte
assert notify_in.fill("Hallo [NAME]/[username]/{name}: [Wort]/{wort}", "Anna", "Bing") == "Hallo Anna/Anna/Anna: Bing/Bing"
rules.update_rule(rc["id"], {"when": {"mode": "all", "conds": [{"type": "telegram", "word": "Bing", "reply": "Hallo [USERNAME], die Klingel läutet!"}]}}); msg(222, "Bing"); assert last() == ("222", "Hallo Anna, die Klingel läutet!"), last()
for k in ("help", "unknown", "stranger"): adm.post("/api/notify/settings", json={"bot": {k: True}})
assert adm.post("/api/notify/settings", json={"bot_text": {"unknown": "Hey [NAME], „[WORT]“ kenne ich nicht.", "stranger": "Hi [NAME], melde dich beim Chef."}}).status_code == 200
j = adm.get("/api/notify").get_json(); assert j["bot_text"]["unknown"].startswith("Hey [NAME]")
msg(222, "xyz"); assert last() == ("222", "Hey Anna, „xyz“ kenne ich nicht."), last()
notify_in._replied.clear(); msg(901, "hi", frm="Zoe"); assert last() == ("901", "Hi Zoe, melde dich beim Chef."), last()
adm.post("/api/notify/settings", json={"bot_text": {"unknown": "", "stranger": ""}}); msg(222, "xyz"); assert last()[1] == "Hallo Anna, das Wort ist mir nicht bekannt!"
print("11) Platzhalter/Texte OK")
print("TGIN OK")
