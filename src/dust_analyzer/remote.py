"""Read CAMS Parquet data directly from GitHub Releases via DuckDB httpfs.

The update-data workflow uploads analysis.parquet and forecast.parquet daily
to the 'data-latest' release. This module reads them without any local download.
"""

import logging
from datetime import date, timedelta

import duckdb
import numpy as np

from dust_analyzer import cams

logger = logging.getLogger(__name__)

REPO = "synapticore-io/dust-analyzer"
TAG = "data-latest"
_BASE = f"https://github.com/{REPO}/releases/download/{TAG}"
ANALYSIS_URL = f"{_BASE}/analysis.parquet"
FORECAST_URL = f"{_BASE}/forecast.parquet"


def _con() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    return con


def _url_for(data_type: str) -> str:
    return FORECAST_URL if data_type == "forecast" else ANALYSIS_URL


def get_timeseries(
    lat: float,
    lon: float,
    date_from: date,
    date_to: date,
    data_type: str = "analysis",
    tolerance: float = 0.15,
) -> dict[str, dict]:
    """Read timeseries for nearest grid point from remote Parquet."""
    url = _url_for(data_type)
    con = _con()
    try:
        rows = con.execute("""
            SELECT variable, timestamp, value, lat, lon
            FROM read_parquet(?)
            WHERE level_m = 0
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
              AND timestamp >= ?
              AND timestamp < ?
            ORDER BY variable, timestamp
        """, [
            url,
            lat - tolerance, lat + tolerance,
            lon - tolerance, lon + tolerance,
            str(date_from),
            str(date_to + timedelta(days=1)),
        ]).fetchall()
    except Exception as e:
        logger.warning("Remote Parquet read failed (%s): %s", data_type, e)
        return {}
    finally:
        con.close()

    if not rows:
        return {}

    # Group by variable, pick nearest grid point
    by_var: dict[str, list] = {}
    for var, ts, val, rlat, rlon in rows:
        by_var.setdefault(var, []).append((ts, val, rlat, rlon))

    series: dict[str, dict] = {}
    for var, records in by_var.items():
        if var not in cams.VARIABLES:
            continue
        # Find nearest grid point
        unique_points = {(r[2], r[3]) for r in records}
        nearest = min(unique_points, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2)
        filtered = [(r[0], r[1]) for r in records if r[2] == nearest[0] and r[3] == nearest[1]]

        _, _, label, color = cams.VARIABLES[var]
        series[var] = {
            "time": np.array([r[0] for r in filtered], dtype="datetime64[us]"),
            "values": np.array([r[1] for r in filtered], dtype="float64"),
            "label": label,
            "color": color,
        }

    logger.info("Remote %s: %d vars, %d rows total", data_type, len(series), len(rows))
    return series


def get_map_data(
    lat: float,
    lon: float,
    radius_deg: float = 5.0,
    max_grid: int = 40,
) -> dict[str, dict]:
    """Read spatial grid from remote Parquet for map display."""
    url = ANALYSIS_URL
    con = _con()
    try:
        rows = con.execute("""
            SELECT variable, lat, lon, value
            FROM read_parquet(?)
            WHERE level_m = 0
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
              AND timestamp = (
                  SELECT MAX(timestamp) FROM read_parquet(?)
                  WHERE level_m = 0
              )
        """, [
            url,
            lat - radius_deg, lat + radius_deg,
            lon - radius_deg, lon + radius_deg,
            url,
        ]).fetchall()
    except Exception as e:
        logger.warning("Remote map read failed: %s", e)
        return {}
    finally:
        con.close()

    if not rows:
        return {}

    colorscales = {"dust": "YlOrBr", "so2": "Reds", "pm2p5": "Blues"}
    by_var: dict[str, list] = {}
    for var, rlat, rlon, val in rows:
        if var in cams.VARIABLES and np.isfinite(val):
            by_var.setdefault(var, []).append((rlat, rlon, val))

    variables: dict[str, dict] = {}
    for var, records in by_var.items():
        # Subsample if grid too dense
        step = max(1, len(records) // (max_grid * max_grid))
        sampled = records[::step]
        _, _, label, _ = cams.VARIABLES[var]
        variables[var] = {
            "label": label,
            "colorscale": colorscales.get(var, "YlOrRd"),
            "lats": [r[0] for r in sampled],
            "lons": [r[1] for r in sampled],
            "values": [r[2] for r in sampled],
        }

    return variables


def get_last_timestamp() -> str | None:
    """Get the newest timestamp in the remote analysis Parquet."""
    con = _con()
    try:
        row = con.execute(
            "SELECT MAX(timestamp) FROM read_parquet(?)", [ANALYSIS_URL]
        ).fetchone()
        return str(row[0]) if row and row[0] else None
    except Exception:
        return None
    finally:
        con.close()


def data_availability() -> dict:
    """Report what data is available in the remote release."""
    con = _con()
    result: dict = {"source": "github-release", "repo": REPO, "tag": TAG}
    try:
        for dtype, url in [("analysis", ANALYSIS_URL), ("forecast", FORECAST_URL)]:
            try:
                row = con.execute("""
                    SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
                    FROM read_parquet(?)
                """, [url]).fetchone()
                if row and row[2]:
                    result[dtype] = {
                        "earliest": str(row[0]),
                        "latest": str(row[1]),
                        "rows": row[2],
                    }
            except Exception as e:
                result[dtype] = {"error": str(e)}
    finally:
        con.close()
    return result
