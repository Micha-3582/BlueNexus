"""Bambu-Lab-Drucker (1.39.0): Druckstatus ueber MQTT. Der Drucker wird mit einem kleinen nachgebauten MQTT-Server ohne TLS nachgebildet.
Prueft: Anlegen (falscher Zugangscode, falsche Seriennummer, richtig), Status (druckt, Fortschritt, Temperaturen, Restzeit), Teilmeldungen werden zusammengefuehrt,
Druck fertig -> aus (und die Regeln werden geweckt), Messwerte als Sensor, nicht schaltbar, Ausfall und Wiederverbinden, Entfernen trennt die Verbindung."""
import sys, os, json, time, threading, socket, socketserver
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import bambu, shelly

SERIAL, CODE = "01P00A123456789", "12345678"
PRINT = {"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 75, "layer_num": 20, "total_layer_num": 120, "nozzle_temper": 219.6,
         "bed_temper": 59.8, "chamber_temper": 31, "subtask_name": "Leitpfosten_v1", "print_error": 0}
CLIENTS, REQUESTS = [], []
MODE = {"silent": False}                          # True: Drucker meldet nach dem Verbinden nichts (falsche Seriennummer)


class Printer(socketserver.BaseRequestHandler):
    def handle(self):
        s = self.request
        try:
            typ, _f, body = bambu.read_packet(s)
            assert typ == 1
            pos = 2 + int.from_bytes(body[:2], "big") + 1 + 1 + 2                 # Protokollname, Level, Flags, Keepalive
            cl = int.from_bytes(body[pos:pos + 2], "big"); pos += 2 + cl          # Client-ID
            ul = int.from_bytes(body[pos:pos + 2], "big"); user = body[pos + 2:pos + 2 + ul].decode(); pos += 2 + ul
            pl = int.from_bytes(body[pos:pos + 2], "big"); pw = body[pos + 2:pos + 2 + pl].decode()
            if user != "bblp" or pw != CODE:
                s.sendall(bytes([0x20, 2, 0, 5])); return                        # nicht autorisiert
            s.sendall(bytes([0x20, 2, 0, 0]))
            CLIENTS.append(s)
            while True:
                typ, flags, body = bambu.read_packet(s)
                if typ == 8:                                                      # SUBSCRIBE -> SUBACK
                    s.sendall(bytes([0x90, 3]) + body[:2] + b"\x00")
                elif typ == 3:
                    topic, payload = bambu.parse_publish(flags, body)
                    REQUESTS.append((topic, json.loads(payload)))
                    if topic == f"device/{SERIAL}/request" and not MODE["silent"]:
                        send({"print": dict(PRINT)})
                elif typ == 12:
                    s.sendall(b"\xd0\x00")
        except (OSError, ConnectionError, AssertionError):
            pass
        finally:
            if s in CLIENTS:
                CLIENTS.remove(s)


def send(obj):
    pkt = bambu.publish_packet(f"device/{SERIAL}/report", json.dumps(obj).encode())
    for c in list(CLIENTS):
        try:
            c.sendall(pkt)
        except OSError:
            pass


def wait(cond, sek=6.0, what=""):
    t0 = time.time()
    while time.time() - t0 < sek:
        if cond():
            return True
        time.sleep(0.05)
    raise AssertionError("Zeitueberschreitung: " + what)


socketserver.ThreadingTCPServer.allow_reuse_address = True
srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Printer); srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]
_orig = socket.create_connection
socket.create_connection = lambda addr, timeout=None, *a, **k: _orig(("127.0.0.1", PORT), timeout)
bambu.USE_TLS = False
bambu.PROBE_S, bambu.READ_S, bambu.BACKOFF_START_S, bambu.BACKOFF_MAX_S, bambu.GRACE_S = 1.5, 0.3, 0.3, 0.6, 1.5
woken = []
bambu.set_wake(lambda: woken.append(time.time()))

# ---------------------------------------------------------------- Paketformat
assert bambu._varlen(0) == b"\x00" and bambu._varlen(127) == b"\x7f" and bambu._varlen(128) == b"\x80\x01" and bambu._varlen(321) == b"\xc1\x02"
assert bambu.parse_publish(0, bambu.publish_packet("a/b", b"xyz")[2:]) == ("a/b", b"xyz")

# ---------------------------------------------------------------- Anlegen
for ip, ser, code, what in (("192.168.2.77", SERIAL, "00000000", "Zugangscode"), ("192.168.2.77", "x", CODE, "Seriennummer")):
    try:
        bambu.add_device(ip, ser, code); raise AssertionError("muss abgelehnt werden: " + what)
    except shelly.ShellyError as e:
        assert ("Zugangscode" in str(e)) if what == "Zugangscode" else ("Seriennummer" in str(e)), e
MODE["silent"] = True
try:
    bambu.add_device("192.168.2.77", SERIAL, CODE); raise AssertionError("ohne Meldung muss abgelehnt werden")
except shelly.ShellyError as e:
    assert "meldet nichts" in str(e), e
MODE["silent"] = False
try:
    bambu.add_device("127.0.0.1", SERIAL, CODE); raise AssertionError("nur lokale Adressen")
except shelly.ShellyError:
    pass
assert shelly.load_devices() == []
dev = bambu.add_device("192.168.2.77", SERIAL, CODE, "Michas X1C")
assert dev["kind"] == "bambu" and dev["switchable"] is False and dev["name"] == "Michas X1C" and dev["icon"] == "🖨️" and "password" not in dev, dev
try:
    bambu.add_device("192.168.2.77", SERIAL, CODE); raise AssertionError("nicht doppelt anlegen")
except shelly.ShellyError as e:
    assert "schon angelegt" in str(e)
d = shelly.load_devices()[0]
assert d["password"] == CODE and d["id"] == "bambu-" + SERIAL.lower()

# ---------------------------------------------------------------- Status
wait(lambda: shelly.status(d).get("online"), 6.0, "Zustand da")
st = shelly.status(d)
assert st["on"] is True and st["state"] == "RUNNING" and st["progress"] == 42.0 and st["remaining_min"] == 75.0 and st["nozzle_c"] == 219.6 and st["layer"] == 20.0 and st["job"] == "Leitpfosten_v1", st
assert st["info"].startswith("druckt 42 %") and "noch 1 h 15 min" in st["info"] and "Düse 220 °C" in st["info"], st["info"]
assert any(t == f"device/{SERIAL}/request" and p["pushing"]["command"] == "pushall" for t, p in REQUESTS), REQUESTS
pub = [x for x in shelly.list_with_status(live=True) if x["id"] == d["id"]][0]
assert "password" not in pub and pub["on"] is True and pub["info"], pub

# Teilmeldung: nur der Fortschritt aendert sich, der Rest bleibt
send({"print": {"mc_percent": 57, "mc_remaining_time": 50}})
wait(lambda: shelly.status(d).get("progress") == 57.0, 3.0, "Teilmeldung")
st = shelly.status(d); assert st["nozzle_c"] == 219.6 and st["remaining_min"] == 50.0 and st["on"] is True, st

# ---------------------------------------------------------------- Messwerte als Sensor
ms = {m["metric"]: m for m in shelly.device_metrics(d["id"])}
assert set(ms) >= {"nozzle_c", "bed_c", "chamber_c", "progress", "remaining_min"} and ms["progress"]["kind"] == "progress" and ms["progress"]["value"] == 57.0, ms
sen = shelly.device_metric_sensor(d["id"], "progress")
import homematic
assert sen["kind"] == "progress" and sen["unit"] == "%"

# ---------------------------------------------------------------- Druck fertig: an -> aus, Regeln werden geweckt
woken.clear()
send({"print": {"gcode_state": "FINISH", "mc_percent": 100, "mc_remaining_time": 0}})
wait(lambda: shelly.status(d).get("on") is False, 3.0, "fertig")
st = shelly.status(d); assert st["state"] == "FINISH" and st["info"].startswith("fertig"), st
assert woken, "der Zustandswechsel muss die Regeln wecken"
send({"print": {"gcode_state": "PAUSE", "print_error": 50348044}})
wait(lambda: shelly.status(d).get("state") == "PAUSE", 3.0, "pausiert")
st = shelly.status(d); assert st["on"] is True and st["error"] is True and "Fehlermeldung" in st["info"], st

# ---------------------------------------------------------------- nicht schaltbar
try:
    shelly.set_state(d["id"], True); raise AssertionError("ein Drucker laesst sich nicht schalten")
except shelly.ShellyError as e:
    assert "nicht schaltbar" in str(e)

# ---------------------------------------------------------------- Ausfall und Wiederverbinden
for c in list(CLIENTS):
    c.close()
wait(lambda: not CLIENTS, 3.0, "Verbindung getrennt")
wait(lambda: len(CLIENTS) == 1, 4.0, "verbindet sich selbst neu")
wait(lambda: shelly.status(d).get("online"), 3.0, "wieder online")
srv.shutdown(); srv.server_close()
for c in list(CLIENTS):
    c.close()
wait(lambda: shelly.status(d).get("online") is False, 6.0, "nach der Karenzzeit nicht erreichbar")

# ---------------------------------------------------------------- Entfernen
assert shelly.remove(d["id"]) is True
assert SERIAL not in bambu._hosts and SERIAL not in bambu._data
print("ok")
