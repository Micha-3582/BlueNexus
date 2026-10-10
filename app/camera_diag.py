"""Diagnose für die SD-Karten-Aufnahmen der Reolink-Kameras: Kann die App die Aufnahmeliste lesen und eine Aufnahme herunterladen?

Aufruf (im App-Ordner, mit der Python-Umgebung der App):
    ./venv/bin/python camera_diag.py [Stunden] [Kamera-Name-Teil]
Beispiele:  ./venv/bin/python camera_diag.py          (alle Kameras, letzte 12 Stunden)
            ./venv/bin/python camera_diag.py 48 Garage   (nur Kameras mit „Garage“ im Namen, letzte 48 Stunden)

Es wird nichts verändert, gelöscht oder gespeichert: nur lesen. Für den Download-Test werden höchstens ca. 3 MB einer Aufnahme geladen.
"""
import sys
import time
from datetime import datetime, timedelta

import requests

import camera

requests.packages.urllib3.disable_warnings()   # selbstsignierte Zertifikate der Kameras


def _t(dt):
    return {"year": dt.year, "mon": dt.month, "day": dt.day, "hour": dt.hour, "min": dt.minute, "sec": dt.second}


def _fmt(t):
    try:
        return "%04d-%02d-%02d %02d:%02d:%02d" % (t["year"], t["mon"], t["day"], t["hour"], t["min"], t["sec"])
    except (KeyError, TypeError):
        return "?"


def _secs(f):
    try:
        a, b = f["StartTime"], f["EndTime"]
        return int((datetime(b["year"], b["mon"], b["day"], b["hour"], b["min"], b["sec"]) - datetime(a["year"], a["mon"], a["day"], a["hour"], a["min"], a["sec"])).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None


def api(item, cmd, param, action=0):
    """Reolink-Befehl mit Token; gibt (Antwort-dict, Fehlertext) zurück."""
    try:
        tok = camera._auth(item)
        r = requests.post(camera._base(item), params={"cmd": cmd, **tok}, json=[{"cmd": cmd, "action": action, "param": param}], timeout=15, verify=False)
        j = r.json()[0]
    except Exception as e:                                                  # noqa: BLE001
        return None, "%s: %s" % (e.__class__.__name__, e)
    if j.get("code") != 0:
        return None, "Fehlercode %s" % (camera._detail(j))
    return j.get("value") or {}, ""


def search(item, start, end, stream):
    ch = int(item.get("channel") or 0)
    param = {"Search": {"channel": ch, "onlyStatus": 0, "streamType": stream, "StartTime": _t(start), "EndTime": _t(end)}}
    for action in (1, 0):                                                   # laut Reolink-Doku action 1; manche Firmware nimmt nur 0
        v, err = api(item, "Search", param, action)
        if v is not None:
            files = ((v.get("SearchResult") or {}).get("File")) or []
            return files, "", action
    return [], err, None


def download_test(item, name, limit=3 * 1024 * 1024):
    """Lädt höchstens `limit` Bytes einer Aufnahme (Download-Befehl, danach Playback als Ersatz)."""
    out = []
    for cmd in ("Download", "Playback"):
        try:
            tok = camera._auth(item)
            params = {"cmd": cmd, "source": name, "output": name.split("/")[-1], **tok}
            t0 = time.time()
            r = requests.get(camera._base(item), params=params, stream=True, timeout=20, verify=False)
            if r.status_code != 200:
                out.append("%s: HTTP %s" % (cmd, r.status_code)); r.close(); continue
            got, head = 0, b""
            for chunk in r.iter_content(65536):
                if not head:
                    head = chunk[:16]
                got += len(chunk)
                if got >= limit:
                    break
            r.close()
            dt = max(time.time() - t0, 0.01)
            kind = "MP4" if b"ftyp" in head else ("FLV" if head[:3] == b"FLV" else "unbekanntes Format (%r)" % head[:8])
            out.append("%s: OK – %.1f MB in %.1f s (%.1f MB/s), %s, Content-Type %s" % (cmd, got / 1e6, dt, got / 1e6 / dt, kind, r.headers.get("Content-Type", "?")))
            return True, out
        except Exception as e:                                              # noqa: BLE001
            out.append("%s: %s" % (cmd, e.__class__.__name__))
    return False, out


def main():
    hours = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 12
    part = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
    cams = [c for c in camera.load() if c.get("kind", "reolink") == "reolink" and part in (c.get("name") or "").lower()]
    if not cams:
        print("Keine passende Reolink-Kamera gefunden."); return
    end = datetime.now(); start = end - timedelta(hours=hours)
    print("Zeitraum: %s bis %s (Serverzeit)\n" % (start.strftime("%d.%m. %H:%M"), end.strftime("%d.%m. %H:%M")))
    summary = []
    for c in cams:
        name = c.get("name") or c["id"]
        print("=" * 70); print("Kamera: %s  (%s)" % (name, c.get("host")))
        try:
            info = camera.device_info(c)
            print("  Modell: %s   Firmware: %s" % (info.get("model") or c.get("model") or "?", info.get("firmware") or info.get("firmVer") or "?"))
        except Exception as e:                                              # noqa: BLE001
            print("  Gerätedaten: %s" % e)
            summary.append((name, "nicht erreichbar", "-", "-")); continue
        rec, err = api(c, "GetRec", {"channel": int(c.get("channel") or 0)})
        if rec:
            r = rec.get("Rec", rec)
            print("  Aufnahme-Einstellungen: Vorab-Aufnahme=%s, Nachlauf=%s, Überschreiben=%s" % (r.get("preRec"), r.get("postRec"), r.get("overwrite")))
        files, err, action = [], "", None
        for stream in ("main", "sub"):
            files, err, action = search(c, start, end, stream)
            if files:
                print("  Suche (%s-Stream): %d Aufnahme(n) gefunden" % (stream, len(files))); break
        if not files:
            print("  Suche: %s" % (err or "keine Aufnahmen im Zeitraum (SD-Karte leer, Aufnahme aus oder nichts passiert?)"))
            summary.append((name, "Suche OK" if not err else "Suche geht nicht", "keine Aufnahmen" if not err else err, "-")); continue
        files.sort(key=lambda f: _fmt(f.get("StartTime")))
        for f in files[-5:]:
            print("   • %s  %s – %s  (%s s, %s MB, %sx%s)  %s" % (f.get("type", "?"), _fmt(f.get("StartTime")), _fmt(f.get("EndTime")), _secs(f), round(int(f.get("size") or 0) / 1e6, 1) if str(f.get("size", "")).isdigit() else f.get("size"), f.get("width"), f.get("height"), f.get("name")))
        types = sorted({str(f.get("type")) for f in files})
        print("  Aufnahme-Typen im Zeitraum: %s" % ", ".join(types))
        ok, lines = download_test(c, files[-1]["name"])
        for l in lines:
            print("  Download-Test – " + l)
        summary.append((name, "Suche OK (%d Dateien)" % len(files), ", ".join(types), "Download OK" if ok else "Download geht NICHT"))
    print("\n" + "=" * 70); print("ZUSAMMENFASSUNG")
    for s in summary:
        print("  %-14s | %-26s | Typen: %-28s | %s" % s)


if __name__ == "__main__":
    main()
