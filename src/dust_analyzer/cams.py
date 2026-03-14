"""
CAMS European Air Quality Forecasts — download and time-series extraction.

Dataset:   cams-europe-air-quality-forecasts
Resolution: 0.1° x 0.1° (~10 km)
Format:    NetCDF (direct, no ZIP) for type=analysis

Verified request for type=analysis (source: ECMWF training notebooks):
    https://ecmwf-projects.github.io/copernicus-training-cams/proc-aq-index.html

NetCDF variable names (verified from actual download):
  dust       → Saharan dust
  so2_conc   → sulphur dioxide  (request name: sulphur_dioxide)
  pm2p5_conc → PM2.5            (request name: particulate_matter_2.5um)

Time axis: float32, hours since date_from 00:00 UTC
  Attribute: 'units' = 'hours', 'long_name' = 'ANALYSIS time from YYYYMMDD'
  → converted to datetime64 in extract()

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
import requests
import xarray as xr

from dust_analyzer.location import Location


logger = logging.getLogger(__name__)


DATASET     = "cams-europe-air-quality-forecasts"
LICENCE_URL = "https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences"

HOURS = [f"{h:02d}:00" for h in range(24)]

DEFAULT_LEVELS_METERS: list[int] = [0, 50, 100, 250, 500, 750, 1000, 2000, 3000, 5000]

# (request_variable_name, netcdf_variable_name, label, color)
VARIABLES: dict[str, tuple[str, str, str, str]] = {
    "dust":  ("dust",                     "dust",       "Saharan dust [µg/m³]", "#c8a96e"),
    "so2":   ("sulphur_dioxide",          "so2_conc",   "SO₂ [µg/m³]",          "#e05252"),
    "pm2p5": ("particulate_matter_2.5um", "pm2p5_conc", "PM2.5 [µg/m³]",        "#7eb8d4"),
}


def date_range(days: int) -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=days)
    return start, end


def _nc_path(loc: Location, date_from: date, date_to: date) -> Path:
    return Path(f"cams_eu_{loc.lat:.2f}_{loc.lon:.2f}_{date_from}_{date_to}.nc")


def _parse_time_axis(ds: xr.Dataset, date_from: date) -> np.ndarray:
    """
    Convert the float32 time axis (hours since date_from 00:00 UTC)
    into a numpy datetime64 array.

    If the reference date can be extracted from the 'long_name' attribute,
    it is used; otherwise date_from is used as fallback.
    """
    long_name = ds.time.attrs.get("long_name", "")
    match = re.search(r"(\d{8})", long_name)
    if match:
        ref = datetime.strptime(match.group(1), "%Y%m%d")
    else:
        ref = datetime(date_from.year, date_from.month, date_from.day)

    hours = ds.time.values.astype(float)
    return np.array(
        [np.datetime64(ref + timedelta(hours=float(h)), "ns") for h in hours],
        dtype="datetime64[ns]",
    )


def download(
    loc: Location,
    date_from: date,
    date_to: date,
    levels_m: list[int] | None = None,
    area: list[float] | None = None,
) -> Path:
    """
    Download CAMS EU analysis data as NetCDF (no ZIP).
    Skip download if the .nc file already exists.
    """
    nc_path = _nc_path(loc, date_from, date_to)

    if nc_path.exists():
        logger.info("NetCDF already present: %s", nc_path.name)
        return nc_path

    if levels_m is None:
        levels_m = [0]

    if area is None:
        area = [loc.lat + 1, loc.lon - 1, loc.lat - 1, loc.lon + 1]  # N, W, S, E

    request = {
        "variable":      [v[0] for v in VARIABLES.values()],
        "model":         ["ensemble"],
        "level":         [str(level) for level in levels_m],
        "date":          [f"{date_from}/{date_to}"],
        "type":          ["analysis"],
        "time":          HOURS,
        "leadtime_hour": ["0"],
        "area":          area,
        "data_format":   "netcdf",
    }

    logger.info("CAMS Europe download (%s → %s)...", date_from, date_to)
    logger.info("%d hours × %d days", len(HOURS), (date_to - date_from).days + 1)
    logger.info("Queue can take 1–5 minutes.")

    client = cdsapi.Client()

    try:
        client.retrieve(DATASET, request, str(nc_path))
    except requests.HTTPError as e:
        if "403" in str(e) and "licence" in str(e).lower():
            logger.error("Licence not accepted for CAMS dataset.")
            logger.error("Accept once in the browser: %s", LICENCE_URL)
            sys.exit(1)
        raise

    logger.info("NetCDF download ready: %s", nc_path.name)
    return nc_path


def extract(nc_path: Path, loc: Location, date_from: date) -> dict[str, dict]:
    """
    Extract time series for the grid point nearest to `loc`.
    Returns dict: key → {time: datetime64[], values: float[], label, color}
    """
    ds = xr.open_dataset(nc_path, decode_timedelta=False)
    logger.info("Variables in file: %s", list(ds.data_vars))
    logger.info("Dimensions: %s", dict(ds.sizes))

    timestamps = _parse_time_axis(ds, date_from)
    series: dict[str, dict] = {}

    for key, (_, nc_var, label, color) in VARIABLES.items():
        if nc_var not in ds:
            logger.warning("Variable '%s' not found in file — skipping.", nc_var)
            continue

        da = ds[nc_var].sel(
            latitude=loc.lat,
            longitude=loc.lon,
            method="nearest",
        )

        # squeeze level dimension
        non_time = [d for d in da.dims if d != "time"]
        if non_time:
            da = da.isel({d: 0 for d in non_time})

        series[key] = {
            "time":   timestamps,
            "values": da.values.flatten().astype(float),
            "label":  label,
            "color":  color,
        }

    ds.close()
    return series


def extract_measurements(nc_path: Path, date_from: date) -> list[tuple]:
    """
    Extract volumetric measurements for all grid points and levels.

    Returns a list of tuples:
        (timestamp, latitude, longitude, level_m, variable, value, unit, model)
    """
    ds = xr.open_dataset(nc_path, decode_timedelta=False)

    timestamps = _parse_time_axis(ds, date_from)

    time_len = timestamps.shape[0]
    levels = ds["level"].values.astype(float) if "level" in ds.coords else np.array([0.0])
    lats = ds["latitude"].values.astype(float)
    lons = ds["longitude"].values.astype(float)

    rows: list[tuple] = []

    for key, (_, nc_var, _, _) in VARIABLES.items():
        if nc_var not in ds:
            continue

        da = ds[nc_var]
        data = da.values  # erwartet Form (time, level, latitude, longitude)
        units = str(da.attrs.get("units", "µg/m³"))
        model = "ensemble"

        for t_idx in range(time_len):
            ts = timestamps[t_idx]
            for lev_idx, level_val in enumerate(levels):
                for lat_idx, lat_val in enumerate(lats):
                    for lon_idx, lon_val in enumerate(lons):
                        value = float(data[t_idx, lev_idx, lat_idx, lon_idx])
                        if not np.isfinite(value):
                            continue
                        rows.append(
                            (
                                ts,
                                float(lat_val),
                                float(lon_val),
                                int(level_val),
                                key,
                                value,
                                units,
                                model,
                            )
                        )

    ds.close()
    return rows
