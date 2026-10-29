"""Homematic-Push: Anmeldung (init/ping), Meldungen (event, multicall), Werte aus dem Push-Speicher, Aufwecken der Regeln, Abmelden."""
import sys, os, json, threading, time, xmlrpc.client, socket
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import homematic as hm
from xmlrpc.server import SimpleXMLRPCServer


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


# ---- Mock-CCU (XML-RPC-Seite)
calls = []
ccu = SimpleXMLRPCServer(("127.0.0.1", 0), logRequests=False, allow_none=True)
ccu.register_function(lambda url, iid="": calls.append(("init", url, iid)) or "", "init")
ccu.register_function(lambda iid: calls.append(("ping", iid)) or True, "ping")
threading.Thread(target=ccu.serve_forever, daemon=True).start()
CCU_PORT = ccu.server_address[1]

hm.RPC_PORTS["BidCos-RF"] = CCU_PORT
hm._split_host = lambda host: ("http", "127.0.0.1")
hm._local_ip = lambda ip: "127.0.0.1"
hm._known_interfaces = lambda: {"BidCos-RF"}
with open(hm.CREDENTIALS_PATH, "w") as f:
    json.dump({"host": "http://192.168.50.22", "user": "Admin", "password": "x"}, f)
PORT = free_port()

# ---- Pruefung der Eingaben
for bad in ("abc", 80, 70000):
    try:
        hm.save_push(True, bad); raise AssertionError(bad)
    except hm.HomematicError:
        pass
hm.save_push(True, PORT)
assert hm.push_status()["enabled"] and hm.push_status()["port"] == PORT
assert json.load(open(hm.CREDENTIALS_PATH))["password"] == "x"        # Zugang bleibt erhalten
hm.save_credentials("192.168.50.22", "Admin", "")
assert json.load(open(hm.CREDENTIALS_PATH))["push"] is True            # und Push-Einstellung bleibt beim Speichern des Zugangs
print("1) Einstellungen speichern OK")

# ---- Anmeldung
hm._push_cycle()
assert calls and calls[0] == ("init", f"http://127.0.0.1:{PORT}", "victron-BidCos-RF"), calls
assert hm.push_active(), hm.push_status()
hm._push_cycle()                                                        # zweiter Durchlauf: nur ping
assert calls[-1] == ("ping", "victron-BidCos-RF"), calls
print("2) init + ping, Push aktiv OK")

# ---- Meldungen der CCU
woke = []
hm.add_listener(lambda: woke.append(1))
hm.set_watch(["NEQ0000001:1", "NEQ0000007"])
cli = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{PORT}", allow_none=True)
assert cli.system.multicall([
    {"methodName": "event", "params": ["victron-BidCos-RF", "NEQ0000007:1", "STATE", True]},
    {"methodName": "event", "params": ["victron-BidCos-RF", "NEQ0000099:1", "STATE", True]},      # nicht beobachtet
    {"methodName": "event", "params": ["victron-BidCos-RF", "NEQ0000001:6", "POWER", 12.5]},      # beobachtet, aber 'laut' -> weckt nicht
]) is not None
time.sleep(0.1)
assert len(woke) == 1, woke
assert hm._pushed[("BidCos-RF", "NEQ0000007:1", "STATE")][1] is True
assert cli.listDevices("victron-BidCos-RF") == [] and cli.newDevices("victron-BidCos-RF", []) == ""
cli.event("victron-BidCos-RF", "NEQ0000007:0", "UNREACH", True)
assert hm._unreach_cache[("BidCos-RF", "NEQ0000007")][1] is True
cli.event("victron-BidCos-RF", "NEQ0000007:0", "UNREACH", False)
assert hm._unreach_cache[("BidCos-RF", "NEQ0000007")][1] is False
print("3) Meldungen: gespeichert, nur relevante wecken die Regeln, UNREACH sofort OK")

# ---- Werte kommen aus dem Push-Speicher (kein Aufruf an die CCU)
def boom(*a, **k):
    raise AssertionError("CCU wurde abgefragt")
real_call = hm._call
hm._call = boom
sen = {"id": "hmS-NEQ0000007-1-STATE", "interface": "BidCos-RF", "address": "NEQ0000007:1", "datapoint": "STATE", "binary": True, "kind": "contact"}
hm._value_cache.clear()
assert hm.read_sensor(sen) is True
dev = {"id": "hm-X", "interface": "BidCos-RF", "address": "NEQ0000007:1", "datapoint": "STATE", "power_addr": None}
assert hm.status(dev) == {"online": True, "on": True, "power": None}
hm._call = real_call
# veralteter Wert -> CCU wird gefragt
# 200 s alt: mit Push noch gueltig (kein Aufruf an die CCU - Lesen kann Funk kosten und den Duty Cycle fuellen)
hm._pushed[("BidCos-RF", "NEQ0000007:1", "STATE")] = (time.time() - 200, True)
hm._call = boom
assert hm._get_value("BidCos-RF", "NEQ0000007:1", "STATE") is True
hm._call = real_call
hm._pushed[("BidCos-RF", "NEQ0000007:1", "STATE")] = (time.time() - hm.PUSH_VALUE_TTL_S - 5, True)
asked = []
hm._call = lambda m, p=None: asked.append(m) or False
assert hm._get_value("BidCos-RF", "NEQ0000007:1", "STATE") is False and asked == ["Interface.getValue"]
hm._call = real_call
print("4) Werte aus Push-Speicher, veraltete werden nachgefragt OK")

# ---- Fremde Absender werden abgewiesen
hm._split_host = lambda host: ("http", "10.9.9.9")
try:
    cli.event("victron-BidCos-RF", "NEQ0000007:1", "STATE", False)
    raise AssertionError("Fremder Absender haette abgelehnt werden muessen")
except xmlrpc.client.ProtocolError as e:
    assert e.errcode == 403
hm._split_host = lambda host: ("http", "127.0.0.1")
print("5) nur die CCU darf melden OK")

# ---- Ausfall: keine Meldungen mehr -> inaktiv (Abfrage-Reserve greift)
hm._push_state["BidCos-RF"]["alive"] = time.time() - 500
hm._push_cycle()
assert not hm._push_state["BidCos-RF"]["ok"] or hm._push_state["BidCos-RF"]["alive"] > time.time() - 5     # nach Neuanmeldung wieder frisch
hm._push_state["BidCos-RF"]["alive"] = time.time() - 500
pass
hm._push_state["BidCos-RF"]["init_ts"] = time.time()
hm._push_cycle()
assert hm._push_state["BidCos-RF"]["ok"] is False and not hm.push_active()
print("6) Ausfall erkannt, Push gilt als inaktiv OK")

# ---- Abmelden
calls.clear()
hm.save_push(False)
hm._push_cycle()
assert ("init", f"http://127.0.0.1:{PORT}", "") in calls, calls
assert not hm.push_active() and hm._inited == {}
print("7) Abmelden bei ausgeschaltetem Push OK")
print("PUSH OK")
