"""
Entry point: python -m dust_analyzer  oder  dust-analyzer (nach uv install)
"""

import logging
import sys
from pathlib import Path

import numpy as np

from dust_analyzer import cache, cams
from dust_analyzer.location import parse_args, resolve_location


logger = logging.getLogger(__name__)


def _fetch(loc, date_from, date_to, data_type, use_cache):
    if use_cache:
        cached = cache.get(loc.lat, loc.lon, date_from, date_to, data_type)
        if cached:
            series = {}
            for key, df in cached.items():
                if key not in cams.VARIABLES:
                    continue
                _, _, label, color = cams.VARIABLES[key]
                series[key] = {
                    "time":   df["time"].to_numpy(),
                    "values": df["value"].to_numpy(),
                    "label":  label,
                    "color":  color,
                }
            return series

    # Download -> Parquet (nc deleted automatically)
    parquet_path = cams.download(loc, date_from, date_to, data_type=data_type)
    return cams.extract_all_timeseries(parquet_path, loc)


def _stitch(analysis, forecast):
    series = dict(analysis) if analysis else {}
    if not forecast:
        return series

    for key, fc_data in forecast.items():
        if key in series and len(series[key]["time"]) > 0:
            series[key] = {
                "time":   np.concatenate([series[key]["time"], fc_data["time"]]),
                "values": np.concatenate([series[key]["values"], fc_data["values"]]),
                "label":  series[key]["label"],
                "color":  series[key]["color"],
            }
        elif key not in series:
            series[key] = fc_data

    for data in series.values():
        sort_idx = np.argsort(data["time"])
        data["time"]   = data["time"][sort_idx]
        data["values"] = data["values"][sort_idx]
        mask = np.concatenate([[True], data["time"][1:] != data["time"][:-1]])
        data["time"]   = data["time"][mask]
        data["values"] = data["values"][mask]

    return series


def _fetch_station(lat, lon, days):
    try:
        from dust_analyzer import uba
        result = uba.fetch_for_location(lat, lon, days=days, variables=["pm2p5", "so2"])
        if result["station"] and result["series"]:
            return result
    except Exception as e:
        logger.warning("UBA station data unavailable: %s", e)
    return None


def main() -> None:
    args = parse_args()

    if args.mcp:
        from dust_analyzer.server import run_server
        run_server()
        return

    loc = resolve_location(args)
    use_cache = not args.no_cache
    mode = args.mode
    series = None

    if mode in ("analysis", "auto"):
        date_from, date_to = cams.date_range(args.days)
        series = _fetch(loc, date_from, date_to, "analysis", use_cache)

    if mode in ("forecast", "auto"):
        fc_from, fc_to = cams.date_range_forecast(days_back=2, days_ahead=3)
        forecast = _fetch(loc, fc_from, fc_to, "forecast", use_cache)
        if mode == "forecast":
            series = forecast
        elif forecast:
            series = _stitch(series, forecast)

    if not series:
        logger.error("No data available.")
        sys.exit(1)

    station_result = None
    if mode != "forecast":
        station_result = _fetch_station(loc.lat, loc.lon, args.days)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    from dust_analyzer.plot import render
    render(series, loc, args.days, out_path, station=station_result, mode=mode)


if __name__ == "__main__":
    main()
