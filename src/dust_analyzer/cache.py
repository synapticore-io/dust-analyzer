"""
DuckDB-Cache für CAMS-Zeitreihen.
Verhindert wiederholte API-Downloads für gleiche Koordinaten + Zeitraum.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


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


def _cache_key(lat: float, lon: float, date_from: date, date_to: date) -> str:
    return f"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}"


def _to_py_datetime(ts: np.datetime64) -> datetime:
    """numpy datetime64[ns] → Python datetime (UTC)."""
    unix_ns = int(ts.astype("int64"))
    return datetime.fromtimestamp(unix_ns / 1e9, tz=timezone.utc).replace(tzinfo=None)


def get(lat: float, lon: float, date_from: date, date_to: date) -> dict[str, pd.DataFrame] | None:
    """Gibt gecachte Zeitreihen zurück oder None wenn nicht vorhanden."""
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

    print("💾 Cache-Treffer — kein API-Download nötig.")
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
    print(f"💾 {sum(len(d['time']) for d in series.values())} Datenpunkte gecacht.")
