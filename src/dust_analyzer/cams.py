"""
CAMS European Air Quality Forecasts - download, convert to Parquet, extract.

Dataset:   cams-europe-air-quality-forecasts
Resolution: 0.1 x 0.1 deg (~10 km)
Format:    NetCDF (direct, no ZIP) for type=analysis

Workflow:
  download() -> .nc file -> to_parquet() -> .parquet file -> .nc deleted
  All subsequent reads go through DuckDB on Parquet (see store.py).

Parquet schema per file:
  timestamp (datetime64[us]) | lat (f64) | lon (f64) | level_m (i32)
  | variable (str) | value (f64) | data_type (str)

NetCDF variable names (verified from actual download):
  dust       -> Saharan dust
  so2_conc   -> sulphur dioxide  (request name: sulphur_dioxide)
  pm2p5_conc -> PM2.5            (request name: particulate_matter_2.5um)

Licence (accept once in the browser):
  https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences
"""

import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
import logging

import cdsapi
import numpy as np
import polars as pl
import requests
import xarray as xr

from dust_analyzer.location import Location
from dust_analyzer.paths import DATA_DIR, ensure_data_dir


logger = logging.getLogger(__name__)

DATASET = "cams-europe-air-quality-forecasts"
LICENCE_URL = (
    "https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts"
    "?tab=download#manage-licences"
)

HOURS = [f"{h:02d}:00" for h in range(24)]

# (request_variable_name, netcdf_variable_name, label, color)
VARIABLES: dict[str, tuple[str, str, str, str]] = {
    "dust":  ("dust",                     "dust",       "Saharan dust [ug/m3]", "#c8a96e"),
    "so2":   ("sulphur_dioxide",          "so2_conc",   "SO2 [ug/m3]",          "#e05252"),
    "pm2p5": ("particulate_matter_2.5um", "pm2p5_conc", "PM2.5 [ug/m3]",        "#7eb8d4"),
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def date_range(days: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=days)
    return start, end


def date_range_forecast(days_back: int = 2, days_ahead: int = 3) -> tuple[date, date]:
    start = date.today() - timedelta(days=days_back)
    end = date.today() + timedelta(days=days_ahead)
    return start, end


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _parquet_path(
    area: list[float],
    date_from: date,
    date_to: date,
    data_type: str,
    levels_m: list[int],
) -> Path:
    """Canonical Parquet path for a given request.

    Encodes bounding box, dates, data_type, level count so different requests
    don't collide but identical requests reuse the same file.
    """
    n, w, s, e = area
    lev_tag = f"_lev{len(levels_m)}" if len(levels_m) > 1 else ""
    type_tag = "" if data_type == "analysis" else f"_{data_type}"
    name = (
        f"cams_n{n:.2f}_w{w:.2f}_s{s:.2f}_e{e:.2f}"
        f"_{date_from}_{date_to}{type_tag}{lev_tag}.parquet"
    )
    return DATA_DIR / name


# ---------------------------------------------------------------------------
# NetCDF helpers (internal)
# ---------------------------------------------------------------------------

def _parse_time_axis(ds: xr.Dataset, date_from: date) -> np.ndarray:
    """Convert float32 time axis (hours since date_from) to datetime64[ns]."""
    long_name = ds.time.attrs.get("long_name", "")
    match = re.search(r"(\d{8})", long_name)
    ref = (
        datetime.strptime(match.group(1), "%Y%m%d")
        if match
        else datetime(date_from.year, date_from.month, date_from.day)
    )
    hours = ds.time.values.astype(float)
    return np.array(
        [np.datetime64(ref + timedelta(hours=float(h)), "ns") for h in hours],
        dtype="datetime64[ns]",
    )


def _nc_to_parquet(
    nc_path: Path,
    parquet_path: Path,
    date_from: date,
    data_type: str,
    variables: list[str] | None = None,
) -> Path:
    """Convert NetCDF to columnar Parquet and delete the .nc file.

    Returns parquet_path.
    All grid points, all levels, all timesteps are stored — DuckDB slices later.
    """
    ds = xr.open_dataset(nc_path, decode_timedelta=False)

    # Sort all dims for consistent slicing
    for dim in ds.sizes:
        if dim in ds.coords:
            idx = ds.indexes[dim]
            if not (idx.is_monotonic_increasing or idx.is_monotonic_decreasing):
                ds = ds.sortby(dim)

    timestamps = _parse_time_axis(ds, date_from)
    # Deduplicate timestamps
    _, uniq_idx = np.unique(timestamps, return_index=True)
    timestamps = timestamps[uniq_idx]

    lats = ds["latitude"].values.astype(np.float32)
    lons = ds["longitude"].values.astype(np.float32)
    levels = ds["level"].values.astype(np.int32) if "level" in ds.coords else np.array([0], dtype=np.int32)

    var_keys = variables if variables is not None else list(VARIABLES.keys())

    chunks: list[pl.DataFrame] = []

    for key in var_keys:
        if key not in VARIABLES:
            continue
        _, nc_var, _, _ = VARIABLES[key]
        if nc_var not in ds:
            logger.warning("Variable '%s' not in file - skipping.", nc_var)
            continue

        da = ds[nc_var]
        # Ensure shape is (time, level, lat, lon) - insert level dim if missing
        if "level" not in da.dims:
            da = da.expand_dims("level", axis=1)

        arr = da.values[uniq_idx]  # (time, level, lat, lon)
        if arr.ndim == 3:
            arr = arr[:, np.newaxis, :, :]  # add level dim

        t_n, lev_n, lat_n, lon_n = arr.shape

        # Flatten to records - use numpy broadcasting for speed
        t_idx, lev_idx, lat_idx, lon_idx = np.meshgrid(
            np.arange(t_n), np.arange(lev_n), np.arange(lat_n), np.arange(lon_n),
            indexing="ij",
        )
        vals = arr.flatten().astype(np.float32)
        finite_mask = np.isfinite(vals)

        df = pl.DataFrame({
            "timestamp": timestamps[t_idx.flatten()[finite_mask]],
            "lat":       lats[lat_idx.flatten()[finite_mask]],
            "lon":       lons[lon_idx.flatten()[finite_mask]],
            "level_m":   levels[lev_idx.flatten()[finite_mask]].astype(np.int32),
            "variable":  key,
            "value":     vals[finite_mask],
            "data_type": data_type,
        })
        chunks.append(df)

    ds.close()

    if not chunks:
        raise ValueError(f"No valid data extracted from {nc_path.name}")

    result = pl.concat(chunks, how="vertical")
    result = result.with_columns(pl.col("timestamp").cast(pl.Datetime("ns")))
    result.write_parquet(parquet_path, compression="zstd")

    nc_path.unlink()
    logger.info(
        "Converted %s -> %s (%d rows, %.1f MB), .nc deleted.",
        nc_path.name, parquet_path.name,
        result.height,
        parquet_path.stat().st_size / 1e6,
    )
    return parquet_path


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def download(
    loc: Location,
    date_from: date,
    date_to: date,
    levels_m: list[int] | None = None,
    area: list[float] | None = None,
    data_type: str = "analysis",
    variables: list[str] | None = None,
) -> Path:
    """Download CAMS EU data and convert to Parquet.

    Returns the Parquet file path. Skips download if Parquet already exists.

    Args:
        data_type: "analysis" (default, ~48h latency) or "forecast"
        variables: Keys from VARIABLES. None = all three species.
        levels_m:  Altitude levels in metres. None = surface only ([0]).
    """
    ensure_data_dir()
    if levels_m is None:
        levels_m = [0]
    if area is None:
        area = [loc.lat + 1, loc.lon - 1, loc.lat - 1, loc.lon + 1]

    parquet_path = _parquet_path(area, date_from, date_to, data_type, levels_m)
    if parquet_path.exists():
        logger.info("Parquet already present: %s", parquet_path.name)
        return parquet_path

    if variables is None:
        request_var_names = [v[0] for v in VARIABLES.values()]
    else:
        unknown = [k for k in variables if k not in VARIABLES]
        if unknown:
            raise ValueError(f"Unknown variable keys: {unknown}")
        request_var_names = [VARIABLES[k][0] for k in variables]

    # Temporary .nc path (deleted after conversion)
    nc_path = DATA_DIR / (parquet_path.stem + ".nc")

    request: dict = {
        "variable":    request_var_names,
        "model":       ["ensemble"],
        "level":       [str(level) for level in levels_m],
        "type":        [data_type],
        "data_format": "netcdf",
    }

    if data_type == "analysis":
        request["area"] = area
        request["date"] = [f"{date_from}/{date_to}"]
        request["time"] = HOURS
        request["leadtime_hour"] = ["0"]
    else:
        # Forecast: no area subsetting (not supported), 6h steps
        init_date = date.today() - timedelta(days=1)
        request["date"] = [f"{init_date}/{init_date}"]
        request["time"] = ["00:00"]
        request["leadtime_hour"] = [
            "0", "6", "12", "18", "24", "30", "36", "42",
            "48", "54", "60", "66", "72", "78", "84", "90", "96",
        ]

    logger.info(
        "CAMS Europe %s download (%s -> %s)... Queue can take 1-5 minutes.",
        data_type, date_from, date_to,
    )
    client = cdsapi.Client()
    try:
        client.retrieve(DATASET, request, str(nc_path))
    except requests.HTTPError as e:
        if "403" in str(e) and "licence" in str(e).lower():
            logger.error("Licence not accepted. Accept once at: %s", LICENCE_URL)
            sys.exit(1)
        raise

    return _nc_to_parquet(nc_path, parquet_path, date_from, data_type, variables)


# ---------------------------------------------------------------------------
# Extraction helpers (read from Parquet via Polars - used by server.py)
# ---------------------------------------------------------------------------

def extract_timeseries(
    parquet_path: Path,
    loc: Location,
    variable: str,
    tolerance_deg: float = 0.15,
) -> dict | None:
    """Extract nearest-grid-point time series for one variable from a Parquet file.

    Returns {time, values, label, color} or None if variable not present.
    """
    if variable not in VARIABLES:
        return None
    _, _, label, color = VARIABLES[variable]

    df = (
        pl.scan_parquet(str(parquet_path))
        .filter(
            (pl.col("variable") == variable)
            & (pl.col("level_m") == 0)
            & (pl.col("lat") >= loc.lat - tolerance_deg)
            & (pl.col("lat") <= loc.lat + tolerance_deg)
            & (pl.col("lon") >= loc.lon - tolerance_deg)
            & (pl.col("lon") <= loc.lon + tolerance_deg),
        )
        .collect()
    )
    if df.is_empty():
        return None

    df = df.with_columns(
        ((pl.col("lat") - loc.lat) ** 2 + (pl.col("lon") - loc.lon) ** 2).alias("_dist"),
    )
    min_d = df["_dist"].min()
    nearest = df.filter(pl.col("_dist") == min_d).head(1)
    nearest_lat = nearest["lat"][0]
    nearest_lon = nearest["lon"][0]
    df = df.filter((pl.col("lat") == nearest_lat) & (pl.col("lon") == nearest_lon))
    df = df.sort("timestamp").unique(subset=["timestamp"], keep="first")

    return {
        "time":   df["timestamp"].to_numpy(),
        "values": df["value"].to_numpy().astype(float),
        "label":  label,
        "color":  color,
    }


def extract_all_timeseries(
    parquet_path: Path,
    loc: Location,
    tolerance_deg: float = 0.15,
) -> dict[str, dict]:
    """Extract time series for all variables from a Parquet file."""
    series = {}
    for key in VARIABLES:
        s = extract_timeseries(parquet_path, loc, key, tolerance_deg)
        if s is not None:
            series[key] = s
    return series


def extract_map_data(
    parquet_path: Path,
    max_grid_side: int = 40,
) -> dict[str, dict]:
    """Extract subsampled grid data for map visualisation.

    Returns {variable: {label, colorscale, lats, lons, values}}.
    """
    colorscales = {"dust": "YlOrBr", "so2": "Reds", "pm2p5": "Blues"}
    df = pl.scan_parquet(str(parquet_path)).filter(pl.col("level_m") == 0).collect()
    if df.is_empty():
        return {}

    # Use last timestamp
    last_ts = df["timestamp"].max()
    df = df.filter(pl.col("timestamp") == last_ts)

    result = {}
    for key in VARIABLES:
        _, _, label, _ = VARIABLES[key]
        sub = df.filter(pl.col("variable") == key)
        if sub.is_empty():
            continue

        # Subsample grid
        lats = np.sort(sub["lat"].unique().to_numpy())
        lons = np.sort(sub["lon"].unique().to_numpy())
        lat_stride = max(1, len(lats) // max_grid_side)
        lon_stride = max(1, len(lons) // max_grid_side)
        keep_lats = set(lats[::lat_stride])
        keep_lons = set(lons[::lon_stride])
        sub = sub.filter(pl.col("lat").is_in(list(keep_lats)) & pl.col("lon").is_in(list(keep_lons)))

        result[key] = {
            "label":      label,
            "colorscale": colorscales.get(key, "YlOrRd"),
            "lats":       np.round(sub["lat"].to_numpy(), 2).tolist(),
            "lons":       np.round(sub["lon"].to_numpy(), 2).tolist(),
            "values":     np.round(sub["value"].to_numpy(), 2).tolist(),
        }
    return result
