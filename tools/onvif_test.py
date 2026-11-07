"""ONVIF-Test fuer eine Kamera (z. B. Reolink Lumus 2K): zeigt, welche Ereignisse (Bewegung, Person, Fahrzeug, Tier ...) sie meldet.

Aufruf (PowerShell, im Ordner K:\\Claude Projekte\\BlueNexus):
    python tools\\onvif_test.py 192.168.51.162
Das Passwort wird abgefragt (nichts wird gespeichert). Port 8000 ist der Standard-ONVIF-Port der Kamera.
Waehrend des Tests (ca. 120 s) bitte vor der Kamera bewegen, ggf. eine Person laufen lassen.
Das Ergebnis wird zusaetzlich in onvif_test_ergebnis.txt neben dem Skript gespeichert (ohne Passwort).
"""
import sys, re, time, base64, hashlib, os, getpass, secrets, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

HOST = sys.argv[1] if len(sys.argv) > 1 else input("IP-Adresse der Kamera: ").strip()
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
USER = input("Benutzer [admin]: ").strip() or "admin"
PASSWORD = getpass.getpass("Passwort (wird nicht angezeigt): ")
OUT = []


def say(*a):
    t = " ".join(str(x) for x in a)
    print(t)
    OUT.append(t)


def utc(off=0.0):
    return (datetime.now(timezone.utc) + timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def header(off, action='', to=''):
    nonce = secrets.token_bytes(16)
    created = utc(off)
    dig = base64.b64encode(hashlib.sha1(nonce + created.encode() + PASSWORD.encode()).digest()).decode()
    wsa = (f'<wsa:Action xmlns:wsa="http://www.w3.org/2005/08/addressing" s:mustUnderstand="1">{action}</wsa:Action><wsa:To xmlns:wsa="http://www.w3.org/2005/08/addressing" s:mustUnderstand="1">{to}</wsa:To>') if action else ''
    return ('<s:Header>' + wsa + '<wsse:Security xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd" '
            'xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd"><wsse:UsernameToken>'
            f'<wsse:Username>{USER}</wsse:Username><wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{dig}</wsse:Password>'
            f'<wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>'
            f'<wsu:Created>{created}</wsu:Created></wsse:UsernameToken></wsse:Security></s:Header>')


def soap(url, body, off=0.0, auth=True, action=''):
    xml = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
           + (header(off, action, url) if auth else "") + f"<s:Body>{body}</s:Body></s:Envelope>")
    req = urllib.request.Request(url, xml.encode(), {"Content-Type": "application/soap+xml; charset=utf-8"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 0, f"{e.__class__.__name__}: {e}"


base = f"http://{HOST}:{PORT}"
say(f"== ONVIF-Test {HOST}:{PORT}  ({datetime.now():%d.%m.%Y %H:%M:%S}) ==")

# 1) Kamerauhr (ohne Anmeldung) -> Zeitversatz fuer die Anmeldung
off = 0.0
st, x = soap(base + "/onvif/device_service", '<GetSystemDateAndTime xmlns="http://www.onvif.org/ver10/device/wsdl"/>', auth=False)
m = re.search(r"<(?:\w+:)?UTCDateTime>.*?<(?:\w+:)?Hour>(\d+)<.*?<(?:\w+:)?Minute>(\d+)<.*?<(?:\w+:)?Second>(\d+)<.*?<(?:\w+:)?Year>(\d+)<.*?<(?:\w+:)?Month>(\d+)<.*?<(?:\w+:)?Day>(\d+)<", x, re.S)
if m:
    h, mi, s_, y, mo, d = map(int, m.groups())
    cam = datetime(y, mo, d, h, mi, s_, tzinfo=timezone.utc)
    off = (cam - datetime.now(timezone.utc)).total_seconds()
    say(f"1) Kamerauhr gelesen, Abweichung zur PC-Uhr: {off:+.0f} s")
else:
    say(f"1) Kamerauhr nicht lesbar (HTTP {st}): {x[:200]}")

# 2) Ereignisdienst finden
st, x = soap(base + "/onvif/device_service", '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl"><Category>All</Category></GetCapabilities>', off)
say(f"2) GetCapabilities: HTTP {st}")
ev = re.search(r"<(?:\w+:)?Events>\s*<(?:\w+:)?XAddr>([^<]+)<", x)
if st != 200 or not ev:
    say("   Antwort:", x[:600])
    ev_url = base + "/onvif/event_service"
    say("   Ereignisdienst nicht gefunden, versuche", ev_url)
else:
    ev_url = ev.group(1)
    say("   Ereignisdienst:", ev_url)
ev_url = re.sub(r"^http://[^/]+", base, ev_url)         # Kamera meldet manchmal eine andere Adresse

# 3) Welche Ereignisarten gibt es?
st, x = soap(ev_url, '<GetEventProperties xmlns="http://www.onvif.org/ver10/events/wsdl"/>', off)
say(f"3) GetEventProperties: HTTP {st}")
import xml.etree.ElementTree as ET
topics = []
try:
    def walk(e, path):
        tag = e.tag.split("}")[-1]
        p = path + [tag]
        if any(k.endswith("}topic") and v == "true" for k, v in e.attrib.items()):
            topics.append("/".join(p))
        for c in e:
            walk(c, p)
    ts = [e for e in ET.fromstring(x).iter() if e.tag.endswith("}TopicSet")]
    for t in ts:
        for c in t:
            walk(c, [])
except Exception as ex:
    say("   (Auslesen fehlgeschlagen:", ex, ")")
topics = sorted(set(topics))
if topics:
    say("   Ereignisarten, die die Kamera kennt:")
    for t in topics:
        say("     -", t)
else:
    say("   Antwort:", x[:800])

# 4) Abo anlegen und Ereignisse einsammeln
body = ('<CreatePullPointSubscription xmlns="http://www.onvif.org/ver10/events/wsdl"><InitialTerminationTime>PT300S</InitialTerminationTime></CreatePullPointSubscription>')
st, x = soap(ev_url, body, off)
say(f"4) CreatePullPointSubscription: HTTP {st}")
addr = re.search(r"<(?:\w+:)?Address[^>]*>([^<]+)<", x)
if st != 200 or not addr:
    say("   Antwort:", x[:800])
    say("\nKein Abo moeglich - bitte dieses Ergebnis an Claude geben.")
else:
    sub = re.sub(r"^http://[^/]+", base, addr.group(1).strip())
    say("   Abo-Adresse:", sub)
    say("\n5) Ereignisse (ca. 120 s). BITTE JETZT vor der Kamera bewegen / eine Person laufen lassen ...")
    end = time.time() + 120
    n = 0
    last = time.time()
    while time.time() < end:
        st, x = soap(sub, '<PullMessages xmlns="http://www.onvif.org/ver10/events/wsdl"><Timeout>PT5S</Timeout><MessageLimit>50</MessageLimit></PullMessages>', off, action="http://www.onvif.org/ver10/events/wsdl/PullPointSubscription/PullMessagesRequest")
        if st != 200:
            say(f"   PullMessages: HTTP {st}"); say(re.sub(r"\s+", " ", x)[-900:])
            break
        if time.time() - last >= 30:
            last = time.time(); say(f"   ... noch {max(0, int(end - time.time()))} s")
        for msg in re.findall(r"<(?:\w+:)?NotificationMessage.*?</(?:\w+:)?NotificationMessage>", x, re.S):
            topic = re.search(r"<(?:\w+:)?Topic[^>]*>([^<]+)<", msg)
            items = re.findall(r'<(?:\w+:)?SimpleItem\s+Name="([^"]+)"\s+Value="([^"]*)"', msg) or re.findall(r'<(?:\w+:)?SimpleItem\s+Value="([^"]*)"\s+Name="([^"]+)"', msg)
            say(f"   [{datetime.now():%H:%M:%S}] {topic.group(1).strip() if topic else '?'}  {items}")
            n += 1
    say(f"\n   {n} Ereignisse empfangen.")

fn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "onvif_test_ergebnis.txt")
with open(fn, "w", encoding="utf-8") as f:
    f.write("\n".join(OUT))
print("\nErgebnis gespeichert in", fn)
