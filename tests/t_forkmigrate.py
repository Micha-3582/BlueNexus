"""Annas Community-Fork (Stand db171fc) -> BlueNexus: Sicherung aus dem Fork in BlueNexus einspielen und starten."""
import os, shutil, subprocess, sys, tempfile, json, textwrap

FORK = "K:/Claude Projekte/Victron Steuerung Community/app"
BN = "K:/Claude Projekte/Victron Standalone Steuerung/app"
work = tempfile.mkdtemp(prefix="forkmig_")
ign = shutil.ignore_patterns("venv", ".venv", "__pycache__", "backups", "history_archive", "*.pyc", "*.corrupt-*", "*.tmp")
fork = os.path.join(work, "fork")
bn = os.path.join(work, "bn")
shutil.copytree(FORK, fork, ignore=ign)
print("Fork-Daten:", sorted(f for f in os.listdir(fork) if f.endswith((".json", ".jsonl", ".db", ".key")))[:40])

# 1) Fork: bekannten Admin anlegen und Sicherung mit Daten erzeugen (mit dem Code des Forks)
code = textwrap.dedent('''
    import sys, os
    sys.path.insert(0, %r); os.chdir(%r)
    import auth, backup, store
    u = auth.UserStore(os.path.join(%r, "users.json"))
    for n in list(u.usernames()): u.delete(n) if len(u.usernames()) > 1 else None
    try:
        u.create("anna", "annapass123")
    except Exception as e:
        print("create:", e)
    cfg = store.load_config()
    print("Fork cfg keys:", len(cfg))
    blob, name = backup.create_backup("sicherung123", True, %r)
    open(os.path.join(%r, "fork.hnx"), "wb").write(blob)
    print("Sicherung:", name, len(blob))
''') % (fork, fork, fork, fork, work)
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=fork)
print(r.stdout[-800:], r.stderr[-800:])
assert os.path.exists(os.path.join(work, "fork.hnx")), "Sicherung im Fork fehlgeschlagen"

# 2) BlueNexus-Code ohne Daten, Sicherung einspielen
shutil.copytree(BN, bn, ignore=shutil.ignore_patterns("venv", ".venv", "__pycache__", "backups", "history_archive", "*.pyc", "*.json", "*.jsonl", "*.db", "*.db-*", "secret.key", "initial-password.txt", "demo_media"))
code2 = textwrap.dedent('''
    import sys, os
    sys.path.insert(0, %r); os.chdir(%r)
    import backup
    blob = open(%r, "rb").read()
    info = backup.inspect_backup(blob, "sicherung123")
    print("inspect:", {k: info[k] for k in info if k in ("app", "version", "count", "users", "include_data")})
    res = backup.restore_backup(blob, "sicherung123", %r)
    print("restore:", res)
''') % (bn, bn, os.path.join(work, "fork.hnx"), bn)
r = subprocess.run([sys.executable, "-c", code2], capture_output=True, text=True, cwd=bn)
print(r.stdout[-1500:], r.stderr[-1500:])
assert "restore:" in r.stdout

# 3) BlueNexus mit den eingespielten Daten starten, anmelden, Seiten + Regeln pruefen
code3 = textwrap.dedent('''
    import sys, os
    sys.path.insert(0, %r); os.chdir(%r)
    os.environ["BLUENEXUS_SANDBOX"] = "1"
    import webapp, store, rules, camera, homematic, virtual
    app = webapp.app
    c = app.test_client()
    r = c.post("/login", data={"username": "anna", "password": "annapass123"}); print("login:", r.status_code)
    for p in ("/", "/admin", "/rules", "/smarthome", "/verlauf", "/kameras", "/report", "/watchdog", "/api/status", "/api/rules", "/api/shelly/devices", "/api/sensors", "/api/cameras", "/api/modules", "/api/version"):
        rr = c.get(p); print(p, rr.status_code)
    d = rules.load(); print("Regeln:", len(d.get("rules", [])), "Gruppen:", len(d.get("groups", [])))
    cfg = store.load_config(); print("Config-Felder:", len(cfg), "modules:", cfg.get("modules"))
    print("Geraete/Sensoren/Kameras/Virtuelle:", len(homematic.load_sensors()), len(camera.load()), len(virtual.load()) if hasattr(virtual, "load") else "-")
''') % (bn, bn)
r = subprocess.run([sys.executable, "-c", code3], capture_output=True, text=True, cwd=bn)
print(r.stdout[-3000:], r.stderr[-1500:])
print("ARBEITSORDNER:", work)
