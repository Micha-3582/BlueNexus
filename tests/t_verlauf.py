"""Verlaufsgraphen: Speicher (Rohwerte + Minuten-Zusammenfassung), Abfrage mit Luecken/Buckets, Katalog, Aufzeichnung, Endpunkte, Rechte."""
import sys, os, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import verlauf, shelly, homematic
verlauf.close()
verlauf.DB_PATH = os.path.join(tmp, "v_test.db"); verlauf.SERIES_PATH = os.path.join(tmp, "v_series.json"); verlauf.CHARTS_PATH = os.path.join(tmp, "v_charts.json")
for p in (verlauf.DB_PATH, verlauf.DB_PATH + "-wal", verlauf.DB_PATH + "-shm", verlauf.SERIES_PATH, verlauf.CHARTS_PATH):
    if os.path.exists(p):
        os.remove(p)
shelly.DEVICES_PATH = os.path.join(tmp, "dev_v.json"); homematic.SENSORS_PATH = os.path.join(tmp, "sens_v.json")
for p in (shelly.DEVICES_PATH, homematic.SENSORS_PATH):
    if os.path.exists(p):
        os.remove(p)

# 1) Speichern + Minuten-Zusammenfassung + Abfrage (roh)
now = int(time.time()) // 60 * 60
rows = [("s1", now - 600 + i * 10, 100.0 + (i % 6) * 10) for i in range(60)]                 # 10 Minuten, alle 10 s
assert verlauf.add_samples(rows) == 60
assert verlauf.add_samples([("s1", now, None), ("s1", now + 1, float("nan"))]) == 0
q = verlauf.query({"s1": {"label": "Netz", "unit": "W", "interval_s": 10}}, now - 600, now, 1500)["s1"]
assert q["source"] == "raw" and q["bucket_s"] == 10 and len(q["points"]) == 60 and q["points"][0][0] == (now - 600) * 1000, q["bucket_s"]
q = verlauf.query({"s1": {"label": "Netz", "unit": "W", "interval_s": 10}}, now - 600, now, 100)["s1"]
assert q["bucket_s"] == 10 and len(q["points"]) == 60                                          # 100 Punkte erlaubt, nur 60 vorhanden
q = verlauf.query({"s1": {"interval_s": 10}}, now - 600, now, 100)["s1"]
big = verlauf.query({"s1": {"interval_s": 10}}, now - 3600, now, 100)["s1"]                    # 1 h / 100 Punkte -> 36 s Buckets
assert big["bucket_s"] == 36 and all(p[2] <= p[1] <= p[3] for p in big["points"] if p[1] is not None), big["bucket_s"]
roll = verlauf._db().execute("SELECT SUM(n), MIN(vmin), MAX(vmax) FROM rollup WHERE series='s1'").fetchone()
assert roll == (60, 100.0, 150.0), roll
print("1) Speichern/Abfrage OK")

# 2) Luecken werden als None-Punkt markiert; Spitzen bleiben in Min/Max sichtbar
verlauf.add_samples([("g", now - 1000, 5.0), ("g", now - 990, 6.0), ("g", now - 200, 7.0), ("g", now - 190, 2000.0)])
g = verlauf.query({"g": {"interval_s": 10}}, now - 1100, now, 1500)["g"]["points"]
assert [p[1] for p in g] == [5.0, 6.0, None, 7.0, 2000.0], g
agg = verlauf.query({"g": {"interval_s": 10}}, now - 1100, now, 100)["g"]
assert max(p[3] for p in agg["points"] if p[3] is not None) == 2000.0
print("2) Luecken/Spitzen OK")

# 3) lange Zeitraeume aus der Minuten-Zusammenfassung; Aufraeumen
old = now - 20 * 86400
verlauf.add_samples([("o", old + i * 10, 50.0) for i in range(30)])                            # 20 Tage alt
n_raw, n_roll = verlauf.prune(time.time())
assert n_raw >= 30 and n_roll == 0, (n_raw, n_roll)                                          # Rohwerte weg, Minutenwerte bleiben
o = verlauf.query({"o": {"interval_s": 10}}, old - 600, old + 3600, 1500)["o"]
assert o["source"] == "rollup" and o["bucket_s"] % 60 == 0 and len(o["points"]) >= 5 and o["points"][0][1] == 50.0, o
print("3) Rollup/Prune OK")

# 4) Katalog, Reihen, Diagramme
shelly._save([{"id": "d1", "kind": "shelly", "name": "Heizlüfter", "ip": "1.2.3.4", "mac": "A", "gen": 1, "channel": 0, "model": "m", "icon": "💡", "show": False},
              {"id": "d2", "kind": "wled", "name": "Lampe", "ip": "1.2.3.5", "mac": "B", "gen": 0, "channel": 0, "model": "w", "icon": "💡", "show": False},
              {"id": "d3", "kind": "homematic", "name": "Boiler", "address": "OEQ1:1", "interface": "BidCos-RF", "datapoint": "STATE", "power_addr": "OEQ1:2", "gen": 0, "channel": 1, "model": "x", "icon": "💡"}])
homematic._save_sensors([{"id": "hmS-1", "kind": "temperature", "name": "Bad", "address": "A:1", "interface": "BidCos-RF", "datapoint": "T", "unit": "°C", "binary": False, "model": "m", "room": ""},
                         {"id": "hmS-2", "kind": "contact", "name": "Fenster", "address": "A:2", "interface": "BidCos-RF", "datapoint": "S", "unit": "", "binary": True, "model": "m", "room": ""}])
ids = {c["id"] for c in verlauf.catalog()}
assert {"energy:grid_w", "energy:soc", "device_power:d1", "device_state:d1", "device_state:d2", "device_power:d3", "sensor:hmS-1", "sensor:hmS-2"} <= ids, ids
assert "device_power:d2" not in ids                                                              # WLED hat keine Leistung
s = verlauf.add_series("device_power:d1", None, " Heizlüfter Leistung ")
assert s["interval_s"] == 10 and s["label"] == "Heizlüfter Leistung" and s["unit"] == "W", s
assert verlauf.add_series("sensor:hmS-1")["interval_s"] == 60 and verlauf.add_series("sensor:hmS-2", 30)["binary"] is True
for bad, kw in (("device_power:d1", {}), ("gibts:nicht", {}), ("energy:soc", {"interval_s": 7})):
    try:
        verlauf.add_series(bad, kw.get("interval_s")); raise SystemExit("sollte scheitern %r" % bad)
    except verlauf.VerlaufError:
        pass
charts = verlauf.save_charts([{"id": "c1", "title": " Verbrauch ", "series": ["device_power:d1", "nix", "sensor:hmS-1"]}, {"id": "c1", "title": "doppelt", "series": []}])
assert charts == [{"id": "c1", "title": "Verbrauch", "series": ["device_power:d1", "sensor:hmS-1"], "colors": {}, "dashboard": False, "kind": "line"}], charts
ch2 = verlauf.save_charts([{"id": "c9", "title": "F", "series": ["device_power:d1", "sensor:hmS-1"], "colors": {"device_power:d1": "#FF8800", "sensor:hmS-1": "rot", "nix": "#123456"}}])
assert ch2[0]["colors"] == {"device_power:d1": "#ff8800"}, ch2
assert verlauf.save_charts([{"id": "c9", "title": "F", "series": ["device_power:d1"]}])[0]["colors"] == {}
verlauf.save_charts(charts)
assert [verlauf.save_charts([{"id": "k", "title": "K", "series": [], "kind": k}])[0]["kind"] for k in ("line", "area", "bar", "step", "points", "stackarea", "stackbar", "pie", None)] == ["line", "area", "bar", "step", "points", "stackarea", "stackbar", "line", "line"]
verlauf.save_charts(charts)
assert verlauf.save_charts([{"id": "c8", "title": "D", "series": ["device_power:d1"], "dashboard": True}])[0]["dashboard"] is True
assert verlauf.save_charts([{"id": "c8", "title": "D", "series": ["device_power:d1"]}])[0]["dashboard"] is False
verlauf.save_charts(charts)
assert verlauf.remove_series("sensor:hmS-1") and verlauf.load_charts()[0]["series"] == ["device_power:d1"]
verlauf.add_samples([("sensor:hmS-1", now - 60, 21.5)])
assert verlauf.query({"sensor:hmS-1": {"interval_s": 60}}, now - 300, now)["sensor:hmS-1"]["points"][0][1] == 21.5                  # Werte bleiben nach dem Entfernen
assert verlauf.add_series("sensor:hmS-1")["id"] == "sensor:hmS-1"                                                                   # und schliessen beim Neuanlegen wieder an
print("4) Katalog/Reihen/Diagramme OK")

# 5) Aufzeichnung: faellige Reihen, eigene Abtastzeit, Quellen
live = {"d1": {"id": "d1", "online": True, "on": True, "power": 1750.0}}
shelly.list_with_status = lambda only_shown=False, ids=None, live_=True: [live[i] for i in (ids or []) if i in live]
homematic.read_values = lambda sens: {s["id"]: (21.0 if s["id"] == "hmS-1" else True) for s in sens}
SYS = {"grid": {"total": -420}, "loads": {"total": 800}, "solar_total": 1900, "battery": {"power": 300, "soc": 77}}
smp = verlauf.Sampler(lambda: SYS)
verlauf.add_series("energy:grid_w", 5); verlauf.add_series("energy:soc", 300); verlauf.add_series("device_state:d1", 30)
n0 = verlauf._db().execute("SELECT COUNT(*) FROM samples").fetchone()[0]
t = time.time()
assert smp.tick(t) == 6, "alle 6 Reihen sind beim ersten Lauf faellig (grid, soc, state, power, 2 Sensoren)"
assert smp.tick(t + 3) == 0, "noch nicht faellig"
assert smp.tick(t + 6) == 1, "nur grid_w (5 s)"
assert smp.tick(t + 11) == 2, "grid_w und device_power (10 s)"
last = lambda sid: verlauf._db().execute("SELECT v FROM samples WHERE series=? ORDER BY ts DESC LIMIT 1", (sid,)).fetchone()[0]
assert last("energy:grid_w") == -420.0 and last("energy:soc") == 77.0 and last("device_state:d1") == 1.0 and last("device_power:d1") == 1750.0 and last("sensor:hmS-2") == 1.0 and last("sensor:hmS-1") == 21.0
live["d1"]["online"] = False; SYS = None
smp.tick(t + 20)                                                                              # Geraet offline, kein Energiewert: nichts Falsches schreiben
assert verlauf._db().execute("SELECT COUNT(*) FROM samples WHERE series='device_power:d1'").fetchone()[0] == 2

# Strompreis als Reihe: Katalog, Standard-Abtastzeit 60 s, Stufenlinie, Werte aus Zusatzquelle, Nachtragen der Tibber-Preise
from datetime import datetime, timedelta
cat = {c["id"]: c for c in verlauf.catalog()}
assert cat["energy:price_ct"]["unit"] == "ct/kWh" and cat["energy:price_ct"]["step"] is True and cat["energy:price_ct"]["interval"] == 60
today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
days = {(today - timedelta(days=1)).date().isoformat(): [20.0 + i / 10 for i in range(96)], (today - timedelta(days=3)).date().isoformat(): [30.0] * 96, today.date().isoformat(): [25.0] * 96}
store.price_slots = lambda day: days.get(day)
ps = verlauf.add_series("energy:price_ct")
assert ps["interval_s"] == 60 and ps["step"] is True and ps["unit"] == "ct/kWh", ps
cnt = verlauf._db().execute("SELECT COUNT(*), MIN(v), MAX(v) FROM samples WHERE series='energy:price_ct'").fetchone()
assert cnt[0] >= 96 * 2 and cnt[1] == 20.0 and cnt[2] == 30.0, cnt                     # gestern + vorgestern-3 + heute (soweit vergangen)
assert verlauf.backfill_prices() == 0, "zweiter Lauf trägt nichts doppelt nach"
yday = verlauf.query({"energy:price_ct": {"interval_s": 60}}, (today - timedelta(days=1)).timestamp(), today.timestamp() - 1, 200)["energy:price_ct"]
assert yday["points"][0][1] == 20.0 and max(p[1] for p in yday["points"] if p[1] is not None) == 29.5, yday["points"][:2]
smp2 = verlauf.Sampler(lambda: None, lambda: {"price_ct": 27.5})
assert smp2.tick(time.time() + 500) >= 1 and last("energy:price_ct") == 27.5
assert verlauf.read_sources(["energy:price_ct"], None, {})["energy:price_ct"] is None
cfg2 = store.load_config(); cfg2["tariff_mode"] = "fixed"; store.save_config(cfg2)
assert verlauf.backfill_prices() == 0
cfg2["tariff_mode"] = "dynamic"; store.save_config(cfg2)
cc = cat2 = {c["id"]: c for c in verlauf.catalog()}["energy:cost_ct_h"]
assert cc["unit"] == "ct/h" and cc["group"] == "Energie (Tarif)" and not cc.get("step") and not cc.get("interval"), cc
rs = lambda sysd, price: verlauf.read_sources(["energy:cost_ct_h"], sysd, {"price_ct": price})["energy:cost_ct_h"]
assert rs({"grid": {"total": 3000}}, 30.0) == 90.0                 # 3 kW x 30 ct/kWh = 90 ct/h
assert rs({"grid": {"total": -1500}}, 30.0) == 0.0                 # Einspeisung kostet nichts
assert rs({"grid": {"total": 500}}, None) is None and rs(None, 30.0) is None and rs({"x": 1}, 30.0) is None
assert verlauf.add_series("energy:cost_ct_h")["interval_s"] == 10
smp3 = verlauf.Sampler(lambda: {"grid": {"total": 2000}, "loads": {"total": 1}, "solar_total": 0, "battery": {"power": 0, "soc": 50}}, lambda: {"price_ct": 25.0})
smp3.tick(time.time() + 1000)
assert last("energy:cost_ct_h") == 50.0, last("energy:cost_ct_h")
print("5b) Strompreis OK")
print("5) Aufzeichnung OK")

# 6) Endpunkte und Rechte
from auth import UserStore
webapp.users = UserStore(os.path.join(tmp, "u_vl.json")); webapp.users.create("admin", "adminpass1")
webapp.users.create("max", "maxpass123", {"dashboard": "write"}); webapp.users.create("vera", "verapass123", {"dashboard": "read", "verlauf": "read"})
A = webapp.app.test_client(); A.post("/login", data={"username": "admin", "password": "adminpass1"}, follow_redirects=True)
M = webapp.app.test_client(); M.post("/login", data={"username": "max", "password": "maxpass123"}, follow_redirects=True)
V = webapp.app.test_client(); V.post("/login", data={"username": "vera", "password": "verapass123"}, follow_redirects=True)
assert A.get("/verlauf").status_code == 200 and b"Ver" in A.get("/verlauf").data
assert M.get("/verlauf").status_code in (302, 403) and M.get("/api/verlauf/series").status_code in (302, 403)
assert V.get("/verlauf").status_code == 200 and V.get("/api/verlauf/series").status_code == 200
assert V.get("/api/verlauf/catalog").status_code in (302, 403) and V.post("/api/verlauf/series", json={"source": "energy:soc"}).status_code in (302, 403)
assert V.post("/api/verlauf/charts", json={"charts": []}).status_code in (302, 403)
cat = A.get("/api/verlauf/catalog").get_json(); assert cat["intervals"] == [5, 10, 30, 60, 300] and any(x["id"] == "energy:grid_w" and x["known"] for x in cat["sources"])
r = A.get("/api/verlauf/series").get_json(); assert {s["id"] for s in r["series"]} >= {"energy:grid_w", "device_power:d1"} and r["stats"]["rollup"] > 0
tms = int(time.time() * 1000)
d = A.get(f"/api/verlauf/data?series=energy:grid_w,nix&from={tms - 3600000}&to={tms}&points=500").get_json()
assert list(d["series"]) == ["energy:grid_w"] and d["series"]["energy:grid_w"]["points"], d
assert V.get(f"/api/verlauf/data?series=energy:grid_w&from={tms - 3600000}&to={tms}").status_code == 200
assert A.get(f"/api/verlauf/data?series=energy:grid_w&from={tms}&to={tms - 5}").status_code == 400
assert A.get(f"/api/verlauf/data?series=energy:grid_w&from={tms - 500 * 86400000}&to={tms}").status_code == 400
assert A.post("/api/verlauf/series", json={"source": "energy:load_w", "interval_s": 10}).status_code == 201
assert A.post("/api/verlauf/series", json={"source": "energy:load_w"}).status_code == 400
assert A.patch("/api/verlauf/series/energy:load_w", json={"label": "Haus", "interval_s": 30}).status_code == 200 and A.patch("/api/verlauf/series/energy:load_w", json={"interval_s": 7}).status_code == 400
assert A.post("/api/verlauf/charts", json={"charts": [{"id": "x1", "title": "Haus", "series": ["energy:load_w"]}]}).get_json()["charts"][0]["series"] == ["energy:load_w"]
assert V.get("/api/verlauf/charts").get_json()["charts"][0]["title"] == "Haus"
assert A.delete("/api/verlauf/series/energy:load_w", json={"delete_data": True}).status_code == 200 and A.get("/api/verlauf/charts").get_json()["charts"][0]["series"] == []
assert A.delete("/api/verlauf/series/gibtsnicht").status_code == 404
# Zusatzquelle des Controllers: aktueller Viertelstundenpreis bzw. Festpreis
now_ = datetime.now(); store.price_slots = lambda day: [float(i) for i in range(96)] if day == now_.date().isoformat() else None
assert webapp.ctrl._verlauf_extra()["price_ct"] == float(now_.hour * 4 + now_.minute // 15) or abs(webapp.ctrl._verlauf_extra()["price_ct"] - (now_.hour * 4 + now_.minute // 15)) <= 1
cfg3 = store.load_config(); cfg3["tariff_mode"] = "fixed"; cfg3["fixed_price_ct"] = 31.5; store.save_config(cfg3)
assert webapp.ctrl._verlauf_extra()["price_ct"] == 31.5
cfg3["tariff_mode"] = "dynamic"; store.save_config(cfg3)
print("VERLAUF OK")
