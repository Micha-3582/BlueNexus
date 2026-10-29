"""UV-Index im Wetter: Open-Meteo-Felder werden angefragt und uebernommen; ohne Werte (Demo/aeltere Antwort) bleibt alles wie bisher."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ps_common
webapp, store, cfg, tmp = ps_common.setup(sys.argv[1])
import weather
def raw(with_uv=True, cur_uv=True):
    times = [f"2026-10-27T{h:02d}:00" for h in range(24)]
    cur = {"time": "2026-10-27T10:15", "temperature_2m": 12.0, "apparent_temperature": 10.0, "relative_humidity_2m": 80, "is_day": 1, "precipitation": 0.0, "weather_code": 1,
           "cloud_cover": 20, "wind_speed_10m": 10, "wind_direction_10m": 200}
    hr = {"time": times, "temperature_2m": [10.0] * 24, "precipitation_probability": [0] * 24, "precipitation": [0] * 24, "weather_code": [1] * 24, "cloud_cover": [10] * 24, "wind_speed_10m": [5] * 24}
    dy = {"time": ["2026-10-27", "2026-10-28"], "weather_code": [1, 2], "temperature_2m_max": [14, 13], "temperature_2m_min": [7, 6], "precipitation_sum": [0, 0], "precipitation_probability_max": [0, 0],
          "wind_speed_10m_max": [12, 11], "sunrise": ["2026-10-27T07:18", "2026-10-28T07:20"], "sunset": ["2026-10-27T17:16", "2026-10-28T17:14"], "sunshine_duration": [20000, 18000]}
    if with_uv:
        hr["uv_index"] = [0.0] * 6 + [0.2, 0.9, 1.6, 2.4, 2.8, 3.1, 2.2, 1.0, 0.3] + [0.0] * 9
        dy["uv_index_max"] = [3.14, 0.0]
        if cur_uv: cur["uv_index"] = 2.9
    return {"current": cur, "hourly": hr, "daily": dy}
d = weather._parse(raw(), "Ort")
assert d["current"]["uv"] == 2.9 and d["daily"][0]["uv"] == 3.1 and d["daily"][1]["uv"] == 0.0 and d["hourly"][0]["uv"] == 2.8 and d["hourly"][1]["uv"] == 3.1 and all("uv" in h for h in d["hourly"]), d["current"]
d2 = weather._parse(raw(cur_uv=False), "Ort"); assert d2["current"]["uv"] == 2.8                         # kein aktueller Wert: UV der laufenden Stunde (10 Uhr)
d3 = weather._parse(raw(with_uv=False), "Ort"); assert d3["current"]["uv"] is None and d3["daily"][0]["uv"] is None and d3["hourly"][3]["uv"] is None   # Demo/aelterer Stand: kein UV, nichts kaputt
assert weather._uv("x") is None and weather._uv(-1) == 0.0 and weather._uv(5.56) == 5.6 and weather._uv(None) is None
# Anfrage enthaelt die UV-Felder
import requests
seen = {}
class R:
    def raise_for_status(self): pass
    def json(self): return raw()
def fake_get(url, params=None, timeout=None, **kw): seen.update(params or {}); return R()
weather.requests.get = fake_get
weather.get_location = lambda: {"configured": True, "lat": 51.0, "lon": 6.0, "name": "Ort"}
weather._cache.update(key=None, until=0, data=None)
out = weather.forecast(force=True); assert out["current"]["uv"] == 2.9
assert "uv_index" in seen["current"].split(",") and "uv_index" in seen["hourly"].split(",") and "uv_index_max" in seen["daily"].split(","), seen
print("UV OK")
