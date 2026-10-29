"""Besucher-Adresse hinter dem Tunnel (1.28.6): Die Kopfzeilen von Cloudflare gelten, wenn die Anfrage von Loopback ODER von der eigenen Adresse des Rechners kommt
(Tunnel-Ziel mit IP statt localhost). Von einem anderen Rechner im LAN gelten sie nie (sonst liesse sich die Bremse gegen Passwort-Raten umgehen)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore

webapp.users = UserStore(os.path.join(tmp, "u.json")); webapp.users.create("admin", "adminpass1")
OWN = "192.168.50.5"
REAL_OWN_IPS = getattr(webapp, "_own_ips", None)
webapp._own_ips = lambda: frozenset({OWN, "127.0.0.1", "::1"})              # Adressen dieses (gedachten) Rechners


def ip(remote, **headers):
    with webapp.app.test_request_context("/", headers=headers, environ_base={"REMOTE_ADDR": remote}):
        return webapp.client_ip()


CF = {"CF-Connecting-IP": "203.0.113.7"}
# Tunnel auf diesem Rechner: ueber Loopback oder ueber die eigene LAN-Adresse -> echte Besucher-Adresse
assert ip("127.0.0.1", **CF) == "203.0.113.7" and ip("::1", **CF) == "203.0.113.7" and ip("::ffff:127.0.0.1", **CF) == "203.0.113.7"
assert ip(OWN, **CF) == "203.0.113.7" and ip("::ffff:" + OWN, **CF) == "203.0.113.7", "Tunnel mit IP als Ziel: Besucher-Adresse muss gelten"
assert ip(OWN, **{"X-Forwarded-For": "198.51.100.1, 9.9.9.9"}) == "9.9.9.9"
# von einem anderen Rechner im LAN (auch wenn er sich als Tunnel ausgibt): die Kopfzeile wird ignoriert
assert ip("192.168.50.77", **CF) == "192.168.50.77" and ip("192.168.50.6", **{"X-Forwarded-For": "8.8.8.8"}) == "192.168.50.6"
assert ip(OWN) == OWN, "ohne Kopfzeile gilt die Adresse selbst"


def fail_login(n, remote, header_ip=None):
    webapp._attempts.clear()
    c = webapp.app.test_client(); c.environ_base["REMOTE_ADDR"] = remote
    codes = []
    for i in range(n):
        h = {"CF-Connecting-IP": header_ip(i)} if header_ip else {}
        codes.append(c.post("/login", data={"username": "admin", "password": "falsch%d" % i}, headers=h).status_code)
    return codes
assert 429 not in fail_login(14, OWN, lambda i: "198.51.100.%d" % i), "ueber den Tunnel (LAN-Adresse als Ziel) hat jeder Besucher seine eigene Bremse"
assert 429 in fail_login(14, OWN, lambda i: "198.51.100.9"), "ein Besucher ueber den Tunnel wird gebremst"
assert 429 in fail_login(14, "192.168.50.77", lambda i: "198.51.100.%d" % i), "von einem fremden Rechner im LAN laesst sich die Bremse nicht umgehen"
webapp._attempts.clear()

# Die echte Funktion (ohne Attrappe): liefert mindestens Loopback, wirft nie, und merkt sich das Ergebnis
webapp._own_ips = REAL_OWN_IPS
real = webapp._own_ips()
assert "127.0.0.1" in real and "::1" in real and all(isinstance(x, str) and x for x in real), real
assert webapp._own_ips() is real, "wird eine Minute gemerkt"
print("CLIENTIP OK", sys.argv[1].split("/")[-1])
