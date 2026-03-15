"""
UBA (Umweltbundesamt) Air Data API v3 — real-time station measurements.

Base URL: https://umweltbundesamt.api.proxy.bund.de/api/air_data/v3
Auth:     None required (public API)
Rate:     ~100 requests/minute

Provides hourly ground-truth measurements from ~500 German stations.
Used to close the ~48h gap between CAMS analysis data and "now".
"""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://umweltbundesamt.api.proxy.bund.de/api/air_data/v3"
REQUEST_TIMEOUT = 30

# UBA component IDs → (variable_key, label, color)
COMPONENTS: dict[int, tuple[str, str, str]] = {
    1: ("pm10",  "PM10 [µg/m³]",  "#9b7ed4"),
    5: ("pm2p5", "PM2.5 [µg/m³]", "#7eb8d4"),
    2: ("so2",   "SO₂ [µg/m³]",   "#e05252"),
    3: ("o3",    "O₃ [µg/m³]",    "#6ecf72"),
    4: ("no2",   "NO₂ [µg/m³]",   "#d4a07e"),
}

# Reverse: variable key → component ID
VAR_TO_COMPONENT: dict[str, int] = {v[0]: k for k, v in COMPONENTS.items()}

SCOPE_HOURLY = 2


@dataclass
class Station:
    id: int
    code: str
    name: str
    lat: float
    lon: float
    city: str
    state: str
    active_from: str
    active_to: str


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def fetch_stations() -> list[Station]:
    """Fetch all UBA stations with coordinates."""
    url = f"{BASE_URL}/stations/json"
    params = {"lang": "de", "index": "id"}
    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    stations: list[Station] = []
    raw = data.get("data", {})

    for station_id, values in raw.items():
        # values: [id, code, name, city, synonym, active_from, active_to,
        #          lon, lat, network_id, state_id, setting_id, ...]
        if not isinstance(values, (list, tuple)) or len(values) < 9:
            continue
        try:
            stations.append(Station(
                id=int(station_id),
                code=str(values[1]),
                name=str(values[2]),
                city=str(values[3]) if values[3] else "",
                lat=float(values[8]),
                lon=float(values[7]),
                state=str(values[10]) if len(values) > 10 and values[10] else "",
                active_from=str(values[5]) if values[5] else "",
                active_to=str(values[6]) if values[6] else "",
            ))
        except (ValueError, IndexError, TypeError) as e:
            logger.debug("Skipping station %s: %s", station_id, e)

    logger.info("Fetched %d UBA stations.", len(stations))
    return stations


def nearest_stations(
    lat: float,
    lon: float,
    stations: list[Station] | None = None,
    max_distance_km: float = 50.0,
    limit: int = 3,
) -> list[tuple[Station, float]]:
    """Find nearest stations to a location. Returns [(station, distance_km), ...]."""
    if stations is None:
        stations = fetch_stations()

    with_dist = [(s, _haversine_km(lat, lon, s.lat, s.lon)) for s in stations]
    with_dist.sort(key=lambda x: x[1])
    return [(s, d) for s, d in with_dist[:limit] if d <= max_distance_km]


def fetch_measurements(
    station_id: int,
    component_ids: list[int] | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, dict]:
    """
    Fetch hourly measurements from a UBA station.

    Returns: variable_key → {time: list[str], values: list[float], label, color}
    """
    if date_from is None:
        date_from = date.today() - timedelta(days=3)
    if date_to is None:
        date_to = date.today()
    if component_ids is None:
        component_ids = list(COMPONENTS.keys())

    url = f"{BASE_URL}/measures/json"
    params = {
        "date_from": date_from.strftime("%Y-%m-%d"),
        "date_to": date_to.strftime("%Y-%m-%d"),
        "time_from": 1,
        "time_to": 24,
        "station": str(station_id),
        "component": ",".join(str(c) for c in component_ids),
        "scope": str(SCOPE_HOURLY),
        "lang": "de",
        "index": "id",
    }

    resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    raw = resp.json()
    raw_data = raw.get("data", {})

    series: dict[str, dict] = {}

    for compound_key, time_entries in raw_data.items():
        # compound_key: "station_id component_id scope_id"
        parts = compound_key.strip().split()
        if len(parts) < 2:
            continue
        try:
            comp_id = int(parts[1])
        except ValueError:
            continue
        if comp_id not in COMPONENTS:
            continue

        var_key, label, color = COMPONENTS[comp_id]
        timestamps: list[str] = []
        values: list[float] = []

        for _ts_key, entry in sorted(time_entries.items()):
            if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                continue
            date_str = entry[0] if isinstance(entry[0], str) else str(entry[0])
            val = entry[1]
            if val is None:
                continue
            try:
                values.append(float(val))
                timestamps.append(date_str)
            except (ValueError, TypeError):
                continue

        if timestamps:
            series[var_key] = {
                "time": timestamps,
                "values": values,
                "label": label,
                "color": color,
            }

    logger.info(
        "UBA station %d: %d variables, %d data points.",
        station_id, len(series), sum(len(s["values"]) for s in series.values()),
    )
    return series


def fetch_for_location(
    lat: float,
    lon: float,
    days: int = 3,
    variables: list[str] | None = None,
) -> dict:
    """
    High-level: find nearest station and fetch measurements.

    Returns:
        {
            "station": {"id", "name", "code", "city", "lat", "lon", "distance_km"} | None,
            "series": {variable_key: {time, values, label, color}},
        }
    """
    nearby = nearest_stations(lat, lon, limit=1)
    if not nearby:
        logger.warning("No UBA station within 50 km of (%.2f, %.2f).", lat, lon)
        return {"station": None, "series": {}}

    station, dist = nearby[0]

    component_ids = None
    if variables:
        component_ids = [VAR_TO_COMPONENT[v] for v in variables if v in VAR_TO_COMPONENT]

    date_to = date.today()
    date_from = date_to - timedelta(days=days)

    series = fetch_measurements(
        station_id=station.id,
        component_ids=component_ids,
        date_from=date_from,
        date_to=date_to,
    )

    return {
        "station": {
            "id": station.id,
            "code": station.code,
            "name": station.name,
            "city": station.city,
            "lat": station.lat,
            "lon": station.lon,
            "distance_km": round(dist, 1),
        },
        "series": series,
    }
