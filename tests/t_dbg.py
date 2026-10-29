import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import shelly, homematic, virtual
from auth import UserStore
store.module_on = lambda n, cfg=None: True
homematic._save_sensors([{"id": "s1", "kind": "contact", "address": "A", "interface": "x", "datapoint": "T", "binary": True, "unit": "", "name": "Tor", "model": "m", "room": "", "show": True, "users": ["fried"]}])
webapp.users = UserStore(os.path.join(tmp, "u_d.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("fried", "friedpass123", {"dashboard": "write", "settings_geraete": "read"})
webapp.users.set_dashboard_tiles("fried", ["show_favorites_card","show_shelly_card","show_virtual_card","show_sensors_card","show_weather_card"])
F = webapp.app.test_client(); F.post("/login", data={"username": "fried", "password": "friedpass123"})
print(F.get("/api/sensors?light=1").get_json())
print(F.get("/api/virtual").get_json())
print(F.get("/api/ui").get_json() if F.get("/api/ui").status_code==200 else F.get("/api/ui").status_code)
