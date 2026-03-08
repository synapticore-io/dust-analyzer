"""
Entry point: python -m dust_analyzer  oder  dust-analyzer (nach uv install)
"""

import sys
from pathlib import Path

from dust_analyzer import cache, cams
from dust_analyzer.location import parse_args, resolve_location


def main() -> None:
    args = parse_args()
    loc  = resolve_location(args)

    date_from, date_to = cams.date_range(args.days)

    # Cache prüfen
    series = None
    if not args.no_cache:
        series = cache.get(loc.lat, loc.lon, date_from, date_to)

    # CAMS Download wenn kein Cache-Treffer
    if series is None:
        nc_path = cams.download(loc, date_from, date_to)
        series  = cams.extract(nc_path, loc, date_from)

        if not series:
            print("❌ Keine Daten extrahiert.")
            sys.exit(1)

        cache.put(loc.lat, loc.lon, date_from, date_to, series)

    # Chart rendern
    from dust_analyzer.plot import render
    render(series, loc, args.days, Path(args.out))


if __name__ == "__main__":
    main()
