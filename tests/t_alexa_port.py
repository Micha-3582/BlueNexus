"""Alexa hinter einem Webserver (Apache) auf Port 80: interner Port, oeffentlich 80."""
import sys, os, socket, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import alexa
alexa.ALEXA_PATH = os.path.join(tmp, "alexa.json")
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("ina", "inapass123", {"dashboard": "write", "smarthome_einrichten": "read"})
def login(u, p):
    c = webapp.app.test_client(); c.post("/login", data={"username": u, "password": p}, follow_redirects=True); return c
A, I = login("admin", "adminpass1"), login("ina", "inapass123")
def freeport(udp=False):
    s_ = socket.socket(socket.AF_INET, socket.SOCK_DGRAM if udp else socket.SOCK_STREAM); s_.bind(("127.0.0.1", 0)); p_ = s_.getsockname()[1]; s_.close(); return p_

b = webapp.alexa_bridge; b.ssdp_port, b.multicast = freeport(True), False
assert A.post("/api/alexa/settings", json={"port": "abc"}).status_code == 400
assert A.post("/api/alexa/settings", json={"port": 500}).status_code == 400 and I.post("/api/alexa/settings", json={"port": 8099}).status_code == 403
free = freeport()
r = A.post("/api/alexa/settings", json={"port": free}); assert r.status_code == 200, r.get_json()
assert b.http_port == free and b.public_port == 80 and cfg["alexa_port"] == free
A.post("/api/modules", json={"alexa": True}); assert b.running, b.error
st = A.get("/api/alexa").get_json()["status"]; assert st["port"] == free and st["public_port"] == 80
req = urllib.request.Request(f"http://127.0.0.1:{free}/description.xml", headers={"Host": "192.168.50.40"})          # wie von Apache mit ProxyPreserveHost On durchgereicht
x = urllib.request.urlopen(req, timeout=3).read().decode()
assert "<URLBase>http://192.168.50.40:80/</URLBase>" in x, x
x2 = urllib.request.urlopen(f"http://127.0.0.1:{free}/description.xml", timeout=3).read().decode()                      # ohne Host-Adresse: lokale Adresse, trotzdem Port 80
assert ":80/</URLBase>" in x2
u2 = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u2.settimeout(3)
u2.sendto(b'M-SEARCH * HTTP/1.1\r\nMAN: "ssdp:discover"\r\nST: upnp:rootdevice\r\n\r\n', ("127.0.0.1", b.ssdp_port))
t2 = u2.recvfrom(2048)[0].decode(); assert ":80/description.xml" in t2, t2                                           # Echo soll Port 80 benutzen
A.post("/api/modules", json={"alexa": False}); assert not b.running
assert A.post("/api/alexa/settings", json={"port": 80}).status_code == 200 and b.public_port is None and b.http_port == 80 and not b.running
print("ALEXA PORT OK")
