import sys, os, io, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic
R = [(0x1F6D6,0x1F6D7),(0x1F6DC,0x1F6DF),(0x1F6FB,0x1F6FC),(0x1F7F0,0x1F7F0),(0x1F90C,0x1F90C),(0x1F972,0x1F972),(0x1F977,0x1F979),(0x1F9A3,0x1F9A4),(0x1F9AB,0x1F9AD),(0x1F9CB,0x1F9CC),(0x1FA74,0x1FA74),(0x1FA7B,0x1FA7C),(0x1FA83,0x1FA86),(0x1FA96,0x1FAFF),(0x23FB,0x23FB)]
bad = lambda c: any(a <= ord(c) <= b for a, b in R)
assert not [i for i in shelly.ICONS if any(bad(c) for c in i)]
root = sys.argv[1]
for f in glob.glob(root + "/app/**/*.py", recursive=True) + glob.glob(root + "/app/**/*.html", recursive=True) + glob.glob(root + "/app/static/*.js"):
    assert not [c for c in io.open(f, encoding="utf-8", errors="ignore").read() if bad(c)], f
assert len(shelly.ICONS) == len(set(shelly.ICONS)) and "🔌" in shelly.ICONS
homematic._save_sensors([{"id": "s1", "kind": "motion", "address": "A", "interface": "x", "datapoint": "M", "binary": True, "unit": "", "name": "F", "model": "m", "room": "", "icon": chr(0x23fb)}])
webapp._migrate_icons(); assert homematic.load_sensors()[0]["icon"] == "🔌"
print("SYMBOLE-ALTER OK")
