"""
Entry point: python -m dust_analyzer  oder  dust-analyzer (nach uv install)
"""

import logging
import sys
from pathlib import Path

from dust_analyzer import cache, cams
from dust_analyzer.location import parse_args, resolve_location


logger = logging.getLogger(__name__)


def _enrich_from_cache(cached: dict) -> dict:
    """Attach label/color from VARIABLES definition to cache DataFrames."""
    enriched = {}
    for key, df in cached.items():
        if key not in cams.VARIABLES:
            continue
        _, _, label, color = cams.VARIABLES[key]
        enriched[key] = {
            "time":   df["time"].values,
            "values": df["value"].values,
            "label":  label,
            "color":  color,
        }
    return enriched


def main() -> None:
    args = parse_args()
    loc  = resolve_location(args)

    date_from, date_to = cams.date_range(args.days)

    # Check cache
    series = None
    if not args.no_cache:
        cached = cache.get(loc.lat, loc.lon, date_from, date_to)
        if cached:
            series = _enrich_from_cache(cached)

    # CAMS download if there was no cache hit
    if series is None:
        nc_path = cams.download(loc, date_from, date_to)
        series  = cams.extract(nc_path, loc, date_from)

        if not series:
            logger.error("No data extracted from CAMS download.")
            sys.exit(1)

        cache.put(loc.lat, loc.lon, date_from, date_to, series)

        # Capture volumetric measurements for the notebook use case
        measurement_rows = cams.extract_measurements(nc_path, date_from)
        if measurement_rows:
            area_lat_min = loc.lat - 1
            area_lat_max = loc.lat + 1
            area_lon_min = loc.lon - 1
            area_lon_max = loc.lon + 1
            cache.put_measurements(
                measurement_rows,
                area_lat_min,
                area_lat_max,
                area_lon_min,
                area_lon_max,
                date_from,
                date_to,
            )

    # Chart rendern
    from dust_analyzer.plot import render
    render(series, loc, args.days, Path(args.out))


if __name__ == "__main__":
    main()
