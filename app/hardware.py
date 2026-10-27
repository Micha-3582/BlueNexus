"""
Hardware-Monitor fuer den Betriebsbericht: Arbeitsspeicher, Auslastung, Temperatur, Laufzeit - ohne zusaetzliche Pakete,
direkt aus /proc und /sys (Linux, z. B. Raspberry Pi). Wo etwas fehlt (z. B. Windows beim Entwickeln), fehlt der Wert einfach -
nichts hier darf den Bericht stoeren.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

_cache: dict = {"t": 0.0, "v": None}
CACHE_S = 5.0

# Schwellen: (Warnung, Fehler)
MEM_AVAIL_PCT = (15.0, 8.0)         # verfuegbarer Speicher in % des gesamten - darunter wird es eng
SWAP_USED_PCT = (50.0, 85.0)
TEMP_C = (75.0, 82.0)               # Raspberry Pi drosselt ab ca. 80-85 Grad
LOAD_PER_CORE = (1.5, 3.0)          # Load-Average (1 Minute) je Kern
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


def snapshot() -> dict | None:
    """Aktueller Zustand der Hardware oder None, wenn das System keine /proc-Werte liefert."""
    now = time.time()
    if _cache["v"] is not None and now - _cache["t"] < CACHE_S:
        return _cache["v"]
    mi = _meminfo()
    if not mi.get("MemTotal"):
        return None
    total, avail = mi["MemTotal"], mi.get("MemAvailable", mi.get("MemFree", 0.0))
    swap_t, swap_f = mi.get("SwapTotal", 0.0), mi.get("SwapFree", 0.0)
    v: dict = {"mem_total_mb": round(total), "mem_avail_mb": round(avail), "mem_avail_pct": round(avail / total * 100, 1),
               "swap_total_mb": round(swap_t), "swap_used_mb": round(swap_t - swap_f), "swap_used_pct": round((swap_t - swap_f) / swap_t * 100, 1) if swap_t else 0.0}
    cores = os.cpu_count() or 1
    v["cores"] = cores
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
    if v["swap_total_mb"] and v["swap_used_pct"] >= SWAP_USED_PCT[1]:
        bump("fail"); notes.append(f"Auslagerung fast voll ({v['swap_used_pct']:.0f} %)")
    elif v["swap_total_mb"] and v["swap_used_pct"] >= SWAP_USED_PCT[0]:
        bump("warn"); notes.append(f"Auslagerung stark genutzt ({v['swap_used_pct']:.0f} %)")
    tc = v.get("temp_c")
    if tc is not None and tc >= TEMP_C[1]:
        bump("fail"); notes.append(f"Prozessor sehr heiß ({tc:.0f} °C)")
    elif tc is not None and tc >= TEMP_C[0]:
        bump("warn"); notes.append(f"Prozessor warm ({tc:.0f} °C)")
    lp = v.get("load_per_core")
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
    if lp is not None:
        head += f" · Last {v['load1']:.2f} ({v['cores']} Kerne)"
    if tc is not None:
        head += f" · {tc:.0f} °C"
    return status, (head + (" – " + "; ".join(notes) if notes else ""))
