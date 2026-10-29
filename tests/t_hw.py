import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import hardware, report
RATE = [0.5]
FAKE = {"/proc/meminfo": "MemTotal:  909000 kB\nMemFree: 100000 kB\nMemAvailable: 585000 kB\nSwapTotal: 102400 kB\nSwapFree: 102400 kB\n",
        "/proc/loadavg": "0.45 0.40 0.30 1/200 999\n", "/proc/uptime": "190000.5 100.0\n", "/sys/class/thermal/thermal_zone0/temp": "52300\n",
        "/proc/self/status": "Name: python\nVmRSS:   84000 kB\n", "/proc/device-tree/model": "Raspberry Pi 3 Model B Rev 1.2\x00"}
def run(over=None):
    data = dict(FAKE); data.update(over or {})
    hardware._read = lambda p: data.get(p)
    hardware._throttled = lambda: None; hardware._cores = lambda: 4.0; hardware._cpu_used_s = lambda: time.time() * RATE[0]; hardware._proc_cpu_s = lambda: time.time() * 0.1; hardware._cpu_prev.clear()
    hardware._cache["v"] = None
    return hardware.snapshot()
v = run(); assert v["mem_total_mb"] == 888 and v["mem_avail_pct"] > 60 and v["temp_c"] == 52.3 and v["load1"] == 0.45 and v["app_rss_mb"] == 82 and v["model"].startswith("Raspberry Pi 3"), v
s, t = hardware.judge(v); assert s == "ok" and "Speicher" in t, (s, t)
s, t = hardware.judge(run({"/proc/meminfo": "MemTotal: 909000 kB\nMemAvailable: 100000 kB\nSwapTotal: 102400 kB\nSwapFree: 10000 kB\n"})); assert s == "fail" and "Arbeitsspeicher" in t and "Auslagerung" in t, (s, t)
s, t = hardware.judge(run({"/proc/meminfo": "MemTotal: 909000 kB\nMemAvailable: 120000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"})); assert s == "warn", (s, t)
s, t = hardware.judge(run({"/sys/class/thermal/thermal_zone0/temp": "79000\n"})); assert s == "warn" and "warm" in t
s, t = hardware.judge(run({"/sys/class/thermal/thermal_zone0/temp": "84000\n"})); assert s == "fail"
s, t = hardware.judge(run({"/proc/loadavg": "14.0 5 4 1/1 1\n"})); assert s == "fail" and "überlastet" in t
hardware._read = lambda p: None; hardware._cache["v"] = None; assert hardware.snapshot() is None and hardware.judge(None)[0] == "info"
# Bericht
run(); 
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_hw.json")); webapp.users.create("admin", "adminpass1")
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"})
j = A.get("/api/report?days=3").get_json(); assert j["hardware"]["mem_avail_mb"] == 571 and any(c["key"] == "hardware" and c["status"] == "ok" for c in j["checks"]), j["hardware"]
md = A.get("/api/report?format=md").get_data(as_text=True); assert "## Hardware" in md and "Raspberry Pi 3" in md and "52 °C" in md, md[-900:]
cfg["modules"] = {"energy": False, "smarthome": True, "verlauf": True, "cameras": True, "alexa": False}
j = A.get("/api/report").get_json(); assert j["hardware"] and any(c["key"] == "hardware" for c in j["checks"])      # auch ohne Energie
assert "## Hardware" in A.get("/api/report?format=md").get_data(as_text=True)
hardware._read = lambda p: None; hardware._cache["v"] = None
j = A.get("/api/report").get_json(); assert j["hardware"] is None and not any(c["key"] == "hardware" for c in j["checks"])   # kein Linux: kein Block, kein Fehler
# CPU-Auslastung (echte Messung statt Last-Wert) + Container
hardware._cpu_prev.clear(); v = run(); assert 10 < v["cpu_pct"] < 15 and 1.5 < v["app_cpu_pct"] < 3.5 and v["container"] is False, (v.get("cpu_pct"), v.get("app_cpu_pct"))
v = run({"/run/systemd/container": "lxc" + chr(10), "/proc/loadavg": "9.0 8 7 1/1 1" + chr(10)}); assert v["container"] is True
s, t = hardware.judge(v); assert s == "ok" and "Prozessor" in t and "Last" not in t, (s, t)                 # Container: die Last des ganzen Servers zaehlt nicht
RATE[0] = 3.8; hardware._cpu_prev.clear(); v = run(); s, t = hardware.judge(v); assert v["cpu_pct"] >= 90 and s == "warn" and "ausgelastet" in t, (v["cpu_pct"], s, t)
RATE[0] = 0.5
j = A.get("/api/hardware").get_json(); assert j["hardware"]["mem_avail_mb"] == 571, j
hardware._read = lambda p: None; hardware._cache["v"] = None; assert A.get("/api/hardware").get_json()["hardware"] is None
print("HARDWARE OK")
