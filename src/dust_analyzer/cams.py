"""
CAMS European Air Quality Forecasts — Download + Zeitreihen-Extraktion.

Dataset:   cams-europe-air-quality-forecasts
Auflösung: 0.1° x 0.1° (~10km)
Format:    netcdf (direkt, kein ZIP) für type=analysis

Verifizierter Request für type=analysis (Quelle: ECMWF Training Notebooks):
    https://ecmwf-projects.github.io/copernicus-training-cams/proc-aq-index.html

NetCDF-Variablennamen (verifiziert aus tatsächlichem Download):
  dust       → Saharastaub
  so2_conc   → Schwefeldioxid  (request-name: sulphur_dioxide)
  pm2p5_conc → PM2.5           (request-name: particulate_matter_2.5um)

Zeitachse: float32, Stunden seit date_from 00:00 UTC
  Attribut: 'units' = 'hours', 'long_name' = 'ANALYSIS time from YYYYMMDD'
  → wird in extract() zu datetime64 konvertiert

Lizenz (einmalig im Browser akzeptieren):
  https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences
"""

import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import cdsapi
import numpy as np
import requests
import xarray as xr

from dust_analyzer.location import Location


DATASET     = "cams-europe-air-quality-forecasts"
LICENCE_URL = "https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences"

HOURS = [f"{h:02d}:00" for h in range(24)]

# (request_variable_name, netcdf_variable_name, label, color)
VARIABLES: dict[str, tuple[str, str, str, str]] = {
    "dust":  ("dust",                     "dust",       "Saharastaub [µg/m³]", "#c8a96e"),
    "so2":   ("sulphur_dioxide",          "so2_conc",   "SO₂ [µg/m³]",         "#e05252"),
    "pm2p5": ("particulate_matter_2.5um", "pm2p5_conc", "PM2.5 [µg/m³]",       "#7eb8d4"),
}


def date_range(days: int) -> tuple[date, date]:
    end   = date.today()
    start = end - timedelta(days=days)
    return start, end


def _nc_path(loc: Location, date_from: date, date_to: date) -> Path:
    return Path(f"cams_eu_{loc.lat:.2f}_{loc.lon:.2f}_{date_from}_{date_to}.nc")


def _parse_time_axis(ds: xr.Dataset, date_from: date) -> np.ndarray:
    """
    Konvertiert die float32-Zeitachse (Stunden seit date_from 00:00 UTC)
    in ein numpy datetime64-Array.

    Falls die Referenzzeit aus dem 'long_name'-Attribut extrahierbar ist,
    wird diese genutzt — ansonsten date_from als Fallback.
    """
    long_name = ds.time.attrs.get("long_name", "")
    match = re.search(r"(\d{8})", long_name)
    if match:
        ref = datetime.strptime(match.group(1), "%Y%m%d").replace(tzinfo=timezone.utc)
    else:
        ref = datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc)

    hours = ds.time.values.astype(float)
    return np.array(
        [np.datetime64(ref + timedelta(hours=float(h)), "ns") for h in hours],
        dtype="datetime64[ns]",
    )


def download(loc: Location, date_from: date, date_to: date) -> Path:
    """
    Lädt CAMS EU Analysis-Daten als netcdf (kein ZIP).
    Überspringt Download wenn .nc bereits vorhanden.
    """
    nc_path = _nc_path(loc, date_from, date_to)

    if nc_path.exists():
        print(f"📁 NetCDF bereits vorhanden: {nc_path.name}")
        return nc_path

    area = [loc.lat + 1, loc.lon - 1, loc.lat - 1, loc.lon + 1]  # N, W, S, E

    request = {
        "variable":      [v[0] for v in VARIABLES.values()],
        "model":         ["ensemble"],
        "level":         ["0"],
        "date":          [f"{date_from}/{date_to}"],
        "type":          ["analysis"],
        "time":          HOURS,
        "leadtime_hour": ["0"],
        "area":          area,
        "data_format":   "netcdf",
    }

    print(f"⬇  CAMS Europe Download ({date_from} → {date_to})...")
    print(f"   {len(HOURS)} Stunden × {(date_to - date_from).days + 1} Tage")
    print("   Queue kann 1–5 Min dauern.\n")

    client = cdsapi.Client()

    try:
        client.retrieve(DATASET, request, str(nc_path))
    except requests.HTTPError as e:
        if "403" in str(e) and "licence" in str(e).lower():
            print(f"\n❌ Lizenz nicht akzeptiert.")
            print(f"   Einmalig im Browser:\n   {LICENCE_URL}\n")
            sys.exit(1)
        raise

    print(f"✅ Bereit: {nc_path.name}")
    return nc_path


def extract(nc_path: Path, loc: Location, date_from: date) -> dict[str, dict]:
    """
    Extrahiert Zeitreihen für nächsten Gitterpunkt zu loc.
    Gibt Dict: key → {time: datetime64[], values: float[], label, color}
    """
    ds = xr.open_dataset(nc_path, decode_timedelta=False)
    print(f"   Variablen im File: {list(ds.data_vars)}")
    print(f"   Dimensionen:       {dict(ds.sizes)}")

    timestamps = _parse_time_axis(ds, date_from)
    series: dict[str, dict] = {}

    for key, (_, nc_var, label, color) in VARIABLES.items():
        if nc_var not in ds:
            print(f"  ⚠ '{nc_var}' nicht im File — überspringe.")
            continue

        da = ds[nc_var].sel(
            latitude=loc.lat,
            longitude=loc.lon,
            method="nearest",
        )

        # level-Dimension rausdrücken
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
