"""ONVIF-Ereignisse fuer RTSP-Kameras ohne Reolink-HTTP (1.45.0): nachgebildete Kamera (SOAP) -> Anmeldung, Anfangszustand, Aenderungen,
Kamera-Sensoren (Bewegung/Person/Fahrzeug/Tier), Fehler (falsches Passwort, nicht erreichbar), Wiederverbindung, Entfernen."""
import sys, os, threading, time, re, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import camera, onvif, homematic

camera.CAMERAS_PATH = os.path.join(tmp, "cameras_onvif.json")
SENS = os.path.join(tmp, "sens_onvif.json")

STATE = {"md": False, "people": False, "pw": "geheim", "pulls": 0, "subs": 0, "queue": []}


def notif(topic, item, val):
    return (f'<wsnt:NotificationMessage><wsnt:Topic Dialect="x">tns1:{topic}</wsnt:Topic><wsnt:Message><tt:Message><tt:Data>'
            f'<tt:SimpleItem Name="{item}" Value="{"true" if val else "false"}"/></tt:Data></tt:Message></wsnt:Message></wsnt:NotificationMessage>')


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        def send(x, code=200):
            self.send_response(code); self.send_header("Content-Type", "application/soap+xml"); self.end_headers(); self.wfile.write(x.encode())
        if "GetSystemDateAndTime" in body:
            return send('<e><UTCDateTime><Time><Hour>12</Hour><Minute>0</Minute><Second>0</Second></Time><Date><Year>2026</Year><Month>11</Month><Day>7</Day></Date></UTCDateTime></e>')
        import base64, hashlib
        m = re.search(r"PasswordDigest\">([^<]+)<.*?<wsse:Nonce[^>]*>([^<]+)<.*?<wsu:Created>([^<]+)<", body, re.S)
        if not m or base64.b64encode(hashlib.sha1(base64.b64decode(m.group(2)) + m.group(3).encode() + STATE["pw"].encode()).digest()).decode() != m.group(1):
            return send("<e>Sender not Authorized</e>", 400)
        if "GetCapabilities" in body:
            return send(f'<e><Events><XAddr>http://10.9.9.9:{PORT}/onvif/event_service</XAddr></Events></e>')
        if "CreatePullPointSubscription" in body:
            STATE["subs"] += 1
            return send(f'<e><SubscriptionReference><wsa:Address>http://10.9.9.9:{PORT}/onvif/PullSubManager?Idx=1</wsa:Address></SubscriptionReference></e>')
        if "PullMessages" in body:
            assert "PullMessagesRequest" in body and "wsa:To" in body, "Adress-Koepfe fehlen"
            STATE["pulls"] += 1
            if STATE["pulls"] == 1:
                msgs = [notif("RuleEngine/CellMotionDetector/Motion", "IsMotion", False), notif("RuleEngine/MyRuleDetector/PeopleDetect", "State", False),
                        notif("RuleEngine/MyRuleDetector/FaceDetect", "State", True), notif("VideoSource/MotionAlarm", "State", False)]
            else:
                msgs, STATE["queue"] = STATE["queue"], []
                time.sleep(0.2)
            return send("<e>" + "".join(msgs) + "</e>")
        send("<e/>", 400)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
onvif.PULL_S = 1

# ---- Auswertung der Nachrichten
x = "<a>" + notif("RuleEngine/MyRuleDetector/VehicleDetect", "State", True) + notif("RuleEngine/MyRuleDetector/Package", "State", True) + notif("RuleEngine/CellMotionDetector/Motion", "IsMotion", False) + "</a>"
assert onvif.parse_messages(x) == [("vehicle", True), ("md", False)], onvif.parse_messages(x)       # Paket u. a. werden uebergangen

# ---- Kamera anlegen (RTSP mit ONVIF-Port)
cam = {"id": "cam-test1", "kind": "rtsp", "name": "Kasse", "host": "127.0.0.1", "user": "admin", "password": "geheim", "onvif_port": PORT, "model": "Lumus 2K", "show": True, "users": []}
camera._save([cam])

try:
    st = camera.motion_states(camera.get("cam-test1"), force=True)
except Exception:
    w = onvif._workers.get("cam-test1"); print("DEBUG", w and (w.is_alive(), w.stop, w.error, w.support, w.ok_at), camera.get("cam-test1")); raise
assert st["md"] is False and st["people"] is False and st["support"] == {"md", "people"}, st           # Gesicht/Alarm nicht angeboten
STATE["queue"] = [notif("RuleEngine/MyRuleDetector/PeopleDetect", "State", True), notif("RuleEngine/CellMotionDetector/Motion", "IsMotion", True)]
for _ in range(40):
    time.sleep(0.1)
    st = camera.motion_states(camera.get("cam-test1"))
    if st.get("people"):
        break
assert st["people"] is True and st["md"] is True, st
STATE["queue"] = [notif("RuleEngine/MyRuleDetector/PeopleDetect", "State", False)]
for _ in range(40):
    time.sleep(0.1)
    if camera.motion_states(camera.get("cam-test1")).get("people") is False:
        break
assert camera.motion_states(camera.get("cam-test1"))["people"] is False and camera.motion_states(camera.get("cam-test1"))["md"] is True

# ---- Suchen: RTSP-Kamera erscheint mit Bewegung + Person, Drucker-Kamera (tls) nicht
camera._save([cam, {**cam, "id": "cam-bambu", "name": "Drucker", "tls": True, "host": "127.0.0.2"}])
found = camera.motion_scan(set())
assert [f["id"] for f in found] == ["cam-cam-test1-md", "cam-cam-test1-people"], [f["id"] for f in found]
assert found[0]["model"] == "Lumus 2K" and found[0]["name"] == "Kasse – Bewegung" and found[0]["source"] == "camera", found[0]
camera._save([cam])

# ---- als Sensor lesen (wie die Regeln)
sen = {"id": "cam-cam-test1-people", "kind": "motion", "address": "cam-test1", "datapoint": "people", "source": "camera", "binary": True}
assert camera.read_motion(sen) is False
sen["datapoint"] = "vehicle"; assert camera.read_motion(sen) is None                                   # nicht angeboten -> kein Wert

# ---- Wiederverbindung: Abo laeuft ab -> neues Abo, Anfangszustand wieder da
n = STATE["subs"]; onvif.SUB_S = 31
onvif.forget("cam-test1"); STATE["pulls"] = 0
camera.motion_states(camera.get("cam-test1"), force=True)
assert STATE["subs"] == n + 1

# ---- falsches Passwort
onvif.forget("cam-test1")
camera._save([{**cam, "password": "falsch"}])
try:
    camera.motion_states(camera.get("cam-test1"), force=True); raise AssertionError("muss scheitern")
except camera.CameraError as e:
    assert "Anmeldung" in str(e), e
onvif.forget("cam-test1")
assert camera.read_motion(sen) is None

# ---- Kamera nicht erreichbar
onvif.forget("cam-test1"); camera._save([{**cam, "onvif_port": 1}])
try:
    camera.motion_states(camera.get("cam-test1"), force=True); raise AssertionError("muss scheitern")
except camera.CameraError as e:
    assert "nicht erreichbar" in str(e), e

# ---- Entfernen beendet den Thread
onvif.forget("cam-test1"); camera._save([cam]); STATE["pulls"] = 0
camera.motion_states(camera.get("cam-test1"), force=True)
w = onvif._workers["cam-test1"]; assert w.is_alive()
assert camera.remove("cam-test1")
w.join(5); assert not w.is_alive()
print("ok")
