"""Zugangsdaten loeschen: CCU (inkl. Push abmelden), Tuya, VRM, Telegram, Tibber - Dateien weg, Rechte, nichts bleibt im Speicher."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic, tuya, vrm, notify

for mod, name in ((homematic, "hm"), (tuya, "tu"), (vrm, "vr"), (notify, "nt")):
    attr = "CRED_PATH" if mod is notify else "CREDENTIALS_PATH"
    setattr(mod, attr, os.path.join(tmp, f"forget_{name}.json"))
    if os.path.exists(getattr(mod, attr)):
        os.remove(getattr(mod, attr))

json.dump({"host": "http://192.168.50.22", "user": "Admin", "password": "geheim", "push": True}, open(homematic.CREDENTIALS_PATH, "w"))
json.dump({"region": "eu", "api_key": "K", "api_secret": "S"}, open(tuya.CREDENTIALS_PATH, "w"))
json.dump({"installation_id": "123", "token": "T"}, open(vrm.CREDENTIALS_PATH, "w"))
json.dump({"token": "1:X", "chat_id": "111", "extra": [{"id": "r1", "name": "M", "chat_id": "222", "system": False}]}, open(notify.CRED_PATH, "w"))
c0 = store.load_config(); c0["tibber_token"] = "TIBBER"; store.save_config(c0)

# CCU: angemeldeter Push wird abgemeldet (init(url, "")), bevor die Adresse vergessen wird
calls = []
class FakeProxy:
    def init(self, url, ident): calls.append((url, ident))
homematic._proxy = lambda c, ip, port: FakeProxy()
homematic._inited.update({"BidCos-RF": "http://192.168.50.40:8765"}); homematic._push_on = True
homematic._pushed[("x", "A:1", "STATE")] = (1.0, True)

from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_forget.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("nur", "nurpass1234", {"dashboard": "write"})
webapp.users.create("lese", "lesepass123", {"smarthome_einrichten": "read", "settings_meldungen": "read", "settings_vrm": "read", "settings_tarif": "read"})
cl = lambda u, p: (lambda c: (c.post("/login", data={"username": u, "password": p}, follow_redirects=True), c)[1])(webapp.app.test_client())
adm, nur, lese = cl("admin", "adminpass1"), cl("nur", "nurpass1234"), cl("lese", "lesepass123")
webapp.opslog.log = lambda *a, **k: None

paths = {"homematic": ("/api/homematic/credentials", homematic.CREDENTIALS_PATH), "tuya": ("/api/tuya/credentials", tuya.CREDENTIALS_PATH),
         "vrm": ("/api/vrm/credentials", vrm.CREDENTIALS_PATH), "telegram": ("/api/notify/credentials", notify.CRED_PATH)}

# Rechte: ohne Schreibrecht (auch Nur-Lese) darf niemand loeschen - nichts geht verloren
for who, cli in (("ohne Recht", nur), ("nur lesen", lese)):
    for name, (url, path) in paths.items():
        r = cli.delete(url); assert r.status_code in (302, 403), (who, name, r.status_code)
        assert os.path.exists(path), (who, name, "Datei darf nicht verschwinden")
    assert cli.delete("/api/tibber/token").status_code in (302, 403)
assert store.load_config().get("tibber_token") == "TIBBER"
print("1) Rechte OK")

# Loeschen als Administrator
assert adm.delete("/api/homematic/credentials").status_code == 200
assert not os.path.exists(homematic.CREDENTIALS_PATH) and homematic.load_credentials() == {} and homematic.credentials_public()["configured"] is False
assert calls == [("http://192.168.50.40:8765", "")], calls
assert homematic._push_on is False and not homematic._inited and not homematic._pushed and not homematic.push_active()
try:
    homematic._base(homematic.load_credentials()); raise SystemExit("ohne Zugang darf keine Verbindung mehr entstehen")
except homematic.HomematicError:
    pass
for name in ("tuya", "vrm", "telegram"):
    url, path = paths[name]
    assert adm.delete(url).status_code == 200 and not os.path.exists(path), name
assert tuya.load_credentials() == {} and vrm.load_credentials() == {}
assert notify.configured() is False and notify.recipients() == [] and notify.credentials_public()["has_token"] is False
assert adm.delete("/api/homematic/credentials").status_code == 200 and adm.delete("/api/tuya/credentials").status_code == 200       # nochmal loeschen schadet nicht
assert adm.delete("/api/tibber/token").status_code == 200 and "tibber_token" not in store.load_config()
print("2) Loeschen OK")
print("FORGET OK")
