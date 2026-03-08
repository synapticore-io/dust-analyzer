"""
dust-analyzer v0.1.0
====================
Saharastaub vs. Industrieemissionen — CAMS/Copernicus Luftqualitätsanalyse.

Datenquelle: Copernicus Atmosphere Monitoring Service (ECMWF)
             Dieselbe Quelle wie Windy für alle Luftqualitäts-Layer.

Quick start:
    dust-analyzer                        # IP-Geolocation automatisch
    dust-analyzer --lat 52.37 --lon 9.73 # Hannover manuell
    dust-analyzer --days 14              # Letzten 14 Tage
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
