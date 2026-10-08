"""
Update-Mechanismus über GitHub (git-basiert).
Prüft, ob im öffentlichen Repo eine neuere Version liegt, und aktualisiert per
`git pull`. Nutzerdaten (config.json, state.json, ...) bleiben unberührt, weil
sie in .gitignore stehen.
"""
import hashlib
import os
import subprocess
import sys

APP_DIR = os.path.dirname(os.path.abspath(__file__))


def _git(*args, timeout=90):
    return subprocess.run(["git", "-C", APP_DIR, *args],
                          capture_output=True, text=True, timeout=timeout)


def is_git_repo() -> bool:
    try:
        r = _git("rev-parse", "--is-inside-work-tree", timeout=10)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def current_version() -> str:
    vf = os.path.join(APP_DIR, "VERSION")
    ver = ""
    if os.path.exists(vf):
        with open(vf, encoding="utf-8") as f:
            ver = f.read().strip()
    short = ""
    if is_git_repo():
        r = _git("rev-parse", "--short", "HEAD", timeout=10)
        short = r.stdout.strip()
    if ver and short:
        return f"{ver} ({short})"
    return ver or short or "unbekannt"


def check_update() -> dict:
    """Holt den Remote-Stand und meldet, ob ein Update verfügbar ist."""
    if not is_git_repo():
        return {"git": False, "current": current_version(),
                "reason": "Keine Git-Installation – Update über GitHub nicht möglich."}
    f = _git("fetch", "--quiet")
    if f.returncode != 0:
        return {"git": True, "current": current_version(), "update_available": False,
                "reason": f"Kein Zugriff auf GitHub: {f.stderr.strip()[:200]}"}
    local = _git("rev-parse", "HEAD").stdout.strip()
    try:
        remote = _git("rev-parse", "@{u}").stdout.strip()
        behind = _git("rev-list", "--count", "HEAD..@{u}").stdout.strip()
    except Exception:                                    # noqa: BLE001
        return {"git": True, "current": current_version(), "update_available": False,
                "reason": "Kein Upstream-Branch gesetzt."}
    return {"git": True, "current": current_version(),
            "update_available": bool(local and remote and local != remote),
            "behind": int(behind or 0)}


def _requirements_hash() -> str:
    try:
        with open(os.path.join(APP_DIR, "requirements.txt"), "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _install_requirements() -> str:
    """Neue Python-Pakete nachinstallieren (nur, wenn sich requirements.txt durch das Update geaendert hat). Rueckgabe: Text fuer die Ausgabe."""
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", os.path.join(APP_DIR, "requirements.txt")],
                           capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return f"Neue Python-Pakete konnten nicht installiert werden: {e}"
    if r.returncode != 0:
        return "Neue Python-Pakete konnten nicht installiert werden:" + chr(10) + (r.stderr or r.stdout).strip()[-600:]
    return "Neue Python-Pakete installiert."


def do_update() -> dict:
    """Führt `git pull --ff-only` aus und installiert bei Bedarf neue Python-Pakete. Startet NICHT neu (das macht der Aufrufer)."""
    if not is_git_repo():
        return {"ok": False, "output": "Keine Git-Installation."}
    before = _requirements_hash()
    r = _git("pull", "--ff-only")
    out = (r.stdout + r.stderr).strip()[-2000:]
    if r.returncode == 0 and before and _requirements_hash() != before:
        out = (out + chr(10) + _install_requirements()).strip()
    return {"ok": r.returncode == 0, "output": out, "version": current_version()}
