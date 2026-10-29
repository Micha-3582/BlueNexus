import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import victron

class FakeRR:
    def __init__(s, r=None): s.registers = r or []
    def isError(s): return False

class FakeClient:
    def __init__(s, **k): pass
    def connect(s): return True
    def close(s): pass
    def read_input_registers(s, address, count, **k):
        # vebus (227): alles ok ausser Ueberlast=2; battery (225): alles ok
        if (k.get("device_id") or k.get("slave")) == victron.VEBUS_UNIT:
            return FakeRR([2 if address == 36 else 0])
        return FakeRR([0])

victron.ModbusTcpClient = FakeClient
webapp.Cerbo = victron.Cerbo
cfg.update({"cerbo_host": "1.2.3.4"})
webapp.store.is_configured = lambda c: True
class U:
    def get(self, n): return {"username": "t"}
    def __getattr__(self, n): return lambda *a, **k: False
webapp.users = U(); c = webapp.app.test_client()
with c.session_transaction() as s: s["user"] = "t"

# ---- SOH (Alterungszustand)
class FakeClientSoh(FakeClient):
    def read_input_registers(s2, address, count, **k):
        return FakeRR([990]) if address == victron.SOH_REG else super().read_input_registers(address, count, **k)


orig_modbus_client = victron.ModbusTcpClient
victron.ModbusTcpClient = FakeClientSoh
assert victron.Cerbo("x").read_soh() == 99.0
victron.ModbusTcpClient = orig_modbus_client

r = c.get("/api/alarms").get_json()
print(r)
assert r["ok"] is True
assert r["values"]["vebus_overload"] == 2 and r["values"]["vebus_grid_lost"] == 0
assert r["values"]["battery_low_soc"] == 0
assert not r["errors"], r["errors"]
print("ALARMS OK", sys.argv[1].split("/")[-1])
