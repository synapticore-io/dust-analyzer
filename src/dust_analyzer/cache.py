"""
Cache layer for dust-analyzer.

CAMS timeseries data is stored as Parquet files in DATA_DIR.
DuckDB reads them directly via glob - no separate schema tables needed.

Parquet schema (written by cams._nc_to_parquet):
  timestamp (datetime64[us]) | lat (f64) | lon (f64) | level_m (i32)
  | variable (str) | value (f64) | data_type (str)

UBA station data is still kept in a small DuckDB table (station_measurements)
because it comes from a REST API, not a file download.
"""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import logging

import duckdb
import numpy as np
import polars as pl

from dust_analyzer.paths import DATA_DIR, DB_FILE, ensure_data_dir


logger = logging.getLogger(__name__)


def _series_ts_to_datetime(ts) -> datetime:
    """Convert time series timestamps (datetime or numpy datetime64) to naive UTC datetime."""
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=None) if ts.tzinfo else ts
    arr = np.asarray(ts, dtype="datetime64[s]")
    sec = int(arr.astype("int64"))
    return datetime.fromtimestamp(sec, tz=timezone.utc).replace(tzinfo=None)


STATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS station_measurements (
    station_id   INTEGER   NOT NULL,
    station_name TEXT,
    lat          DOUBLE    NOT NULL,
    lon          DOUBLE    NOT NULL,
    variable     TEXT      NOT NULL,
    timestamp    TIMESTAMP NOT NULL,
    value        DOUBLE,
    unit         TEXT      DEFAULT 'ug/m3',
    source       TEXT      DEFAULT 'uba'
);
CREATE INDEX IF NOT EXISTS idx_station_var_ts
    ON station_measurements (station_id, variable, timestamp);
"""


# ---------------------------------------------------------------------------
# Parquet file discovery
# ---------------------------------------------------------------------------

def _parquet_glob() -> str:
    """DuckDB glob pattern for all CAMS Parquet files in DATA_DIR."""
    return str(DATA_DIR / "cams_*.parquet").replace("\\", "/")


def find_parquet_covering(
    lat: float,
    lon: float,
    date_from: date,
    date_to: date,
    data_type: str = "analysis",
    tolerance_deg: float = 0.5,
) -> list[Path]:
    """Return Parquet files that likely cover the requested location + time window.

    Checks filename bounding-box encoding: cams_n{N}_w{W}_s{S}_e{E}_{from}_{to}...
    Falls back to content scan only when filename parsing fails.
    """
    parquet_files = list(DATA_DIR.glob("cams_*.parquet"))
    if not parquet_files:
        return []

    type_tag = f"_{data_type}" if data_type != "analysis" else ""
    candidates = []

    for p in parquet_files:
        name = p.stem
        # Must match data_type
        if data_type == "analysis" and "_forecast" in name:
            continue
        if data_type != "analysis" and type_tag not in name:
            continue

        # Parse bounding box from filename
        import re
        m = re.match(
            r"cams_n([\d.\-]+)_w([\d.\-]+)_s([\d.\-]+)_e([\d.\-]+)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})",
            name,
        )
        if not m:
            candidates.append(p)  # can't parse, include for content scan
            continue

        fn, fw, fs, fe = float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
        f_from = date.fromisoformat(m.group(5))
        f_to = date.fromisoformat(m.group(6))

        bbox_ok = (fs - tolerance_deg <= lat <= fn + tolerance_deg and
                   fw - tolerance_deg <= lon <= fe + tolerance_deg)
        # Allow partial time overlap - server layer handles gaps
        date_ok = f_from <= date_to and f_to >= date_from

        if bbox_ok and date_ok:
            candidates.append(p)

    return candidates


# ---------------------------------------------------------------------------
# CAMS timeseries read/write via Parquet
# ---------------------------------------------------------------------------

def get(
    lat: float,
    lon: float,
    date_from: date,
    date_to: date,
    data_type: str = "analysis",
) -> dict[str, pl.DataFrame] | None:
    """Return cached time series from Parquet or None if not covered.

    Cache is only used when date_to is today - ensures at most one CAMS
    download per day. For older date ranges the data is already final
    (CAMS analysis doesn't change), so we always reuse those.
    Requires 80 % hourly row coverage per variable.
    """
    candidates = find_parquet_covering(lat, lon, date_from, date_to, data_type)
    if not candidates:
        return None

    # If date_to is today and data_type is analysis, check that the newest
    # timestamp in the candidate files actually reaches today - otherwise
    # the file is from yesterday's run and we need a fresh download.
    from datetime import date as _date
    today = _date.today()
    if date_to >= today and data_type == "analysis":
        con = duckdb.connect()
        try:
            glob_parts = " UNION ALL ".join(
                f"SELECT timestamp FROM read_parquet('{p.as_posix()}')" for p in candidates
            )
            row = con.execute(f"SELECT MAX(timestamp) FROM ({glob_parts})").fetchone()
            max_ts = row[0] if row else None
        finally:
            con.close()
        if max_ts is None:
            return None
        if isinstance(max_ts, datetime):
            max_date = max_ts.date()
        elif isinstance(max_ts, date):
            max_date = max_ts
        else:
            max_date = _series_ts_to_datetime(max_ts).date()
        # CAMS analysis has ~48h latency: data for D-2 is the freshest available.
        # Accept cache if it covers at least up to 2 days ago.
        freshness_cutoff = today - timedelta(days=2)
        if max_date < freshness_cutoff:
            logger.info("Cache stale (newest data: %s) - triggering fresh download.", max_date)
            return None

    glob = " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{p.as_posix()}')" for p in candidates
    )

    con = duckdb.connect()
    try:
        raw = con.execute(f"""
            SELECT variable, timestamp, value
            FROM ({glob})
            WHERE data_type = ?
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
              AND level_m = 0
              AND timestamp >= ?
              AND timestamp < ?
            ORDER BY variable, timestamp
        """, [
            data_type,
            lat - 0.15, lat + 0.15,
            lon - 0.15, lon + 0.15,
            str(date_from),
            str(date_to + timedelta(days=1)),
        ]).fetchnumpy()
    finally:
        con.close()

    result = pl.DataFrame(raw)
    if result.is_empty():
        return None

    requested_days = max(1, (date_to - date_from).days + 1)
    min_rows = int(requested_days * 24 * 0.8)

    series: dict[str, pl.DataFrame] = {}
    for var in result["variable"].unique().to_list():
        grp = result.filter(pl.col("variable") == var)
        if grp.height >= min_rows:
            series[str(var)] = grp.select(
                pl.col("timestamp").alias("time"),
                pl.col("value"),
            )

    if not series:
        return None

    logger.info("Cache hit (%s, %d vars) - no API download needed.", data_type, len(series))
    return series


def put(
    lat: float,
    lon: float,
    date_from: date,
    date_to: date,
    series: dict[str, dict],
    data_type: str = "analysis",
) -> None:
    """Write time series to Parquet (point data only, level_m=0).

    Used when data was fetched via API but not via the full download flow
    (e.g. legacy paths). In the normal download flow, cams._nc_to_parquet
    already writes the full Parquet - this is only a fallback.
    """
    ensure_data_dir()

    rows = []
    for variable, data in series.items():
        for ts, val in zip(data["time"], data["values"]):
            rows.append({
                "timestamp": _series_ts_to_datetime(ts),
                "lat":       float(lat),
                "lon":       float(lon),
                "level_m":   0,
                "variable":  variable,
                "value":     float(val),
                "data_type": data_type,
            })

    if not rows:
        return

    df = pl.DataFrame(rows)
    # Use a point-data filename distinct from area downloads
    fname = f"cams_pt_{lat:.2f}_{lon:.2f}_{date_from}_{date_to}"
    if data_type != "analysis":
        fname += f"_{data_type}"
    fname += ".parquet"
    out_path = DATA_DIR / fname

    if out_path.exists():
        existing = pl.read_parquet(out_path)
        df = pl.concat([existing, df], how="vertical").unique(
            subset=["timestamp", "lat", "lon", "level_m", "variable"],
            keep="first",
        )

    df.write_parquet(out_path, compression="zstd")
    logger.info("Wrote %d rows to %s.", len(df), fname)


# ---------------------------------------------------------------------------
# UBA station measurements (still DuckDB table - small, API-sourced)
# ---------------------------------------------------------------------------

def put_station_data(
    station_id: int,
    station_name: str,
    lat: float,
    lon: float,
    series: dict[str, dict],
) -> None:
    ensure_data_dir()
    con = duckdb.connect(str(DB_FILE))
    con.execute(STATION_SCHEMA)

    total = 0
    with con:
        for variable, data in series.items():
            rows = [
                (station_id, station_name, lat, lon, variable,
                 _series_ts_to_datetime(ts), float(val), "ug/m3", "uba")
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
    logger.info("Cached %d station rows for %s (%d).", total, station_name, station_id)


def get_station_data(
    station_id: int,
    variable: str,
    date_from: date,
    date_to: date,
) -> list[dict] | None:
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
    """Summary of available data: Parquet files + UBA station cache."""
    parquet_files = list(DATA_DIR.glob("cams_*.parquet"))
    result: dict = {"parquet_files": len(parquet_files), "sources": {}}

    if parquet_files:
        glob_parts = " UNION ALL ".join(
            f"SELECT * FROM read_parquet('{p.as_posix()}')" for p in parquet_files
        )
        con = duckdb.connect()
        try:
            row = con.execute(f"""
                SELECT MIN(timestamp), MAX(timestamp), COUNT(*)
                FROM ({glob_parts})
            """).fetchone()
            if row and row[2]:
                result["sources"]["cams"] = {
                    "earliest": str(row[0]),
                    "latest":   str(row[1]),
                    "count":    row[2],
                    "files":    [p.name for p in parquet_files],
                }
        finally:
            con.close()

    if DB_FILE.exists():
        con = duckdb.connect(str(DB_FILE), read_only=True)
        try:
            tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
            if "station_measurements" in tables:
                row = con.execute(
                    "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM station_measurements"
                ).fetchone()
                if row and row[2]:
                    result["sources"]["uba_stations"] = {
                        "earliest": str(row[0]),
                        "latest":   str(row[1]),
                        "count":    row[2],
                    }
        finally:
            con.close()

    return result
