import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import midea, shelly
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_m.json")); webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None
midea.LOGIN_STATE_PATH = os.path.join(tmp, "ml.json"); midea._login_fail.clear()

# 1) Anmeldefehler: Wartezeit (Passwort falsch = lang) und Ueberleben eines Neustarts.
# Fehlversuche merkt die Schranke an der Bibliothek (_install_login_gate); hier schlaegt die Anmeldung der Bibliothek selbst fehl.
from midea_beautiful.midea import DEFAULT_APP_ID, DEFAULT_APPKEY, DEFAULT_HMACKEY, DEFAULT_IOTKEY, DEFAULT_PROXIED, DEFAULT_SIGNKEY
from midea_beautiful.cloud import MideaCloud
_orig_login = (MideaCloud._login_proxied, MideaCloud._login_non_proxied)
class AuthErr(Exception): pass
def _bad_login(self): raise AuthErr("Cloud authentication error: password error (3101)")
MideaCloud._login_proxied = MideaCloud._login_non_proxied = _bad_login
if hasattr(MideaCloud, "_bnx_gated"): del MideaCloud._bnx_gated
midea._install_login_gate(None)
class FakeMb:
    calls = 0
    @classmethod
    def connect_to_cloud(cls, account, password):
        cls.calls += 1
        MideaCloud(appkey=DEFAULT_APPKEY, account=account, password=password, appid=DEFAULT_APP_ID, hmac_key=DEFAULT_HMACKEY, iot_key=DEFAULT_IOTKEY,
                   proxied=DEFAULT_PROXIED, sign_key=DEFAULT_SIGNKEY)._login_proxied()
        raise AssertionError("Anmeldung haette scheitern muessen")
midea._mb = lambda: FakeMb
try: midea._cloud_conn("a@b.de", "falsch", manual=True); raise SystemExit("sollte scheitern")
except AuthErr as e: assert "password" in str(e).lower()
t, msg, wait = midea._login_fail["a@b.de"]; assert wait == midea.LOGIN_BACKOFF_AUTH_S
try: midea._cloud_conn("a@b.de", "falsch"); raise SystemExit("Wartezeit")
except midea.MideaError as e: assert "Zugang erneuern" in str(e) and FakeMb.calls == 1
midea._login_fail.clear(); midea._login_fail.update(midea._load_login_fail())                                 # "Neustart"
assert "a@b.de" in midea._login_fail
try: midea._cloud_conn("a@b.de", "falsch"); raise SystemExit("nach Neustart weiter warten")
except midea.MideaError: assert FakeMb.calls == 1, "kein neuer Anmeldeversuch nach Neustart"
MideaCloud._login_proxied, MideaCloud._login_non_proxied = _orig_login; del MideaCloud._bnx_gated           # Bibliothek fuer die weiteren Teile unveraendert
print("1) Wartezeit ueberlebt Neustart OK")

# 2) Zugang erneuern
shelly._save([{"id": "midea-1", "kind": "midea", "cloud": True, "cloud_account": "a@b.de", "cloud_password": "falsch", "device_id": 1, "name": "Klima", "icon": "❄️", "ip": "", "gen": 0, "channel": 0, "model": "M", "users": []},
              {"id": "midea-2", "kind": "midea", "cloud": True, "cloud_account": "a@b.de", "cloud_password": "falsch", "device_id": 2, "name": "Klima2", "icon": "❄️", "ip": "", "gen": 0, "channel": 0, "model": "M", "users": []},
              {"id": "midea-3", "kind": "midea", "cloud": True, "cloud_account": "x@y.de", "cloud_password": "andere", "device_id": 3, "name": "Fremd", "icon": "❄️", "ip": "", "gen": 0, "channel": 0, "model": "M", "users": []}])
def fake_list(account, password):
    if password != "richtig": raise midea.MideaError("Anmeldung bei der Midea-Cloud fehlgeschlagen (password error)")
    return [{"device_id": 1}, {"device_id": 2}]
midea._cloud_list = fake_list
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
r = c.post("/api/midea/cloud", json={"id": "midea-1", "account": "a@b.de", "password": "nochfalsch"}); assert r.status_code == 400 and "fehlgeschlagen" in r.get_json()["error"]
assert [d["cloud_password"] for d in shelly.load_devices()][:2] == ["falsch", "falsch"]                          # nichts gespeichert, wenn die Pruefung scheitert
assert c.post("/api/midea/cloud", json={"id": "midea-1", "account": "", "password": "x"}).status_code == 400
assert c.post("/api/midea/cloud", json={"id": "midea-3", "account": "a@b.de", "password": "richtig"}).status_code == 400   # Anlage gehoert nicht zum Konto
r = c.post("/api/midea/cloud", json={"id": "midea-1", "account": "a@b.de", "password": "richtig"}); assert r.status_code == 200 and r.get_json()["devices"] == 2, r.data
d = {x["id"]: x for x in shelly.load_devices()}; assert d["midea-1"]["cloud_password"] == "richtig" == d["midea-2"]["cloud_password"] and d["midea-3"]["cloud_password"] == "andere"
assert "a@b.de" not in midea._login_fail
pub = {x["id"]: x for x in shelly.list_with_status(live=False)}; assert "cloud_password" not in pub["midea-1"] and pub["midea-1"]["cloud"] is True
k = webapp.app.test_client(); webapp.users.create("kind", "kindpass1234", {"dashboard": "write"}); k.post("/login", data={"username": "kind", "password": "kindpass1234"})
assert k.post("/api/midea/cloud", json={"id": "midea-1", "account": "a@b.de", "password": "richtig"}).status_code == 403
print("2) Zugang erneuern OK")

# 3) Sitzung ueberlebt einen Neustart (keine neue Anmeldung)
import midea_beautiful as mb_real
from midea_beautiful.midea import DEFAULT_APP_ID, DEFAULT_APPKEY, DEFAULT_HMACKEY, DEFAULT_IOTKEY, DEFAULT_PROXIED, DEFAULT_SIGNKEY
from midea_beautiful.cloud import MideaCloud
midea.SESSION_STATE_PATH = os.path.join(tmp, "ms.json"); midea._session_saved.clear()
real = MideaCloud(appkey=DEFAULT_APPKEY, account="s@t.de", password="pw1", appid=DEFAULT_APP_ID, hmac_key=DEFAULT_HMACKEY, iot_key=DEFAULT_IOTKEY, proxied=DEFAULT_PROXIED, sign_key=DEFAULT_SIGNKEY)
real._session = {"sessionId": "sid", "uid": "42", "accessToken": "tok", "randomData": "rnd", "mdata": {"accessToken": "hdr"}}; real._uid = "42"; real._header_access_token = "hdr"; real._login_id = "lid"; real._country_code = "DE"
midea._session_save("s@t.de", "pw1", real)
assert os.path.exists(midea.SESSION_STATE_PATH) and "pw1" not in open(midea.SESSION_STATE_PATH, encoding="utf-8").read()          # kein Passwort in der Datei
calls = []
from midea_beautiful.crypto import Security
orig = Security.set_access_token; Security.set_access_token = lambda self, t, r: calls.append((t, r))
orig_prop = Security.access_token; Security.access_token = property(lambda self: getattr(self, "_t", None), lambda self, v: (calls.append((v, None)), setattr(self, "_t", v)))
midea._session_saved.clear()
back = midea._session_restore(mb_real, "s@t.de", "pw1")
assert back is not None and back._uid == "42" and back._header_access_token == "hdr" and back._login_id == "lid" and back._session["accessToken"] == "tok" and calls in ([("tok", "rnd")], [("tok", None)])
assert midea._session_restore(mb_real, "s@t.de", "anderes") is None and midea._session_restore(mb_real, "x@y.de", "pw1") is None          # falsches Passwort/Konto: keine Sitzung
back.authenticate()                                                                                                         # mit Sitzung: keine Anmeldung noetig (kein Netz im Test!)
# _cloud_conn nutzt die Sitzung statt sich anzumelden
midea._clouds.clear(); FakeMb.calls = 0
midea._mb = lambda: type("M", (), {"connect_to_cloud": staticmethod(lambda **k: (_ for _ in ()).throw(SystemExit("haette sich neu angemeldet")))})
Security.set_access_token = lambda self, t, r: None
cc = midea._cloud_conn("s@t.de", "pw1"); assert cc._uid == "42"
# unbrauchbare Sitzung wird vergessen
midea._cloud_drop({"cloud_account": "s@t.de"}, Exception("session invalid")); assert "s@t.de" not in midea._sessions_load()
Security.set_access_token = orig; Security.access_token = orig_prop
print("3) Sitzung ueberlebt Neustart OK")
print("MIDEA OK")
