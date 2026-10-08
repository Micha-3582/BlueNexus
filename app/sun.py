"""
Sonnenaufgang / Sonnenuntergang (astronomisch berechnet, ohne Internet).

Rechnet mit dem Standort aus den Wetter-Einstellungen (weather_lat / weather_lon) nach dem NOAA-Verfahren (Genauigkeit etwa eine Minute).
Aufgang/Untergang = Oberkante der Sonnenscheibe am Horizont (Zenitwinkel 90,833 Grad, mit Refraktion).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta


def _event_utc_minutes(day: date, lat: float, lon: float, rising: bool) -> float | None:
    """Minuten nach 0:00 UTC (kann ausserhalb 0..1440 liegen), None bei Polartag/-nacht."""
    n = day.timetuple().tm_yday
    gamma = 2 * math.pi / 365 * (n - 1 + (12 - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                       - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    decl = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma) - 0.006758 * math.cos(2 * gamma)
            + 0.000907 * math.sin(2 * gamma) - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    la = math.radians(lat)
    cos_h = math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl)) - math.tan(la) * math.tan(decl)
    if cos_h > 1 or cos_h < -1:
        return None
    ha = math.degrees(math.acos(cos_h))
    return 720 - 4 * (lon + (ha if rising else -ha)) - eqtime


def times(day: date, lat: float, lon: float) -> dict | None:
    """{'sunrise': Minuten seit Mitternacht (Ortszeit), 'sunset': ...} oder None (Polartag/-nacht)."""
    rise, sset = _event_utc_minutes(day, lat, lon, True), _event_utc_minutes(day, lat, lon, False)
    if rise is None or sset is None:
        return None
    noon = datetime(day.year, day.month, day.day, 12)
    off = (noon.astimezone().utcoffset() or timedelta(0)).total_seconds() / 60       # Zeitzone des Servers (Sommerzeit inklusive)
    return {"sunrise": int(round((rise + off) % 1440)), "sunset": int(round((sset + off) % 1440))}


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def for_config(cfg: dict, day: date) -> dict | None:
    """Zeiten fuer den Standort der Anlage, None ohne Standort."""
    lat, lon = cfg.get("weather_lat"), cfg.get("weather_lon")
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
        return None
    return times(day, float(lat), float(lon))
