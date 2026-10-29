import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
from auth import UserStore
from logic import Params
import planner

webapp.users = UserStore(os.path.join(tmp, "u_pv.json")); webapp.users.create("admin", "adminpass1")
webapp.opslog.log = lambda *a, **k: None

# 1) Params: Prozent -> kWh Platz
p = Params.from_config({"battery_usable_kwh": 22.8, "pv_reserve_soc": 80})
assert abs(p.pv_reserve_kwh - 4.56) < 1e-6, p.pv_reserve_kwh
p = Params.from_config({"battery_usable_kwh": 20.0, "pv_reserve_soc": 100}); assert p.pv_reserve_kwh == 0.0
p = Params.from_config({"battery_usable_kwh": 20.0, "pv_reserve_soc": 0}); assert p.pv_reserve_kwh == 20.0
p = Params.from_config({"battery_usable_kwh": 20.0, "pv_reserve_soc": 250}); assert p.pv_reserve_kwh == 0.0                       # begrenzt
p = Params.from_config({"battery_usable_kwh": 20.0, "pv_reserve_soc": "abc", "pv_reserve_kwh": 3.0}); assert p.pv_reserve_kwh == 3.0     # ungueltig -> alter Wert
p = Params.from_config({"battery_usable_kwh": 22.8, "pv_reserve_kwh": 5.0}); assert p.pv_reserve_kwh == 5.0                        # alte Einstellung bleibt wirksam
print("1) Params OK")

# 2) Planer: Netzladen bis (cap - Reserve), Ladelimit als strengere/hoehere Grenze
p = Params.from_config({"battery_usable_kwh": 22.8, "pv_reserve_soc": 80, "max_charge_soc": 95})
b = planner.battery_from_params(p); assert abs(b.grid_cap - 22.8 * 0.80) < 1e-6, b.grid_cap
p = Params.from_config({"battery_usable_kwh": 22.8, "pv_reserve_soc": 100, "max_charge_soc": 90})
b = planner.battery_from_params(p); assert abs(b.grid_cap - 22.8 * 0.90) < 1e-6, b.grid_cap
print("2) Planer OK")

# 3) API: alte kWh-Einstellung wird als % angezeigt, Speichern setzt den neuen Wert
c = webapp.app.test_client(); c.post("/login", data={"username": "admin", "password": "adminpass1"})
cf = store.load_config(); cf.pop("pv_reserve_soc", None); cf.update({"battery_usable_kwh": 22.8, "pv_reserve_kwh": 5.0}); store.save_config(cf)
j = c.get("/api/config").get_json(); assert abs(j["pv_reserve_soc"] - 78.1) < 0.05, j["pv_reserve_soc"]                   # (22,8-5)/22,8
r = c.post("/api/config", json={"pv_reserve_soc": 80}); assert r.status_code == 200
assert store.load_config()["pv_reserve_soc"] == 80 and c.get("/api/config").get_json()["pv_reserve_soc"] == 80
c.post("/api/config", json={"pv_reserve_soc": 150}); assert store.load_config()["pv_reserve_soc"] == 100.0
c.post("/api/config", json={"pv_reserve_soc": -5}); assert store.load_config()["pv_reserve_soc"] == 0.0
assert b"pv_reserve_soc" in c.get("/admin").data
print("3) API OK")
print("PVRESERVE OK")
