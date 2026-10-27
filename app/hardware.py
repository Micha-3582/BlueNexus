"""
Hardware-Monitor fuer den Betriebsbericht: Arbeitsspeicher, Auslastung, Temperatur, Laufzeit - ohne zusaetzliche Pakete,
direkt aus /proc und /sys (Linux, z. B. Raspberry Pi). Wo etwas fehlt (z. B. Windows beim Entwickeln), fehlt der Wert einfach -
nichts hier darf den Bericht stoeren.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

_cache: dict = {"t": 0.0, "v": None}
CACHE_S = 5.0
LIVE_CACHE_S = 1.5                  # Live-Anzeige der Seite: nicht oefter als alle 1,5 s neu messen
_cpu_lock = threading.Lock()
_cpu_prev: dict = {}                # letzte Messung: Zeit, CPU-Zeit des (Containers/Rechners), CPU-Zeit von BlueNexus

# Schwellen: (Warnung, Fehler)
MEM_AVAIL_PCT = (15.0, 8.0)         # verfuegbarer Speicher in % des gesamten - darunter wird es eng
SWAP_USED_PCT = (50.0, 85.0)
SWAP_ONLY_IF_MEM_BELOW = 40.0       # Auslagerung nur bewerten, wenn weniger als so viel % Speicher frei sind
TEMP_C = (75.0, 82.0)               # Raspberry Pi drosselt ab ca. 80-85 Grad
LOAD_PER_CORE = (1.5, 3.0)          # Load-Average (1 Minute) je Kern - nur ausserhalb von Containern
CPU_PCT = (90.0, 99.0)              # Auslastung der zugewiesenen Kerne in %
DISK_FREE_GB = (2.0, 0.5)


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def _meminfo() -> dict:
    out: dict = {}
    txt = _read("/proc/meminfo")
    for line in (txt or "").splitlines():
        k, _, v = line.partition(":")
        parts = v.split()
        if parts and parts[0].isdigit():
            out[k.strip()] = int(parts[0]) / 1024.0                     # kB -> MB
    return out


def _throttled() -> dict | None:
    """Raspberry Pi: Unterspannung/Drosselung (vcgencmd get_throttled) - nur wenn das Werkzeug da ist."""
    exe = shutil.which("vcgencmd")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "get_throttled"], capture_output=True, text=True, timeout=2)
        v = int(r.stdout.strip().split("=")[-1], 16)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return {"raw": v, "undervolt_now": bool(v & 0x1), "throttled_now": bool(v & 0x4), "undervolt_ever": bool(v & 0x10000), "throttled_ever": bool(v & 0x40000)}


def in_container() -> bool:
    """Laeuft BlueNexus in einem Container (LXC/Docker)? Dort zeigt /proc/loadavg den GANZEN Server, nicht den Container."""
    if os.path.exists("/.dockerenv"):
        return True
    c = _read("/run/systemd/container")
    if c and c.strip():
        return True
    env = _read("/proc/1/environ")
    return bool(env and "container=" in env)


def _cores() -> float:
    """Zugewiesene Rechenkerne: Begrenzung der Gruppe (cpu.max) oder die dem Prozess erlaubten Kerne, sonst alle."""
    cm = _read("/sys/fs/cgroup/cpu.max")
    if cm:
        q, _, p = cm.strip().partition(" ")
        try:
            if q != "max":
                return max(0.1, int(q) / int(p))
        except ValueError:
            pass
    try:
        return float(len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return float(os.cpu_count() or 1)


def _cpu_used_s() -> float | None:
    """Bisher verbrauchte CPU-Zeit (Sekunden) von diesem Container bzw. Rechner - cgroup bevorzugt (im Container genau), sonst /proc/stat."""
    cs = _read("/sys/fs/cgroup/cpu.stat")
    if cs:
        for line in cs.splitlines():
            if line.startswith("usage_usec"):
                try:
                    return int(line.split()[1]) / 1e6
                except (ValueError, IndexError):
                    break
    for p in ("/sys/fs/cgroup/cpuacct/cpuacct.usage", "/sys/fs/cgroup/cpu,cpuacct/cpuacct.usage"):
        u = _read(p)
        if u and u.strip().isdigit():
            return int(u.strip()) / 1e9
    st = _read("/proc/stat")
    if st and st.startswith("cpu "):
        try:
            f = [int(x) for x in st.splitlines()[0].split()[1:]]
            return (sum(f) - f[3] - (f[4] if len(f) > 4 else 0)) / float(os.sysconf("SC_CLK_TCK"))        # alles ausser Leerlauf (idle, iowait)
        except (ValueError, IndexError, OSError, AttributeError):
            return None
    return None


def _proc_cpu_s() -> float | None:
    """CPU-Zeit von BlueNexus selbst (Sekunden)."""
    s = _read("/proc/self/stat")
    if not s:
        return None
    try:
        f = s.rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / float(os.sysconf("SC_CLK_TCK"))
    except (ValueError, IndexError, OSError, AttributeError):
        return None


def cpu_percent() -> dict | None:
    """Auslastung seit der letzten Messung in % der zugewiesenen Kerne: {"cpu_pct", "app_cpu_pct"}. Die erste Messung wartet kurz (0,6 s)."""
    with _cpu_lock:
        now = time.time()
        used, mine = _cpu_used_s(), _proc_cpu_s()
        if used is None:
            return None
        prev = _cpu_prev.get("s")
        if prev and now - prev[0] < 0.4:
            return _cpu_prev.get("last")                        # zu schnell hintereinander: letzte Zahl weitergeben
        if not prev or now - prev[0] > 30:
            time.sleep(0.6)
            now2 = time.time()
            used2, mine2 = _cpu_used_s(), _proc_cpu_s()
            if used2 is None:
                return None
            prev, now, used, mine = (now, used, mine), now2, used2, mine2
        dt = max(0.05, now - prev[0])
        cores = _cores()
        res = {"cpu_pct": round(min(100.0, max(0.0, (used - prev[1]) / dt / cores * 100)), 1)}
        if mine is not None and prev[2] is not None:
            res["app_cpu_pct"] = round(min(100.0, max(0.0, (mine - prev[2]) / dt / cores * 100)), 1)
        _cpu_prev["s"] = (now, used, mine)
        _cpu_prev["last"] = res
        return res


def snapshot(live: bool = False) -> dict | None:
    """Aktueller Zustand der Hardware oder None, wenn das System keine /proc-Werte liefert. live=True: fuer die Live-Anzeige (kuerzerer Zwischenspeicher)."""
    now = time.time()
    if _cache["v"] is not None and now - _cache["t"] < (LIVE_CACHE_S if live else CACHE_S):
        return _cache["v"]
    mi = _meminfo()
    if not mi.get("MemTotal"):
        return None
    total, avail = mi["MemTotal"], mi.get("MemAvailable", mi.get("MemFree", 0.0))
    swap_t, swap_f = mi.get("SwapTotal", 0.0), mi.get("SwapFree", 0.0)
    v: dict = {"mem_total_mb": round(total), "mem_avail_mb": round(avail), "mem_avail_pct": round(avail / total * 100, 1),
               "swap_total_mb": round(swap_t), "swap_used_mb": round(swap_t - swap_f), "swap_used_pct": round((swap_t - swap_f) / swap_t * 100, 1) if swap_t else 0.0}
    cores = _cores()
    v["cores"] = int(cores) if cores == int(cores) else round(cores, 1)
    v["container"] = in_container()
    cp = cpu_percent()
    if cp:
        v.update(cp)
    la = _read("/proc/loadavg")
    if la:
        try:
            l1, l5, l15 = (float(x) for x in la.split()[:3])
            v.update({"load1": l1, "load5": l5, "load15": l15, "load_per_core": round(l1 / cores, 2)})
        except ValueError:
            pass
    up = _read("/proc/uptime")
    if up:
        try:
            v["uptime_s"] = int(float(up.split()[0]))
        except ValueError:
            pass
    t = _read("/sys/class/thermal/thermal_zone0/temp")
    if t:
        try:
            v["temp_c"] = round(int(t.strip()) / 1000.0, 1)
        except ValueError:
            pass
    st = _read("/proc/self/status") or ""
    for line in st.splitlines():
        if line.startswith("VmRSS:"):
            try:
                v["app_rss_mb"] = round(int(line.split()[1]) / 1024.0)       # Speicher, den BlueNexus selbst belegt
            except (ValueError, IndexError):
                pass
    model = _read("/proc/device-tree/model")
    if model:
        v["model"] = model.strip("\x00\n ")
    th = _throttled()
    if th:
        v["power"] = th
    try:
        v["disk_free_gb"] = round(shutil.disk_usage(os.path.dirname(os.path.abspath(__file__))).free / 1e9, 1)
    except OSError:
        pass
    _cache["t"], _cache["v"] = now, v
    return v


def fmt_uptime(s) -> str:
    try:
        s = int(s)
    except (TypeError, ValueError):
        return "–"
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    return (f"{d} T " if d else "") + f"{h} h {r // 60} min"


def judge(v: dict | None) -> tuple[str, str]:
    """(Status ok/warn/fail, Klartext) aus einem Snapshot."""
    if not v:
        return "info", "keine Messwerte (kein Linux-System)"
    status, notes = "ok", []

    def bump(level: str) -> None:
        nonlocal status
        if level == "fail" or (level == "warn" and status == "ok"):
            status = level

    if v["mem_avail_pct"] < MEM_AVAIL_PCT[1]:
        bump("fail"); notes.append(f"Arbeitsspeicher sehr knapp ({v['mem_avail_mb']} MB frei)")
    elif v["mem_avail_pct"] < MEM_AVAIL_PCT[0]:
        bump("warn"); notes.append(f"Arbeitsspeicher wird knapp ({v['mem_avail_mb']} MB frei)")
    tight = v["mem_avail_pct"] < SWAP_ONLY_IF_MEM_BELOW             # viel Auslagerung bei reichlich freiem Speicher ist harmlos (alte, ungenutzte Seiten) - nur zusammen mit knappem Speicher ein Problem
    if tight and v["swap_total_mb"] and v["swap_used_pct"] >= SWAP_USED_PCT[1]:
        bump("fail"); notes.append(f"Auslagerung fast voll ({v['swap_used_pct']:.0f} %)")
    elif tight and v["swap_total_mb"] and v["swap_used_pct"] >= SWAP_USED_PCT[0]:
        bump("warn"); notes.append(f"Auslagerung stark genutzt ({v['swap_used_pct']:.0f} %)")
    tc = v.get("temp_c")
    if tc is not None and tc >= TEMP_C[1]:
        bump("fail"); notes.append(f"Prozessor sehr heiß ({tc:.0f} °C)")
    elif tc is not None and tc >= TEMP_C[0]:
        bump("warn"); notes.append(f"Prozessor warm ({tc:.0f} °C)")
    cpu = v.get("cpu_pct")
    if cpu is not None and cpu >= CPU_PCT[1]:
        bump("fail"); notes.append(f"Prozessor am Limit ({cpu:.0f} % ausgelastet)")
    elif cpu is not None and cpu >= CPU_PCT[0]:
        bump("warn"); notes.append(f"Prozessor stark ausgelastet ({cpu:.0f} %)")
    lp = None if v.get("container") else v.get("load_per_core")          # im Container zeigt die Last den ganzen Server - dort zaehlt nur die eigene Auslastung
    if lp is not None and lp >= LOAD_PER_CORE[1]:
        bump("fail"); notes.append(f"Prozessor überlastet (Last {v['load1']:.1f} bei {v['cores']} Kernen)")
    elif lp is not None and lp >= LOAD_PER_CORE[0]:
        bump("warn"); notes.append(f"Prozessor stark ausgelastet (Last {v['load1']:.1f} bei {v['cores']} Kernen)")
    pw = v.get("power")
    if pw and (pw["undervolt_now"] or pw["throttled_now"]):
        bump("fail"); notes.append("Unterspannung/Drosselung JETZT (Netzteil prüfen)")
    elif pw and (pw["undervolt_ever"] or pw["throttled_ever"]):
        bump("warn"); notes.append("seit dem Start gab es Unterspannung/Drosselung (Netzteil prüfen)")
    if v.get("disk_free_gb") is not None and v["disk_free_gb"] < DISK_FREE_GB[1]:
        bump("fail"); notes.append(f"Speicherplatz fast voll ({v['disk_free_gb']} GB frei)")
    elif v.get("disk_free_gb") is not None and v["disk_free_gb"] < DISK_FREE_GB[0]:
        bump("warn"); notes.append(f"Speicherplatz wird knapp ({v['disk_free_gb']} GB frei)")
    head = f"Speicher {v['mem_avail_mb']} von {v['mem_total_mb']} MB frei ({v['mem_avail_pct']:.0f} %)"
    if v["swap_total_mb"]:
        head += f" · Auslagerung {v['swap_used_mb']} MB"
    if cpu is not None:
        head += f" · Prozessor {cpu:.0f} % ({v['cores']} Kerne" + (f", BlueNexus {v['app_cpu_pct']:.0f} %" if v.get("app_cpu_pct") is not None else "") + ")"
    elif lp is not None:
        head += f" · Last {v['load1']:.2f} ({v['cores']} Kerne)"
    if tc is not None:
        head += f" · {tc:.0f} °C"
    return status, (head + (" – " + "; ".join(notes) if notes else ""))
