"""Telegram-Empfaenger: mehrere Chats an einem Bot, Auswahl je Regel-Schritt, ein Foto fuer alle, Rechte."""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import notify, rules, camera, autolog

notify.CRED_PATH = os.path.join(tmp, "tg_rcpt.json")
if os.path.exists(notify.CRED_PATH):
    os.remove(notify.CRED_PATH)

SENT = []            # (Methode, chat_id, Text/Caption)


class FakeResp:
    status_code = 200
    def __init__(self, j): self._j = j
    def json(self): return self._j


def fake_post(url, json=None, data=None, files=None, timeout=0):
    method = url.rsplit("/", 1)[-1]
    if method == "getUpdates":
        return FakeResp({"ok": True, "result": [
            {"message": {"chat": {"id": 111, "first_name": "Max", "type": "private"}}},
            {"message": {"chat": {"id": 222, "first_name": "Anna", "type": "private"}}}]})
    p = json or data
    if str(p.get("chat_id")) == "999":
        return FakeResp({"ok": False, "description": "Forbidden: bot was blocked by the user"})
    SENT.append((method, str(p["chat_id"]), p.get("text") or p.get("caption")))
    return FakeResp({"ok": True})


notify.requests.post = fake_post

# 1) Einrichtung: erster Empfaenger = Chat-ID oben, weitere dazu
notify.save_credentials("123:ABC", "111")
assert [r["id"] for r in notify.recipients()] == ["main"] and notify.recipients()[0]["system"] is True and notify.recipients()[0]["name"] == "Ich"
m = notify.add_recipient("Anna", "222")
assert m["id"] == "r1" and m["system"] is False and [r["name"] for r in notify.recipients()] == ["Ich", "Anna"]
for bad in (("", "333"), ("X", "abc"), ("Y", "222"), ("Z", "")):
    try:
        notify.add_recipient(*bad); raise SystemExit("sollte scheitern %r" % (bad,))
    except notify.NotifyError:
        pass
notify.save_credentials("", "111")                                       # Token leer = behalten, Empfaenger bleiben
assert len(notify.recipients()) == 2
notify.update_recipient("main", name="Max")
assert notify.recipients()[0]["name"] == "Max"
print("1) Empfaenger OK")

# 2) Senden: Standard = nur Systemempfaenger; mit Auswahl nur die Gewaehlten
SENT.clear(); notify.send("hallo"); assert SENT == [("sendMessage", "111", "hallo")], SENT
SENT.clear(); notify.send("an beide", to=["main", "r1"]); assert sorted(c for _, c, _ in SENT) == ["111", "222"]
SENT.clear(); notify.send("nur Anna", to=["r1"]); assert SENT == [("sendMessage", "222", "nur Anna")]
SENT.clear(); notify.send("unbekannt", to=["r99"]); assert SENT == [("sendMessage", "111", "unbekannt")], "unbekannter Empfaenger -> Standard"
notify.update_recipient("r1", system=True)
SENT.clear(); notify.send("system"); assert sorted(c for _, c, _ in SENT) == ["111", "222"]
notify.update_recipient("r1", system=False)
# Fehler bei einem Empfaenger stoppt die anderen nicht
notify.add_recipient("Blockiert", "999")
SENT.clear()
try:
    notify.send("test", to=["main", "r2"]); raise SystemExit("Fehler erwartet")
except notify.NotifyError as e:
    assert "Blockiert" in str(e)
assert SENT == [("sendMessage", "111", "test")]
print("2) Senden OK")

# 3) Foto: Bild nur EINMAL holen, an alle Gewaehlten
calls = []
def jpeg():
    calls.append(1); return b"JPEG"
cfgd = {"notify_prefix": False}
SENT.clear(); assert notify.photo(jpeg, "Hof", cfgd, ["main", "r1"]) is True
for _ in range(50):
    if len(SENT) >= 2: break
    time.sleep(0.05)
assert len(calls) == 1 and sorted(c for _, c, _ in SENT) == ["111", "222"] and all(m == "sendPhoto" for m, _, _ in SENT), (calls, SENT)
print("3) Foto OK")

# 4) Regel-Schritte: Auswahl wird gespeichert, leere Auswahl abgelehnt
base = {"name": "Hof", "mode": "flow", "when": {"mode": "all", "conds": [{"type": "time", "from": "00:00", "to": "24:00"}]}, "else": []}
nrm = lambda step: rules.normalize_rule({**base, "then": [step]}, "h1")["then"][0]
assert nrm({"type": "notify", "text": "Hi"}) == {"type": "notify", "text": "Hi"}
assert nrm({"type": "notify", "text": "Hi", "to": ["main", "r1", "main"]}) == {"type": "notify", "text": "Hi", "to": ["main", "r1"]}
assert nrm({"type": "photo", "id": "cam1", "text": "x", "to": ["r1"]}) == {"type": "photo", "id": "cam1", "text": "x", "to": ["r1"]}
for bad in ({"type": "notify", "text": "Hi", "to": []}, {"type": "photo", "id": "c", "to": []}):
    try:
        nrm(bad); raise SystemExit("leere Auswahl muss scheitern")
    except rules.RuleError as e:
        assert "Empfänger" in str(e)
print("4) Regeln OK")

# 5) Ausfuehrung ueber die Regel-Maschine (Nachricht + Foto), Trockenlauf nennt die Empfaenger
log = []
autolog.log = lambda module, text, dev="", action="", dry=False, rule=None, now=None: log.append((action, dev, text, dry))
SENT.clear()
run = lambda step, dry=False: webapp.ctrl._apply_flow({"rule_id": "h1", "rule": "Hof", "branch": "then", "step": step, "after_s": 0}, dry, {})
run({"type": "notify", "text": "Besuch", "to": ["r1"]})
for _ in range(50):
    if SENT: break
    time.sleep(0.05)
assert SENT and SENT[0][1] == "222" and len(SENT) == 1 and "Anna" in log[-1][2], (SENT, log[-1])
run({"type": "notify", "text": "Besuch", "to": ["main", "r1"]}, dry=True)
assert "würde" in log[-1][2] and "Max, Anna" in log[-1][2], log[-1]
print("5) Ausfuehrung OK")

# 6) Endpunkte und Rechte
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_rcpt.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("regel", "regelpass12", {"rules": "write"}); webapp.users.create("melder", "melderpass1", {"settings_meldungen": "read"})
adm = webapp.app.test_client(); adm.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
reg = webapp.app.test_client(); reg.post("/login", data={"username": "regel", "password": "regelpass12"}, follow_redirects=True)
mel = webapp.app.test_client(); mel.post("/login", data={"username": "melder", "password": "melderpass1"}, follow_redirects=True)
webapp.opslog.log = lambda *a, **k: None
lst = reg.get("/api/notify/recipients"); assert lst.status_code == 200
body = lst.get_json(); assert [r["name"] for r in body] == ["Max", "Anna", "Blockiert"] and all("chat_id" not in r for r in body), body
assert reg.get("/api/notify").status_code in (302, 403), "Regel-Konto darf die Meldungs-Einstellungen nicht lesen"
assert reg.post("/api/notify/recipient", json={"name": "X", "chat_id": "5"}).status_code in (302, 403)
assert reg.delete("/api/notify/recipient/r1").status_code in (302, 403)
info = mel.get("/api/notify").get_json(); assert all("chat_id" not in r for r in info["recipients"]), "Chat-IDs nur mit Schreibrecht"
assert mel.post("/api/notify/recipient", json={"name": "X", "chat_id": "5"}).status_code in (302, 403)
info = adm.get("/api/notify").get_json(); assert {r["chat_id"] for r in info["recipients"]} == {"111", "222", "999"}
r = adm.post("/api/notify/recipient", json={"name": "Oma", "chat_id": "444"}); assert r.status_code == 201 and r.get_json()["id"] == "r3", r.get_json()
assert adm.patch("/api/notify/recipient/r3", json={"name": "Mutti", "system": True}).status_code == 200
assert adm.patch("/api/notify/recipient/nix", json={"name": "A"}).status_code == 404
assert adm.delete("/api/notify/recipient/main").status_code == 400
assert adm.delete("/api/notify/recipient/r3").status_code == 200 and adm.delete("/api/notify/recipient/r3").status_code == 404
SENT.clear(); assert adm.post("/api/notify/test", json={"id": "r1"}).status_code == 200 and [c for _, c, _ in SENT] == ["222"]
assert adm.post("/api/notify/detect", json={}).get_json()[1]["id"] == 222
print("6) Endpunkte OK")
print("RECIPIENTS OK")
