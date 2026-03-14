"""
Location resolution — IP geolocation or manual override.
"""

import argparse
from dataclasses import dataclass
import logging

import requests


logger = logging.getLogger(__name__)


@dataclass
class Location:
    lat: float
    lon: float
    city: str

    def __str__(self) -> str:
        return f"{self.city} ({self.lat:.2f}°N, {self.lon:.2f}°E)"


def from_ip() -> Location:
    """Resolve location via ipapi.co IP geolocation (no API key required)."""
    response = requests.get("https://ipapi.co/json/", timeout=10)
    response.raise_for_status()
    data = response.json()
    return Location(
        lat=float(data["latitude"]),
        lon=float(data["longitude"]),
        city=data.get("city", "Unknown"),
    )


def from_args(lat: float, lon: float) -> Location:
    return Location(lat=lat, lon=lon, city=f"{lat:.2f}°N, {lon:.2f}°E")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dust vs. SO₂ analysis using CAMS/Copernicus data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  dust-analyzer                        # auto-detect location via IP\n"
            "  dust-analyzer --lat 52.37 --lon 9.73 # Hannover manually\n"
            "  dust-analyzer --days 14              # last 14 days\n"
            "  dust-analyzer --no-cache             # ignore DuckDB cache\n"
        ),
    )
    parser.add_argument("--lat",      type=float, help="Latitude  (e.g. 52.37)")
    parser.add_argument("--lon",      type=float, help="Longitude (e.g. 9.73)")
    parser.add_argument("--days", type=int, default=7, help="Time range in days (default: 7)")
    parser.add_argument("--out", type=str, default="dust_analysis.html", help="Output HTML file")
    parser.add_argument("--no-cache", action="store_true", help="Ignore DuckDB cache")
    parser.add_argument("--mcp", action="store_true", help="Start as MCP server (stdio)")
    return parser.parse_args()


def resolve_location(args: argparse.Namespace) -> Location:
    if args.lat and args.lon:
        loc = from_args(args.lat, args.lon)
        logger.info("Using manual location: %s", loc)
        return loc

    logger.info("Resolving location via IP geolocation...")
    loc = from_ip()
    logger.info("Resolved location via IP: %s", loc)
    return loc
