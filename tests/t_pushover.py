"""Pushover: Zugang, Empfaenger, Senden (Text/Prioritaet/Ton/Bild), Regel-Schritt, Systemmeldungen, Rechte, Loeschen."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import pushover, notify, rules, autolog, camera

pushover.CRED_PATH = os.path.join(tmp, "po_test.json"); notify.CRED_PATH = os.path.join(tmp, "po_tg.json")
for p in (pushover.CRED_PATH, notify.CRED_PATH):
    if os.path.exists(p):
        os.remove(p)

SENT = []                 # (user, message, priority, sound, hat_bild, retry)
TG = []
DEV = []
BADKEY = "b" * 30


class FakeResp:
    status_code = 200
    def __init__(self, j): self._j = j
    def json(self): return self._j


def fake_post(url, data=None, files=None, json=None, timeout=0):
    if "api.pushover.net" in url and url.endswith("/users/validate.json"):
        return FakeResp({"status": 0 if data["user"] == BADKEY else 1, "errors": ["user identifier is not a valid user, group, or subscribed user key"] if data["user"] == BADKEY else []})
    if "api.pushover.net" in url:
        if data["user"] == "x" * 30:
            return FakeResp({"status": 0, "errors": ["user key invalid"]})
        DEV.append((data["user"], data.get("device")))
        SENT.append((data["user"], data["message"], data["priority"], data.get("sound"), bool(files), data.get("retry")))
        return FakeResp({"status": 1})
    TG.append(json or data)                                  # Telegram
    return FakeResp({"ok": True})


pushover.requests.post = fake_post
notify.requests.post = fake_post
TOK = "a" * 30
KEY1, KEY2 = "1" * 30, "2" * 30

# 1) Einrichtung
assert pushover.configured() is False
for bad in ("", "zu kurz", "a b" * 12):
    try:
        pushover.save_token(bad); raise SystemExit("Token %r muss abgelehnt werden" % bad)
    except pushover.PushoverError:
        pass
try:
    pushover.add_recipient("X", KEY1); raise SystemExit("ohne Token")
except pushover.PushoverError:
    pass
pushover.save_token(TOK)
m = pushover.add_recipient("Max", KEY1)
assert m["id"] == "p1" and m["system"] is True and "user_key" not in m, m          # erster Empfaenger = Systemempfaenger
r = pushover.add_recipient("Anna", KEY2)
assert r["id"] == "p2" and r["system"] is False and pushover.configured()
for bad in (("", KEY2 + "z"), ("Y", "kurz"), ("Z", KEY1), ("Falsch", BADKEY)):
    try:
        pushover.add_recipient(*bad); raise SystemExit("sollte scheitern %r" % (bad,))
    except pushover.PushoverError:
        pass
pushover.save_token("")                                                         # leer = behalten
assert pushover.has_token() and len(pushover.recipients()) == 2
print("1) Einrichtung OK")

# 2) Senden: Standard = Systemempfaenger; Auswahl; Prioritaet, Ton, Notfall-Wiederholung, Bild
SENT.clear(); pushover.send("hallo"); assert SENT == [(KEY1, "hallo", 0, None, False, None)], SENT
SENT.clear(); pushover.send("an beide", priority=1, sound="siren", to=["p1", "p2"]); assert sorted(x[0] for x in SENT) == [KEY1, KEY2] and all(x[2] == 1 and x[3] == "siren" for x in SENT)
SENT.clear(); pushover.send("notfall", priority=2, to=["p2"]); assert SENT == [(KEY2, "notfall", 2, None, False, 60)], SENT
SENT.clear(); pushover.send("bild", jpeg=b"JPG", to=["p1", "p2"]); assert len(SENT) == 2 and all(x[4] for x in SENT)
SENT.clear(); pushover.send("x" * 5000); assert len(SENT[0][1]) == 1024
SENT.clear(); pushover.send("ton egal", sound="unbekannt"); assert SENT[0][3] is None
pushover.update_recipient("p2", system=True)
SENT.clear(); pushover.send("system"); assert sorted(x[0] for x in SENT) == [KEY1, KEY2]
pushover.update_recipient("p2", system=False)
# Fehler bei einem Empfaenger stoppt die anderen nicht (Schluessel nachtraeglich ungueltig)
pushover.add_recipient("Kaputt", "x" * 30, check=False)
SENT.clear()
try:
    pushover.send("t", to=["p1", "p3"]); raise SystemExit("Fehler erwartet")
except pushover.PushoverError as e:
    assert "Kaputt" in str(e)
assert [x[0] for x in SENT] == [KEY1]
print("2) Senden OK")

# 2b) Zwei Handys im selben Konto: gleicher Schluessel, verschiedene Geraete
ina = pushover.add_recipient("Ina (S22)", KEY1, device="GalaxyS22")
mic = pushover.add_recipient("Max (S25)", KEY1, device="Hanss-S25-Ultra")
assert ina["id"] == "p4" and mic["id"] == "p5"
for bad in (("Doppelt", KEY1, "GalaxyS22"), ("Doppelt", KEY1, ""), ("X", KEY1, "mit leerzeichen"), ("X", KEY1, "a" * 26)):
    try:
        pushover.add_recipient(bad[0], bad[1], device=bad[2], check=False); raise SystemExit("sollte scheitern %r" % (bad,))
    except pushover.PushoverError:
        pass
DEV.clear(); pushover.send("nur Ina", to=["p4"]); assert DEV == [(KEY1, "GalaxyS22")], DEV
DEV.clear(); pushover.send("nur ich", to=["p5"]); assert DEV == [(KEY1, "Hanss-S25-Ultra")], DEV
DEV.clear(); pushover.send("alle Geraete", to=["p1"]); assert DEV == [(KEY1, None)], "ohne Geraet: an alle Geraete des Kontos"
DEV.clear(); pushover.send("beide", to=["p4", "p5"]); assert sorted(d for _, d in DEV) == ["GalaxyS22", "Hanss-S25-Ultra"]
assert pushover.remove_recipient("p4") and pushover.remove_recipient("p5")
print("2b) Geraete OK")

# 3) Bild nur einmal holen, an alle Gewaehlten
calls = []
SENT.clear(); assert pushover.message("Hof", None, "Titel", 1, None, ["p1", "p2"], lambda: (calls.append(1), b"JPG")[1]) is True
for _ in range(60):
    if len(SENT) >= 2: break
    time.sleep(0.05)
assert len(calls) == 1 and len(SENT) == 2 and all(x[4] for x in SENT), (calls, SENT)
# Kamera tot -> Text geht trotzdem raus (ohne Bild)
SENT.clear(); pushover.message("ohne Bild", None, None, 0, None, ["p1"], lambda: (_ for _ in ()).throw(RuntimeError("tot")))
for _ in range(60):
    if SENT: break
    time.sleep(0.05)
assert SENT and SENT[0][1] == "ohne Bild" and SENT[0][4] is False, SENT
print("3) Bild OK")

# 4) Regel-Schritt
base = {"name": "Hof", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]}, "else": []}
nrm = lambda step: rules.normalize_rule({**base, "then": [step]}, "po1")["then"][0]
assert nrm({"type": "pushover", "text": " Hallo "}) == {"type": "pushover", "text": "Hallo"}
full = nrm({"type": "pushover", "text": "Besuch", "title": "Hof", "priority": "1", "sound": "Siren", "camera": "cam1", "to": ["p1", "p2", "p1"]})
assert full == {"type": "pushover", "text": "Besuch", "title": "Hof", "priority": 1, "sound": "siren", "camera": "cam1", "to": ["p1", "p2"]}, full
for bad in ({"text": ""}, {"text": "x", "priority": 5}, {"text": "x", "priority": "abc"}, {"text": "x", "sound": "kaffee"}, {"text": "x", "to": []}):
    try:
        nrm({"type": "pushover", **bad}); raise SystemExit("sollte scheitern %r" % (bad,))
    except rules.RuleError:
        pass
log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
run = lambda step, dry=False: webapp.ctrl._apply_flow({"rule_id": "po1", "rule": "Hof", "branch": "then", "step": step, "after_s": 0}, dry, {})
SENT.clear(); run({"type": "pushover", "text": "Besuch", "priority": 1, "to": ["p2"]})
for _ in range(60):
    if SENT: break
    time.sleep(0.05)
assert SENT and SENT[0][0] == KEY2 and SENT[0][2] == 1 and "Anna" in log[-1][2], (SENT, log[-1])
run({"type": "pushover", "text": "Besuch", "to": ["p1", "p2"]}, dry=True)
assert "würde" in log[-1][2] and "Max, Anna" in log[-1][2] and log[-1][3], log[-1]
run({"type": "pushover", "text": "mit Bild", "camera": "weg"})
assert log[-1][0] == "fail" and "Kamera" in log[-1][2], log[-1]
print("4) Regel-Schritt OK")

# 5) Systemmeldungen gehen an Telegram UND Pushover; nur Pushover reicht aus
notify.save_credentials("1:X", "111")
SENT.clear(); TG.clear()
assert notify.push("startup", "🔄 Start", {"notify_events": {"startup": True}, "notify_prefix": False}) is True
for _ in range(60):
    if SENT and TG: break
    time.sleep(0.05)
assert [x[0] for x in SENT] == [KEY1] and SENT[0][1] == "🔄 Start" and len(TG) == 1, (SENT, TG)
notify.clear_credentials()                                                      # nur Pushover
SENT.clear(); TG.clear()
assert notify.any_configured() and not notify.configured()
assert notify.push("startup", "nur Pushover", {"notify_events": {"startup": True}, "notify_prefix": False}) is True
for _ in range(60):
    if SENT: break
    time.sleep(0.05)
assert len(SENT) == 1 and not TG
# Telegram-Schritt geht NICHT an Pushover
notify.save_credentials("1:X", "111"); SENT.clear()
assert notify.message("nur Telegram", {"notify_prefix": False}) is True; time.sleep(0.3); assert SENT == []
print("5) Systemmeldungen OK")

# 6) Endpunkte, Rechte, Loeschen
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_po.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("regel", "regelpass12", {"rules": "write"}); webapp.users.create("lese", "lesepass123", {"settings_meldungen": "read"})
cl = lambda u, p: (lambda c: (c.post("/login", data={"username": u, "password": p}, follow_redirects=True), c)[1])(webapp.app.test_client())
adm, reg, lese = cl("admin", "adminpass1"), cl("regel", "regelpass12"), cl("lese", "lesepass123")
webapp.opslog.log = lambda *a, **k: None
body = reg.get("/api/pushover/recipients").get_json(); assert [r["name"] for r in body] == ["Max", "Anna", "Kaputt"] and all("user_key" not in r for r in body)
assert reg.get("/api/pushover").status_code in (302, 403)
for cli in (reg, lese):
    assert cli.post("/api/pushover/credentials", json={"token": TOK}).status_code in (302, 403)
    assert cli.post("/api/pushover/recipient", json={"name": "X", "user_key": KEY1}).status_code in (302, 403)
    assert cli.delete("/api/pushover/credentials").status_code in (302, 403)
    assert cli.post("/api/pushover/test", json={}).status_code in (302, 403)
info = lese.get_json if False else lese.get("/api/pushover").get_json()
assert all("user_key" not in r for r in info["recipients"]), "Schluessel nur mit Schreibrecht"
info = adm.get("/api/pushover").get_json()
assert info["configured"] and all("…" in r["user_key"] and r["user_key"] != KEY1 for r in info["recipients"]), "auch Admin sieht nur den Anfang/das Ende"
assert info["priorities"]["2"] and "siren" in info["sounds"]
assert adm.post("/api/pushover/recipient", json={"name": "Oma", "user_key": "3" * 30}).status_code == 201
assert adm.post("/api/pushover/recipient", json={"name": "Falsch", "user_key": BADKEY}).status_code == 400
assert adm.patch("/api/pushover/recipient/p4", json={"name": "Mutti", "system": True}).status_code == 200
assert adm.patch("/api/pushover/recipient/nix", json={"name": "A"}).status_code == 404
SENT.clear(); assert adm.post("/api/pushover/test", json={"id": "p2"}).status_code == 200 and [x[0] for x in SENT] == [KEY2]
assert adm.delete("/api/pushover/recipient/p4").status_code == 200 and adm.delete("/api/pushover/recipient/p4").status_code == 404
assert webapp.app.test_client().get("/api/pushover").status_code in (302, 401, 403)
assert adm.delete("/api/pushover/credentials").status_code == 200
assert not os.path.exists(pushover.CRED_PATH) and pushover.configured() is False and pushover.recipients() == []
try:
    pushover.send("nix"); raise SystemExit("ohne Zugang darf nichts gesendet werden")
except pushover.PushoverError:
    pass
print("6) Endpunkte OK")
print("PUSHOVER OK")
