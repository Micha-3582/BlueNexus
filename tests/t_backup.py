"""Sicherung/Wiederherstellung: Verschluesselung, Auswahl der Dateien, Sicherheit beim Einspielen, Routen, Rechte."""
import sys, os, io, json, sqlite3, zipfile, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import backup
from auth import UserStore
webapp.opslog.log = lambda *a, **k: None


def mkdir():
    return tempfile.mkdtemp(dir=tmp)


def seed(d):
    for n, v in (("config.json", {"cerbo_host": "192.168.50.50", "owner_first_name": "Max", "tibber_token": "GEHEIM-TOKEN"}),
                 ("users.json", {"users": {"admin": {"pw_hash": "x"}, "anna": {"pw_hash": "y"}}}),
                 ("rules.json", [{"id": "r1", "name": "Licht"}]), ("history.json", {"d": 1}), ("telegram.json", {"token": "TG-GEHEIM"})):
        json.dump(v, open(os.path.join(d, n), "w", encoding="utf-8"))
    open(os.path.join(d, "secret.key"), "w").write("KEY")
    con = sqlite3.connect(os.path.join(d, "verlauf.db")); con.execute("create table t(a)"); con.execute("insert into t values (42)"); con.commit(); con.close()
    os.makedirs(os.path.join(d, "history_archive"), exist_ok=True); json.dump({"m": 1}, open(os.path.join(d, "history_archive", "2026-09.json"), "w"))
    open(os.path.join(d, "price_cache.json"), "w").write("{}")                       # Zwischenspeicher: gehoert nicht in die Sicherung
    open(os.path.join(d, "evil.py"), "w").write("print(1)")


src = mkdir(); seed(src)

# 1) Passwortpflicht, Verschluesselung
for bad in ("", "kurz"):
    try: backup.create_backup(bad, True, src); raise SystemExit("zu kurzes Passwort muss abgelehnt werden")
    except backup.BackupError: pass
blob, name = backup.create_backup("sicher-passwort", True, src)
assert name.endswith(".bnx") and blob.startswith(b"BNXB1")
assert b"GEHEIM-TOKEN" not in blob and b"TG-GEHEIM" not in blob and b"PK" not in blob[:4]
print("1) verschluesselt OK", len(blob), name)

# 2) Falsches Passwort / beschaedigt / fremde Datei
for pw, b in (("falsch-passwort", blob), ("sicher-passwort", blob[:-5] + b"xxxxx"), ("sicher-passwort", b"kein backup"), ("sicher-passwort", blob[:20])):
    try: backup.inspect_backup(b, pw); raise SystemExit("muss abgelehnt werden")
    except backup.BackupError: pass
print("2) falsches Passwort / Beschaedigung OK")

# 3) Inhalt: mit und ohne Verlaeufe
info = backup.inspect_backup(blob, "sicher-passwort")
assert info["users"] == ["admin", "anna"] and info["include_data"] and info["count"] >= 8, info
z = zipfile.ZipFile(io.BytesIO(backup._decrypt(blob, "sicher-passwort")))
names = set(z.namelist())
assert "evil.py" not in names and "price_cache.json" not in names and "history_archive/2026-09.json" in names and "verlauf.db" in names, names
b2, _ = backup.create_backup("sicher-passwort", False, src)
n2 = set(zipfile.ZipFile(io.BytesIO(backup._decrypt(b2, "sicher-passwort"))).namelist())
assert "config.json" in n2 and "history.json" not in n2 and "verlauf.db" not in n2 and "history_archive/2026-09.json" not in n2, n2
print("3) Inhalt OK")

# 4) Einspielen in einen frischen Ordner (neue Installation)
dst = mkdir()
r = backup.restore_backup(blob, "sicher-passwort", dst)
assert not r["failed"] and r["previous"] is None and r["written"] >= 8, r
assert json.load(open(os.path.join(dst, "config.json")))["tibber_token"] == "GEHEIM-TOKEN"
assert json.load(open(os.path.join(dst, "history_archive", "2026-09.json"))) == {"m": 1}
assert sqlite3.connect(os.path.join(dst, "verlauf.db")).execute("select a from t").fetchone()[0] == 42
assert not os.path.exists(os.path.join(dst, "evil.py")) and not os.path.exists(os.path.join(dst, "price_cache.json"))
# 4b) Ueberschreiben einer bestehenden Installation: vorher Rueckweg-Sicherung
json.dump({"cerbo_host": "ALT"}, open(os.path.join(dst, "config.json"), "w"))
r = backup.restore_backup(blob, "sicher-passwort", dst)
assert r["previous"] and os.path.exists(os.path.join(dst, "backups", r["previous"]))
assert json.load(open(os.path.join(dst, "config.json")))["cerbo_host"] == "192.168.50.50"
assert json.loads(zipfile.ZipFile(os.path.join(dst, "backups", r["previous"])).read("config.json"))["cerbo_host"] == "ALT"
print("4) Einspielen + Rueckweg OK")

# 5) Boesartige Sicherung: Pfade ausserhalb, nicht erlaubte Dateien, kaputtes JSON, fehlende Konten
def forged(files, manifest_files=None, manifest=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zz:
        for n, c in files.items(): zz.writestr(n, c)
        zz.writestr("manifest.json", json.dumps(manifest or {"format": 1, "files": manifest_files or list(files)}))
    return backup._encrypt(buf.getvalue(), "sicher-passwort")
victim = mkdir(); outside = os.path.join(os.path.dirname(victim), "AUSSEN.txt")
fb = forged({"config.json": "{}", "users.json": '{"users":{}}', "../AUSSEN.txt": "x", "evil.py": "x", "history_archive/../../x.json": "x", "history_archive/a b.json": "{}"})
r = backup.restore_backup(fb, "sicher-passwort", victim)
assert not os.path.exists(outside) and not os.path.exists(os.path.join(victim, "evil.py")) and r["written"] == 2, r
for files in ({"config.json": "{kaputt"}, {"rules.json": "{}"}):
    try: backup.restore_backup(forged({**files, "users.json": '{"users":{}}'} if "config.json" in files else files), "sicher-passwort", mkdir()); raise SystemExit("muss abgelehnt werden")
    except backup.BackupError: pass
try: backup.restore_backup(forged({"config.json": "{}", "users.json": "{}"}, manifest={"format": 99, "files": ["config.json", "users.json"]}), "sicher-passwort", mkdir()); raise SystemExit("neuere Version")
except backup.BackupError as e: assert "neueren" in str(e)
print("5) boesartige Sicherung OK")

# 6) Routen: Rechte, Export, Import
webapp.BASE_DIR = src
webapp.users = UserStore(os.path.join(tmp, "u_b.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("helfer", "helferpass1", permissions={"dashboard": "write", "settings_system": "write", "smarthome": "write"})
adm = webapp.app.test_client(); adm.post("/login", data={"username": "admin", "password": "adminpass1"})
hlp = webapp.app.test_client(); hlp.post("/login", data={"username": "helfer", "password": "helferpass1"})
assert hlp.post("/api/backup/export", json={"password": "sicher-passwort"}).status_code == 403, "Nicht-Admin darf nicht sichern"
assert hlp.post("/api/backup/import", data={"mode": "inspect"}).status_code == 403
assert adm.post("/api/backup/export", json={"password": "kurz"}).status_code == 400
r = adm.post("/api/backup/export", json={"password": "sicher-passwort", "include_data": True})
assert r.status_code == 200 and "attachment" in r.headers["Content-Disposition"] and r.headers["Cache-Control"] == "no-store" and r.data.startswith(b"BNXB1")
assert adm.post("/api/backup/export", json={"password": "sicher-passwort"}, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
def imp(c, data, pw, mode):
    return c.post("/api/backup/import", data={"file": (io.BytesIO(data), "x.bnx"), "password": pw, "mode": mode}, content_type="multipart/form-data")
r = imp(adm, r.data, "sicher-passwort", "inspect"); assert r.status_code == 200 and r.get_json()["users"] == ["admin", "anna"], r.get_json()
assert imp(adm, blob, "falsch", "inspect").status_code == 400
assert imp(adm, b"", "x", "inspect").status_code == 400
webapp.BASE_DIR = dst2 = mkdir()
webapp._restart_soon = lambda: True
r = imp(adm, blob, "sicher-passwort", "restore"); d = r.get_json()
assert r.status_code == 200 and d["ok"] and d["restarting"] and os.path.exists(os.path.join(dst2, "rules.json")), d
# grosse Anfragen: nur fuer das Einspielen erlaubt
big = b"x" * (5 * 1024 * 1024)
assert adm.post("/api/virtual", data=big, content_type="application/json").status_code == 413
assert imp(adm, big, "x", "inspect").status_code == 400                      # gross erlaubt, aber keine Sicherung
print("6) Routen/Rechte OK")

# 7) Frische Installation: /restore nur ohne Konto, Link auf der Startseite
fresh = webapp.app.test_client(); webapp.users = UserStore(os.path.join(tmp, "u_leer.json"))
h = fresh.get("/create-account").get_data(as_text=True); assert "/restore" in h
r = fresh.get("/restore"); assert r.status_code == 200 and "Sicherung" in r.get_data(as_text=True)
assert fresh.get("/api/backup/import").status_code in (401, 405)
webapp.users = UserStore(os.path.join(tmp, "u_b.json"))
assert fresh.get("/restore").status_code == 302 and fresh.post("/restore", data={}).status_code == 302, "mit Konto gesperrt"
print("7) Erstinstallation OK")
print("BACKUP OK")

# 8) laufende Aufzeichnung haelt verlauf.db offen (Windows): Einspielen muss trotzdem klappen
import verlauf
live = mkdir(); verlauf.DB_PATH = os.path.join(live, "verlauf.db"); verlauf.close(); verlauf._db().execute("create table if not exists zz(a)")
r = backup.restore_backup(blob, "sicher-passwort", live)
assert not r["failed"], r
verlauf.close(); assert sqlite3.connect(os.path.join(live, "verlauf.db")).execute("select a from t").fetchone()[0] == 42
print("8) offene Datenbank OK")
