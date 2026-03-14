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

    if args.mcp:
        from dust_analyzer.server import run_server
        run_server()
        return
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

        if not args.no_cache:
            cache.put(loc.lat, loc.lon, date_from, date_to, series)

            measurement_rows = cams.extract_measurements(nc_path, date_from)
            if measurement_rows:
                cache.put_measurements(
                    measurement_rows,
                    loc.lat - 1, loc.lat + 1,
                    loc.lon - 1, loc.lon + 1,
                    date_from, date_to,
                )

    # Render chart
    from dust_analyzer.plot import render
    render(series, loc, args.days, Path(args.out))


if __name__ == "__main__":
    main()
