"""Alle Tests (t_*.py) nacheinander ausfuehren und das Ergebnis zusammenfassen.

Aufruf (aus dem Projektordner):
    python tests/run_all.py                  alle Tests
    python tests/run_all.py rules share      nur Tests, deren Name einen der Begriffe enthaelt
    python tests/run_all.py --save           Ergebnis als Referenz speichern (tests/baseline.json)
    python tests/run_all.py --compare        mit der Referenz vergleichen: meldet nur Abweichungen

Jeder Test laeuft in einem eigenen Prozess mit Wegwerf-Ordner (siehe ps_common.py) und fasst die echten Daten
im Ordner app/ nicht an. Ein Test gilt als bestanden, wenn er mit Exit-Code 0 endet.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(HERE, "baseline.json")
TIMEOUT = 240


def clean_copy() -> str:
    """Sauberer Code-Stand (nur von Git verfolgte Dateien aus app/, ohne Daten, Schluessel, Passwoerter) in einem Wegwerf-Ordner:
    so liest kein Test echte Einstellungen und schreibt keinen Test in die echten Daten."""
    tmp = tempfile.mkdtemp(prefix="bn-tests-")
    files = subprocess.run(["git", "ls-files", "app"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout.splitlines()
    for f in files:
        dst = os.path.join(tmp, f)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, f), dst)
    return tmp


def run_one(name: str, root: str) -> dict:
    t0 = time.time()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run([sys.executable, os.path.join(HERE, name), root.replace("\\", "/")], cwd=HERE, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT)
        out = (p.stdout + p.stderr).strip().splitlines()
        return {"ok": p.returncode == 0, "code": p.returncode, "sek": round(time.time() - t0, 1), "letzte": out[-1][:200] if out else ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": "timeout", "sek": TIMEOUT, "letzte": "Zeitüberschreitung"}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    names = sorted(f for f in os.listdir(HERE) if f.startswith("t_") and f.endswith(".py"))
    if args:
        names = [n for n in names if any(a in n for a in args)]
    res: dict[str, dict] = {}
    root = clean_copy()
    for i, n in enumerate(names, 1):
        res[n] = run_one(n, root)
        print(f"[{i:3d}/{len(names)}] {'OK    ' if res[n]['ok'] else 'FEHLER'} {n}  ({res[n]['sek']} s)", flush=True)
        if not res[n]["ok"]:
            print("          " + res[n]["letzte"], flush=True)
    shutil.rmtree(root, ignore_errors=True)
    bad = [n for n, r in res.items() if not r["ok"]]
    print(f"\n{len(names) - len(bad)} von {len(names)} Tests bestanden.")
    if "--save" in sys.argv:
        json.dump({n: r["ok"] for n, r in res.items()}, open(BASELINE, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("Referenz gespeichert:", BASELINE)
    if "--compare" in sys.argv:
        base = json.load(open(BASELINE, encoding="utf-8"))
        diff = [n for n in res if base.get(n) is not None and base[n] != res[n]["ok"]]
        print("Abweichung von der Referenz:", ", ".join(diff) if diff else "keine")
        return 1 if diff else 0
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
