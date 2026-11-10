import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import inventory, shelly, camera
# Drucker und seine Kamera teilen sich eine Adresse: das ist KEIN Konflikt
shelly.load_devices = lambda: [{"id": "p1", "name": "Drucker", "kind": "bambu", "ip": "192.168.2.140"}, {"id": "s1", "name": "A", "kind": "shelly", "ip": "192.168.2.50"}, {"id": "s2", "name": "B", "kind": "shelly", "ip": "192.168.2.50"}]
camera.load = lambda: [{"id": "c1", "name": "Drucker-Kamera", "host": "192.168.2.140", "kind": "rtsp"}, {"id": "c2", "name": "K1", "host": "192.168.2.9", "kind": "reolink"}, {"id": "c3", "name": "K2", "host": "192.168.2.9", "kind": "reolink"}]
rows = {r["name"]: r["doppelt"] for r in inventory.collect()}
assert rows["Drucker"] is False and rows["Drucker-Kamera"] is False, rows
assert rows["A"] is True and rows["B"] is True, rows                    # zwei Schalter auf einer Adresse: echter Konflikt
assert rows["K1"] is True and rows["K2"] is True, rows                  # zwei Kameras auf einer Adresse bleiben markiert
print("INVENTORY-DUP OK")
