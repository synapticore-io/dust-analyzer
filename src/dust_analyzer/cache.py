"""
DuckDB cache for CAMS time series.
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


def _cache_key(lat: float, lon: float, date_from: date, date_to: date) -> str:
    return f"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}"


def _to_py_datetime(ts: np.datetime64) -> datetime:
    """numpy datetime64[ns] → Python datetime (UTC)."""
    unix_ns = int(ts.astype("int64"))
    return datetime.fromtimestamp(unix_ns / 1e9, tz=timezone.utc).replace(tzinfo=None)


def get(lat: float, lon: float, date_from: date, date_to: date) -> dict[str, pd.DataFrame] | None:
    """Return cached time series or None if not present."""
    if not DB_FILE.exists():
        return None

    key = _cache_key(lat, lon, date_from, date_to)
    con = duckdb.connect(str(DB_FILE))
    con.execute(SCHEMA)

    result = con.execute(
        "SELECT variable, timestamp, value FROM timeseries WHERE key = ? ORDER BY variable, timestamp",
        [key],
    ).fetchdf()
    con.close()

    if result.empty:
        return None

    logger.info("Cache hit — no API download needed.")
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
) -> None:
    """Speichert Zeitreihen in den Cache."""
    key = _cache_key(lat, lon, date_from, date_to)
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
    logger.info("Cached %d data points.", sum(len(d["time"]) for d in series.values()))


def put_measurements(
    rows: list[tuple],
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    date_from: date,
    date_to: date,
) -> None:
    """
    Speichert volumetrische Messungen in measurements.

    rows: (timestamp, latitude, longitude, level_m, variable, value, unit, model)
    """
    if not rows:
        return

    request_hash = (
        f"{lat_min:.2f}_{lat_max:.2f}_"
        f"{lon_min:.2f}_{lon_max:.2f}_"
        f"{date_from}_{date_to}"
    )

    con = duckdb.connect(str(DB_FILE))
    con.execute(MEASUREMENTS_SCHEMA)

    with con:
        con.executemany(
            """
            INSERT INTO measurements (
                timestamp, latitude, longitude, level_m,
                variable, value, unit, model, request_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(_to_py_datetime(ts), lat, lon, level_m, var, val, unit, model, request_hash) for ts, lat, lon, level_m, var, val, unit, model in rows],
        )

    con.close()
