"""
DuckDB cache for CAMS time series and UBA station measurements.
Prevents repeated API downloads for identical coordinates and time ranges.
"""

from datetime import date, datetime, timezone
from pathlib import Path
import logging

import duckdb
import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)

DB_FILE = Path("dust_cache.duckdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS timeseries (
    key       TEXT    NOT NULL,
    variable  TEXT    NOT NULL,
    lat       DOUBLE  NOT NULL,
    lon       DOUBLE  NOT NULL,
    date_from DATE    NOT NULL,
    date_to   DATE    NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    value     DOUBLE,
    PRIMARY KEY (key, variable, timestamp)
)
"""

MEASUREMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    timestamp    TIMESTAMP,
    latitude     DOUBLE,
    longitude    DOUBLE,
    level_m      INTEGER,
    variable     TEXT,
    value        DOUBLE,
    unit         TEXT,
    model        TEXT,
    request_hash TEXT
);

CREATE INDEX IF NOT EXISTS idx_ts_level
ON measurements (timestamp, level_m, variable);
"""

STATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS station_measurements (
    station_id   INTEGER   NOT NULL,
    station_name TEXT,
    lat          DOUBLE    NOT NULL,
    lon          DOUBLE    NOT NULL,
    variable     TEXT      NOT NULL,
    timestamp    TIMESTAMP NOT NULL,
    value        DOUBLE,
    unit         TEXT      DEFAULT 'µg/m³',
    source       TEXT      DEFAULT 'uba'
);

CREATE INDEX IF NOT EXISTS idx_station_var_ts
ON station_measurements (station_id, variable, timestamp);
"""


def _cache_key(lat: float, lon: float, date_from: date, date_to: date, data_type: str = "analysis") -> str:
    suffix = "" if data_type == "analysis" else f"_{data_type}"
    return f"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}{suffix}"


def _to_py_datetime(ts: np.datetime64) -> datetime:
    """numpy datetime64[ns] → Python datetime (UTC)."""
    unix_ns = int(ts.astype("int64"))
    return datetime.fromtimestamp(unix_ns / 1e9, tz=timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# CAMS timeseries cache
# ---------------------------------------------------------------------------

def get(
    lat: float, lon: float, date_from: date, date_to: date, data_type: str = "analysis",
) -> dict[str, pd.DataFrame] | None:
    """Return cached time series or None if not present."""
    if not DB_FILE.exists():
        return None

    key = _cache_key(lat, lon, date_from, date_to, data_type)
    con = duckdb.connect(str(DB_FILE))
    con.execute(SCHEMA)

    result = con.execute(
        "SELECT variable, timestamp, value FROM timeseries WHERE key = ? ORDER BY variable, timestamp",
        [key],
    ).fetchdf()
    con.close()

    if result.empty:
        return None

    logger.info("Cache hit (%s) — no API download needed.", data_type)
    return {
        var: grp[["timestamp", "value"]].rename(columns={"timestamp": "time"})
        for var, grp in result.groupby("variable")
    }


def put(
    lat: float,
    lon: float,
    date_from: date,
    date_to: date,
    series: dict[str, dict],
    data_type: str = "analysis",
) -> None:
    """Store CAMS time series in cache."""
    key = _cache_key(lat, lon, date_from, date_to, data_type)
    con = duckdb.connect(str(DB_FILE))
    con.execute(SCHEMA)

    for variable, data in series.items():
        rows = [
            (key, variable, lat, lon, date_from, date_to, _to_py_datetime(ts), float(val))
            for ts, val in zip(data["time"], data["values"])
        ]
        con.executemany(
            "INSERT OR REPLACE INTO timeseries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )

    con.close()
    logger.info("Cached %d data points (%s).", sum(len(d["time"]) for d in series.values()), data_type)


# ---------------------------------------------------------------------------
# CAMS volumetric measurements
# ---------------------------------------------------------------------------

def put_measurements(
    rows: list[tuple],
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    date_from: date,
    date_to: date,
) -> None:
    """Store volumetric measurements. rows: (timestamp, lat, lon, level_m, var, val, unit, model)"""
    if not rows:
        return

    request_hash = f"{lat_min:.2f}_{lat_max:.2f}_{lon_min:.2f}_{lon_max:.2f}_{date_from}_{date_to}"

    con = duckdb.connect(str(DB_FILE))
    con.execute(MEASUREMENTS_SCHEMA)

    with con:
        con.executemany(
            """INSERT INTO measurements
            (timestamp, latitude, longitude, level_m, variable, value, unit, model, request_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (_to_py_datetime(ts), lat, lon, level_m, var, val, unit, model, request_hash)
                for ts, lat, lon, level_m, var, val, unit, model in rows
            ],
        )
    con.close()


# ---------------------------------------------------------------------------
# UBA station measurements
# ---------------------------------------------------------------------------

def put_station_data(
    station_id: int,
    station_name: str,
    lat: float,
    lon: float,
    series: dict[str, dict],
) -> None:
    """Cache UBA station measurements. series: {variable: {time: [...], values: [...]}}."""
    con = duckdb.connect(str(DB_FILE))
    con.execute(STATION_SCHEMA)

    total = 0
    with con:
        for variable, data in series.items():
            rows = [
                (station_id, station_name, lat, lon, variable, ts, val, "µg/m³", "uba")
                for ts, val in zip(data["time"], data["values"])
            ]
            if rows:
                con.executemany(
                    """INSERT OR REPLACE INTO station_measurements
                    (station_id, station_name, lat, lon, variable, timestamp, value, unit, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                total += len(rows)
    con.close()
    logger.info("Cached %d station measurements for %s (%d).", total, station_name, station_id)


def get_station_data(
    station_id: int,
    variable: str,
    date_from: date,
    date_to: date,
) -> list[dict] | None:
    """Read cached station measurements. Returns [{timestamp, value}] or None."""
    if not DB_FILE.exists():
        return None

    con = duckdb.connect(str(DB_FILE), read_only=True)
    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "station_measurements" not in tables:
            return None

        rows = con.execute(
            """SELECT timestamp, value FROM station_measurements
            WHERE station_id = ? AND variable = ?
              AND timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp""",
            [station_id, variable, str(date_from), str(date_to)],
        ).fetchall()

        if not rows:
            return None
        return [{"timestamp": str(ts), "value": float(val)} for ts, val in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Data availability diagnostics
# ---------------------------------------------------------------------------

def data_availability() -> dict:
    """Latest timestamps per data source. Useful for diagnosing data gaps."""
    if not DB_FILE.exists():
        return {"error": "No cache database found."}

    con = duckdb.connect(str(DB_FILE), read_only=True)
    result: dict = {"sources": {}}

    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]

        if "timeseries" in tables:
            row = con.execute(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM timeseries"
            ).fetchone()
            if row and row[2] > 0:
                result["sources"]["cams_timeseries"] = {
                    "earliest": str(row[0]),
                    "latest": str(row[1]),
                    "count": row[2],
                }

        if "station_measurements" in tables:
            row = con.execute(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM station_measurements"
            ).fetchone()
            if row and row[2] > 0:
                result["sources"]["uba_stations"] = {
                    "earliest": str(row[0]),
                    "latest": str(row[1]),
                    "count": row[2],
                }

        if "measurements" in tables:
            row = con.execute(
                "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM measurements"
            ).fetchone()
            if row and row[2] > 0:
                result["sources"]["cams_volumetric"] = {
                    "earliest": str(row[0]),
                    "latest": str(row[1]),
                    "count": row[2],
                }

    finally:
        con.close()

    return result
