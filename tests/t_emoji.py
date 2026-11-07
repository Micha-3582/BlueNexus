import sys, os, io, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic
R = [(0x23FB, 0x23FB)]   # seit 1.44.0 sind neuere Emoji (13-15) erlaubt; verboten bleiben nur Nicht-Emoji-Zeichen wie das Ein/Aus-Zeichen (Kaestchen auf dem Handy)
bad = lambda c: any(a <= ord(c) <= b for a, b in R)
assert not [i for i in shelly.ICONS if any(bad(c) for c in i)]
root = sys.argv[1]
for f in glob.glob(root + "/app/**/*.py", recursive=True) + glob.glob(root + "/app/**/*.html", recursive=True) + glob.glob(root + "/app/static/*.js"):
    assert not [c for c in io.open(f, encoding="utf-8", errors="ignore").read() if bad(c)], f
assert len(shelly.ICONS) == len(set(shelly.ICONS)) and "🔌" in shelly.ICONS
homematic._save_sensors([{"id": "s1", "kind": "motion", "address": "A", "interface": "x", "datapoint": "M", "binary": True, "unit": "", "name": "F", "model": "m", "room": "", "icon": chr(0x23fb)}])
webapp._migrate_icons(); assert homematic.load_sensors()[0]["icon"] == "🔌"
print("SYMBOLE-ALTER OK")
assert all(c in shelly.ICONS for c in (chr(0x1FA9F), chr(0x1FAB4), chr(0x1F6DC)))   # Fenster, Zimmerpflanze, WLAN
