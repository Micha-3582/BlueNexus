"""Zwei Bridges auf einem Server: eigene Adresse, eigene Kennung, eigene Lichter-IDs."""
import sys, os, json, socket, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import alexa
alexa.ALEXA_PATH = os.path.join(tmp, "alexa.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
def freeport(udp=False):
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM); s_.bind(("127.0.0.1", 0)); p_ = s_.getsockname()[1]; s_.close(); return p_

# --- eigene, feste Kennung je Installation
s1 = webapp._alexa_serial(); assert len(s1) == 12 and s1.startswith("001788") and cfg["alexa_serial"] == s1
assert webapp._alexa_serial() == s1                                           # bleibt gleich
assert alexa.new_serial() != alexa.new_serial()

# --- zwei Bridges nebeneinander (verschiedene Ports, wie zwei Adressen mit Port 80)
alexa.add("virtual", "v1", "Licht", "light")
st = lambda devs: {d["hid"]: (True, True) for d in devs}
b1 = alexa.Bridge(st, lambda d, on: True, http_port=freeport(), ssdp_port=freeport(True), multicast=False, bind_ip="127.0.0.1", serial="00178811aaaa")
b2 = alexa.Bridge(st, lambda d, on: True, http_port=freeport(), ssdp_port=freeport(True), multicast=False, bind_ip="127.0.0.1", serial="00178822bbbb")
b1.start(); b2.start(); assert b1.running and b2.running, (b1.error, b2.error)
def get(b, path):
    return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{b.http_port}{path}", timeout=3).read().decode())
c1, c2 = get(b1, "/api/x/config"), get(b2, "/api/x/config")
assert c1["bridgeid"] == "001788FFFE11AAAA" and c2["bridgeid"] == "001788FFFE22BBBB" and c1["bridgeid"] != c2["bridgeid"]
l1, l2 = get(b1, "/api/x/lights")["1"], get(b2, "/api/x/lights")["1"]
assert l1["uniqueid"] != l2["uniqueid"], (l1["uniqueid"], l2["uniqueid"])
d1 = urllib.request.urlopen(f"http://127.0.0.1:{b1.http_port}/description.xml", timeout=3).read().decode(); d2 = urllib.request.urlopen(f"http://127.0.0.1:{b2.http_port}/description.xml", timeout=3).read().decode()
assert "00178811aaaa" in d1 and "00178822bbbb" in d2 and "<URLBase>http://127.0.0.1:" in d1
for b in (b1, b2):
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(3)
    u.sendto(b'M-SEARCH * HTTP/1.1\r\nMAN: "ssdp:discover"\r\nST: upnp:rootdevice\r\n\r\n', ("127.0.0.1", b.ssdp_port))
    t = u.recvfrom(2048)[0].decode()
    assert f"LOCATION: http://127.0.0.1:{b.http_port}/description.xml" in t and f"hue-bridgeid: {alexa._bridge_id(b.serial)}" in t, t     # eigene Adresse + eigene Kennung
b1.stop(); b2.stop()

# --- Einstellungen in der App: Adresse pruefen und speichern
assert A.post("/api/alexa/settings", json={"bind_ip": "abc"}).status_code == 400
assert A.post("/api/alexa/settings", json={"bind_ip": "300.1.1.1"}).status_code == 400
assert A.post("/api/alexa/settings", json={"bind_ip": "192.168.50.41"}).status_code == 200 and cfg["alexa_bind_ip"] == "192.168.50.41" and webapp.alexa_bridge.bind_ip == "192.168.50.41"
assert A.get("/api/alexa").get_json()["status"]["bind_ip"] == "192.168.50.41" and A.get("/api/alexa").get_json()["status"]["bridge_id"].startswith("001788FFFE")
assert A.post("/api/alexa/settings", json={"bind_ip": ""}).status_code == 200 and webapp.alexa_bridge.bind_ip == ""
assert A.post("/api/alexa/settings", json={"port": 80}).status_code == 200                # Port bleibt, wenn nur die Adresse geaendert wird
# Adresse gehoert nicht diesem Rechner -> verstaendliche Meldung, App laeuft weiter
b3 = webapp.alexa_bridge; b3.http_port, b3.ssdp_port, b3.multicast, b3.public_port = freeport(), freeport(True), False, None
A.post("/api/alexa/settings", json={"bind_ip": "203.0.113.9"}); A.post("/api/modules", json={"alexa": True})
assert not b3.running and "203.0.113.9" in b3.error, b3.error
A.post("/api/alexa/settings", json={"bind_ip": ""}); A.post("/api/modules", json={"alexa": False})
print("ALEXA IP OK")
