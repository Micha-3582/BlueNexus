"""Telegram-Befehle im Geraete-Logbuch: wer hat ausgeloest, nicht freigegebene Chats."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import notify, notify_in, devicelog
notify_in.REQUESTS_PATH = os.path.join(tmp, "tg_req.json")
notify.recipients = lambda: [{"id": "r1", "name": "Mitarbeiter", "chat_id": "111", "system": False}]
notify_in._reply = lambda *a, **k: None
notify_in._hooks["words"] = lambda: [{"word": "Tor", "shown": "Tor", "who": [], "confirm": False}]
notify_in._hooks["wake"] = lambda: None
msg = lambda cid, text, name="X": {"chat": {"id": cid, "first_name": name}, "text": text, "date": time.time()}
token = "t"
notify_in.handle_message(token, msg(111, "Tor"))
e = devicelog.recent(5)[0]; assert e["name"] == "Telegram „Tor“" and "Mitarbeiter" in e["text"] and e["by"] == "Telegram" and e["cat"] == "aktor", e
notify_in.handle_message(token, msg(111, "unbekannt"))                                           # unbekanntes Wort eines freigegebenen Chats: steht (ab 1.26.6) im Geraete-Logbuch
u = devicelog.recent(1)[0]; assert u["ref"] == "telegram:unknown" and "unbekannt" in u["text"] and "Mitarbeiter" in u["text"] and u["ok"] is False and u["by"] == "Telegram" and u["cat"] == "aktor", u
# Rueckfrage und Abbruch
notify_in._hooks["words"] = lambda: [{"word": "Tor", "shown": "Tor", "who": [], "confirm": True}]
notify_in.handle_message(token, msg(111, "Tor")); q = devicelog.recent(1)[0]; assert q["name"] == "Telegram „Tor“" and "Rückfrage" in q["text"] and q["ok"] is True, q
notify_in.handle_message(token, msg(111, "nein")); ab = devicelog.recent(1)[0]; assert "abgebrochen" in ab["text"] and ab["ok"] is False, ab
notify_in.handle_message(token, msg(111, "Tor")); notify_in.handle_message(token, msg(111, "ja")); f = devicelog.recent(1)[0]; assert "ausgelöst von Mitarbeiter" in f["text"], f
notify_in._hooks["words"] = lambda: [{"word": "Tor", "shown": "Tor", "who": [], "confirm": False}]
notify_in.handle_message(token, msg(999, "Tor", "Fremder"))
a = devicelog.recent(5)[0]; assert a["ref"] == "telegram:alert" and a["ok"] is False and a["by"] == "Fremder Zugriff" and "999" in a["text"] and "Fremder" in a["text"], a
n = len(devicelog.recent(50)); notify_in.handle_message(token, msg(999, "Tor", "Fremder")); assert len(devicelog.recent(50)) == n        # nicht nochmal innerhalb 10 min
notify_in.handle_message(token, msg(888, "hallo", "Anderer")); assert devicelog.recent(1)[0]["text"].find("888") > 0                      # anderer Chat zaehlt eigenstaendig
assert not any(x["name"] == "Telegram „Tor“" and "Fremder" in x["text"] for x in devicelog.recent(50))                                    # ein Fremder loest NICHTS aus
print("TELEGRAM-LOGBUCH OK")
