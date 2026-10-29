import os, sys
from datetime import datetime, timedelta
root = sys.argv[1]
sys.path.insert(0, root + "/app"); os.chdir(root + "/app")
import requests, store, weather

cfg = {}
store.load_config = lambda: dict(cfg)
def save(c): cfg.clear(); cfg.update(c)
store.save_config = save

now = datetime.now().replace(minute=20, second=0, microsecond=0)
def hourly_times():
    t0 = now.replace(hour=0) - timedelta(days=0)
    return [(t0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
T = hourly_times()
RAW = {"current": {"time": now.strftime("%Y-%m-%dT%H:%M"), "temperature_2m": 11.2, "apparent_temperature": 9.4, "relative_humidity_2m": 81,
                   "is_day": 1, "precipitation": 0.0, "weather_code": 3, "cloud_cover": 100, "wind_speed_10m": 14.4, "wind_direction_10m": 250},
       "hourly": {"time": T, "temperature_2m": [10 + i % 5 for i in range(48)], "precipitation_probability": [i % 100 for i in range(48)],
                  "precipitation": [0.1] * 48, "weather_code": [61 if i % 7 == 0 else 2 for i in range(48)], "cloud_cover": [50] * 48,
                  "wind_speed_10m": [12.0] * 48},
       "daily": {"time": [(now.date() + timedelta(days=i)).isoformat() for i in range(7)], "weather_code": [3, 61, 0, 1, 2, 95, 71],
                 "temperature_2m_max": [14, 15, 16, 17, 13, 12, 3], "temperature_2m_min": [8, 9, 7, 6, 5, 4, -2],
                 "precipitation_sum": [0, 4.2, 0, 0, 1, 12.5, 0.3], "precipitation_probability_max": [10, 80, 0, 5, 30, 95, 40],
                 "wind_speed_10m_max": [20, 35, 15, 10, 22, 50, 25],
                 "sunrise": [f"{(now.date() + timedelta(days=i)).isoformat()}T07:0{i}" for i in range(7)],
                 "sunset": [f"{(now.date() + timedelta(days=i)).isoformat()}T19:1{i}" for i in range(7)],
                 "sunshine_duration": [3600 * 4.5] * 6 + [None]}}
calls = []
class R:
    def __init__(self, data, code=200): self._d, self.status_code = data, code
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError("boom")
    def json(self): return self._d
def fake_get(url, params=None, timeout=None):
    calls.append((url, dict(params or {})))
    if "geocoding" in url:
        return R({"results": [{"name": "Alpen", "admin1": "Nordrhein-Westfalen", "country": "Deutschland", "latitude": 51.5926, "longitude": 6.5048},
                              {"name": "Broken"}]})
    return R(RAW)
weather.requests.get = fake_get

assert weather.forecast() == {"configured": False, "error": None}
try: weather.save_location("abc", 1); raise SystemExit("bad lat accepted")
except weather.WeatherError: pass
try: weather.save_location(91, 0); raise SystemExit("range")
except weather.WeatherError: pass
weather.save_location("51,5926", "6.5048", "Zuhause")
assert cfg["weather_lat"] == 51.5926 and cfg["weather_name"] == "Zuhause"
w = weather.forecast()
c = w["current"]
assert c["temp"] == 11.2 and c["text"] == "Bewölkt" and c["wind"] == 14 and c["wind_dir"] == "W", c
assert w["name"] == "Zuhause" and len(w["hourly"]) == 24 and w["hourly"][0]["hour"] == now.hour, (len(w["hourly"]), w["hourly"][0])
assert len(w["daily"]) == 7 and w["daily"][1]["text"] == "Leichter Regen" and w["daily"][0]["sunrise"] == "07:00" and w["daily"][0]["sun_h"] == 4.5
assert w["daily"][6]["sun_h"] is None and w["daily"][6]["tmin"] == -2
n = len(calls); weather.forecast(); assert len(calls) == n            # gepuffert
assert calls[0][1]["timezone"] == "auto" and calls[0][1]["latitude"] == 51.5926

# Fehler: alte Werte bleiben, Fehler wird gemeldet
weather.requests.get = lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("offline"))
r = weather.forecast(force=True)
assert r["current"]["temp"] == 11.2 and "nicht erreichbar" in r["error"], r
# Standortwechsel loescht den Cache; ohne alte Daten nur Fehler
weather.save_location(48.1, 11.6, "")
r = weather.forecast()
assert r["configured"] and "current" not in r and r["error"], r
# Ortssuche
weather.requests.get = fake_get
res = weather.search_places("Alpen")
assert res == [{"name": "Alpen", "region": "Nordrhein-Westfalen, Deutschland", "lat": 51.5926, "lon": 6.5048}], res
try: weather.search_places("A"); raise SystemExit("short query")
except weather.WeatherError: pass
# Standort entfernen
weather.save_location(None, None)
assert weather.get_location()["configured"] is False and "weather_lat" not in cfg
print("WEATHER OK", root.split("/")[-1])
