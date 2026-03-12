"""
dust-analyzer v0.1.0
====================
Saharan dust vs. anthropogenic emissions — CAMS/Copernicus air-quality analysis.

Data source: Copernicus Atmosphere Monitoring Service (ECMWF)
             Same source Windy uses for all air-quality layers.

Quick start:
    dust-analyzer                        # auto-detect location via IP geolocation
    dust-analyzer --lat 52.37 --lon 9.73 # Hannover manually
    dust-analyzer --days 14              # last 14 days
"""

from dust_analyzer.cams import download, extract, date_range, VARIABLES
from dust_analyzer.location import Location, from_ip, from_args
from dust_analyzer.plot import render

__version__ = "0.1.0"
__all__ = [
    "download",
    "extract",
    "date_range",
    "VARIABLES",
    "Location",
    "from_ip",
    "from_args",
    "render",
]
