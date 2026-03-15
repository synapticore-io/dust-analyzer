"""
dust-analyzer v0.2.0
====================
Saharan dust vs. anthropogenic emissions — CAMS/Copernicus air-quality analysis
with UBA ground-truth station overlay.

Data sources:
  - CAMS European Air Quality Forecasts (Copernicus/ECMWF) — analysis + forecast
  - UBA Umweltbundesamt — hourly station measurements (Germany)

Quick start:
    dust-analyzer                        # auto-detect location via IP geolocation
    dust-analyzer --lat 52.37 --lon 9.73 # Hannover manually
    dust-analyzer --days 14              # last 14 days
    dust-analyzer --mcp                  # start as MCP server
"""

from dust_analyzer.cams import download, extract, date_range, date_range_forecast, VARIABLES
from dust_analyzer.location import Location, from_ip, from_args
from dust_analyzer.plot import render

__version__ = "0.2.0"
__all__ = [
    "download",
    "extract",
    "date_range",
    "date_range_forecast",
    "VARIABLES",
    "Location",
    "from_ip",
    "from_args",
    "render",
]
