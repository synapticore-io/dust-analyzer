"""
Location resolution — IP geolocation oder manueller Override.
"""

import argparse
from dataclasses import dataclass

import requests


@dataclass
class Location:
    lat: float
    lon: float
    city: str

    def __str__(self) -> str:
        return f"{self.city} ({self.lat:.2f}°N, {self.lon:.2f}°E)"


def from_ip() -> Location:
    """IP-Geolocation via ipapi.co — kein API-Key nötig."""
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
        description="Dust vs. SO₂ Analyse via CAMS/Copernicus",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  dust-analyzer                        # IP-Geolocation automatisch
  dust-analyzer --lat 52.37 --lon 9.73 # Hannover manuell
  dust-analyzer --days 14              # Letzten 14 Tage
  dust-analyzer --no-cache             # Cache ignorieren
        """,
    )
    parser.add_argument("--lat",      type=float, help="Latitude  (z.B. 52.37)")
    parser.add_argument("--lon",      type=float, help="Longitude (z.B. 9.73)")
    parser.add_argument("--days",     type=int,   default=7,     help="Zeitraum in Tagen (default: 7)")
    parser.add_argument("--out",      type=str,   default="dust_analysis.html", help="Output HTML-Datei")
    parser.add_argument("--no-cache", action="store_true", help="DuckDB-Cache ignorieren")
    return parser.parse_args()


def resolve_location(args: argparse.Namespace) -> Location:
    if args.lat and args.lon:
        loc = from_args(args.lat, args.lon)
        print(f"📍 Manuell: {loc}")
        return loc

    print("📍 IP-Geolocation läuft...")
    loc = from_ip()
    print(f"   → {loc}")
    return loc
