"""
MCP Server for dust-analyzer - exposes CAMS + UBA air quality data as interactive Plotly charts.
Uses MCP Apps to render charts directly in Claude Desktop.

MCP Apps protocol:
- Tools return CallToolResult: content[] = human summary for the model; structuredContent = JSON object for the UI only (per MCP spec — do not embed chart JSON in content[].text).
- structuredContent is sanitized with _json_safe so the wire payload is valid JSON.
- UI resources predeclared via @mcp.resource() with mime_type and meta CSP
- Tool meta links to resource via {"ui": {"resourceUri": "ui://..."}}
- CSP is set directly under resource meta: meta={"csp": {"resourceDomains": [...]}}

Data layer:
- CAMS downloads are converted to Parquet immediately after download (.nc deleted)
- All reads go through cams.extract_* helpers (Polars on Parquet) or DuckDB read_parquet
- UBA station data lives in a small DuckDB table (station_measurements)
"""

import logging
import math
from datetime import date, datetime
from typing import Any
from typing_extensions import TypedDict

import duckdb
import numpy as np
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from dust_analyzer import cams, cache, remote, uba
from dust_analyzer.location import Location
from dust_analyzer.mcp_ui import load_mcp_html

logger = logging.getLogger(__name__)


class CityInput(TypedDict):
    """City coordinates for compare_cities."""
    lat: float
    lon: float
    city: str


mcp = FastMCP(
    "dust-analyzer",
    instructions=(
        "Luftqualitat in Europa analysieren - Saharastaub, SO2 und PM2.5 aus CAMS/Copernicus-Daten "
        "mit optionalem UBA-Stationsmessungen-Overlay (nur Deutschland).\n\n"
        "Tool-Auswahl:\n"
        "- Einzelstandort analysieren -> analyze_air_quality (Zeitreihe, empfohlener Einstieg)\n"
        "- Raumliche Verteilung auf Karte -> show_air_quality_map (Heatmap auf OSM)\n"
        "- Mehrere Stadte vergleichen -> compare_cities (max 5)\n"
        "- Bereits heruntergeladene Daten abfragen -> query_measurements (kein API-Call)\n\n"
        "Datumsbereich wird automatisch berechnet - keine manuellen Daten notig. "
        "Koordinaten (lat/lon) sind immer erforderlich."
    ),
)

TIMESERIES_URI = "ui://dust-analyzer/timeseries.html"
MAP_URI        = "ui://dust-analyzer/map.html"
COMPARE_URI    = "ui://dust-analyzer/compare.html"

_UI_CSP = {
    "resourceDomains": [
        "https://cdn.plot.ly",
        "https://cdn.jsdelivr.net",
        "https://unpkg.com",
    ]
}
_RESOURCE_META = {"csp": _UI_CSP}


@mcp.resource(TIMESERIES_URI, mime_type="text/html;profile=mcp-app", meta=_RESOURCE_META)
def timeseries_resource() -> str:
    return load_mcp_html("timeseries.html")


@mcp.resource(MAP_URI, mime_type="text/html;profile=mcp-app", meta=_RESOURCE_META)
def map_resource() -> str:
    return load_mcp_html("map.html")


@mcp.resource(COMPARE_URI, mime_type="text/html;profile=mcp-app", meta=_RESOURCE_META)
def compare_resource() -> str:
    return load_mcp_html("compare.html")




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _serialize_series(series: dict[str, dict]) -> dict:
    out = {}
    for key, data in series.items():
        out[key] = {
            "time":   [str(t) for t in data["time"]],
            "values": [float(v) for v in data["values"]],
            "label":  data["label"],
            "color":  data["color"],
        }
    return out


def _sort_dedup_series(series: dict[str, dict], keep: str = "first") -> dict[str, dict]:
    for data in series.values():
        times = np.asarray(data["time"])
        values = np.asarray(data["values"])
        sort_idx = np.argsort(times)
        times = times[sort_idx]
        values = values[sort_idx]
        if keep == "last":
            mask = np.concatenate([times[:-1] != times[1:], [True]])
        else:
            mask = np.concatenate([[True], times[1:] != times[:-1]])
        data["time"]   = times[mask]
        data["values"] = values[mask]
    return series


def _stitch_analysis_forecast(analysis: dict, forecast: dict) -> dict:
    series = dict(analysis) if analysis else {}
    if not forecast:
        return series
    for key, fc in forecast.items():
        if key in series and len(series[key]["time"]) > 0:
            series[key] = {
                "time":   np.concatenate([series[key]["time"], fc["time"]]),
                "values": np.concatenate([series[key]["values"], fc["values"]]),
                "label":  series[key]["label"],
                "color":  series[key]["color"],
            }
        elif key not in series:
            series[key] = fc
    return _sort_dedup_series(series, keep="first")


def _today_str() -> str:
    return date.today().isoformat()


def _json_safe(obj: Any) -> Any:
    """Ensure values are JSON-serializable for MCP CallToolResult.structuredContent (RFC 8259)."""
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(x) for x in obj]
    if hasattr(obj, "item"):
        try:
            return _json_safe(obj.item())
        except Exception:
            return str(obj)
    return str(obj)


def _error_result(msg: str, **extra) -> CallToolResult:
    payload = _json_safe({"error": msg, **extra})
    assert isinstance(payload, dict)
    return CallToolResult(
        content=[TextContent(type="text", text=msg)],
        structuredContent=payload,
        isError=True,
    )


def _ok_result(summary: str, data: dict) -> CallToolResult:
    payload = _json_safe(data)
    assert isinstance(payload, dict)
    return CallToolResult(
        content=[TextContent(type="text", text=summary)],
        structuredContent=payload,
    )


def _fetch_cams(
    loc: Location,
    date_from: date,
    date_to: date,
    data_type: str = "analysis",
) -> dict[str, dict]:
    """Read time series from remote GitHub Release Parquet via DuckDB httpfs."""
    series = remote.get_timeseries(
        loc.lat, loc.lon, date_from, date_to, data_type,
    )
    if series and data_type == "forecast":
        series = _sort_dedup_series(series, keep="last")
    return series


def _fetch_station_overlay(lat: float, lon: float, days: int) -> dict | None:
    try:
        result = uba.fetch_for_location(lat, lon, days=days, variables=["pm2p5", "so2"])
        if result["station"] and result["series"]:
            st = result["station"]
            cache.put_station_data(
                station_id=st["id"],
                station_name=st["name"],
                lat=st["lat"],
                lon=st["lon"],
                series=result["series"],
            )
            return result
    except Exception as e:
        logger.warning("UBA station data unavailable: %s", e)
    return None


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

@mcp.prompt(
    name="luftqualitaet",
    description="Luftqualitat an einem Standort analysieren - Saharastaub, SO2, PM2.5 als Zeitreihe",
)
def prompt_luftqualitaet(stadt: str = "", lat: str = "", lon: str = "") -> str:
    if stadt:
        return (
            f"Analysiere die aktuelle Luftqualitat in {stadt}. "
            "Nutze analyze_air_quality im auto-Modus fur eine vollstandige Zeitreihe "
            "mit Saharastaub, SO2 und PM2.5."
        )
    if lat and lon:
        return (
            f"Analysiere die aktuelle Luftqualitat bei {lat}N, {lon}E. "
            "Nutze analyze_air_quality im auto-Modus."
        )
    return (
        "Analysiere die aktuelle Luftqualitat an meinem Standort. "
        "Nutze analyze_air_quality im auto-Modus."
    )


@mcp.prompt(
    name="staedtevergleich",
    description="Luftqualitat mehrerer Stadte vergleichen - z.B. PM2.5 in Berlin, Munchen, Hamburg",
)
def prompt_staedtevergleich(staedte: str = "Berlin, Munchen, Hamburg") -> str:
    return (
        f"Vergleiche die Luftqualitat (PM2.5) dieser Stadte: {staedte}. "
        "Nutze compare_cities mit den Koordinaten der genannten Stadte."
    )


@mcp.prompt(
    name="saharastaub_lage",
    description="Aktuelle Saharastaub-Situation - Karte und Zeitreihe fur Deutschland",
)
def prompt_saharastaub() -> str:
    return (
        "Wie ist die aktuelle Saharastaub-Situation in Deutschland? "
        "Zeige zuerst eine Karte (show_air_quality_map, ca. 50N 10E) "
        "und dann eine Zeitreihe (analyze_air_quality) fur einen zentralen Standort."
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool(meta={"ui": {"resourceUri": TIMESERIES_URI}})
def analyze_air_quality(
    lat: float,
    lon: float,
    days: int = 7,
    city: str = "",
    mode: str = "auto",
) -> CallToolResult:
    """Zeitreihe fur Saharastaub, SO2 und PM2.5 an einem europaischen Standort.

    Empfohlener Einstieg fur jede Luftqualitats-Frage. Zeigt alle drei Schadstoffe
    als interaktive Zeitreihe. Im Auto-Modus werden validierte Analysedaten mit
    aktuellen Prognosedaten kombiniert und UBA-Stationsmessungen uberlagert (Deutschland).

    Args:
        lat: Breitengrad (z.B. 52.37 fur Hannover)
        lon: Langengrad (z.B. 9.73 fur Hannover)
        days: Anzahl Tage (Standard 7, max 30)
        city: Stadtname fur Anzeige
        mode: "auto" (Analyse + Prognose + Station, empfohlen),
              "analysis" (nur validierte Daten, ~48h Verzogerung),
              "forecast" (nur Prognose, nahezu Echtzeit)
    """
    days = min(max(1, days), 30)
    loc = Location(lat=lat, lon=lon, city=city or f"{lat:.2f}N, {lon:.2f}E")
    series: dict = {}
    date_from, date_to = cams.date_range(days)

    if mode in ("analysis", "auto"):
        analysis = _fetch_cams(loc, date_from, date_to, "analysis")
        if analysis:
            series = analysis

    if mode in ("forecast", "auto"):
        fc_from, fc_to = cams.date_range_forecast(days_back=2, days_ahead=3)
        forecast = _fetch_cams(loc, fc_from, fc_to, "forecast")
        if mode == "forecast":
            series = forecast or {}
        elif forecast:
            series = _stitch_analysis_forecast(series, forecast)

    if not series:
        return _error_result("Keine Daten verfugbar.", data_availability=remote.data_availability())

    all_times = [t for s in series.values() for t in s["time"]]
    actual_from = str(min(all_times))[:10] if all_times else str(date_from)
    actual_to   = str(max(all_times))[:10] if all_times else str(date_to)

    data: dict = {
        "lat": loc.lat, "lon": loc.lon, "city": loc.city,
        "days": days, "mode": mode, "today": _today_str(),
        "date_from": actual_from, "date_to": actual_to,
        "series": _serialize_series(series),
    }

    if mode != "forecast":
        station_result = _fetch_station_overlay(lat, lon, days)
        if station_result and station_result["station"]:
            data["station"]        = station_result["station"]
            data["station_series"] = station_result["series"]

    var_names    = [s["label"] for s in data["series"].values()]
    station_info = ""
    if data.get("station"):
        station_info = f" | UBA Station: {data['station']['name']} ({data['station']['distance_km']} km)"
    summary = (
        f"Luftqualitat {loc.city}: {', '.join(var_names)} | "
        f"{actual_from} bis {actual_to} ({mode}){station_info}"
    )
    return _ok_result(summary, data)


@mcp.tool(meta={"ui": {"resourceUri": MAP_URI}})
def show_air_quality_map(
    lat: float,
    lon: float,
    days: int = 3,
) -> CallToolResult:
    """Raumliche Verteilung von Saharastaub, SO2 und PM2.5 auf einer Europakarte.

    Zeigt Konzentrationen als farbige Marker in einem +-5-Grad-Bereich um den Standort.
    Alle drei Schadstoffe sind enthalten.

    Args:
        lat: Breitengrad (Kartenmitte)
        lon: Langengrad (Kartenmitte)
        days: Anzahl Tage (Standard 3)
    """
    days = min(max(1, days), 14)

    variables = remote.get_map_data(lat, lon, radius_deg=5.0)
    if not variables:
        return _error_result("Keine Kartendaten verfugbar.")

    last_ts = remote.get_last_timestamp() or _today_str()

    data = {
        "variables":  variables,
        "timestamp":  last_ts,
        "center_lat": lat,
        "center_lon": lon,
    }
    var_labels = [v["label"] for v in variables.values()]
    n_points   = sum(len(v["values"]) for v in variables.values())
    summary = f"Karte {lat:.1f}N {lon:.1f}E: {', '.join(var_labels)} | {n_points} Punkte | {last_ts}"
    return _ok_result(summary, data)


@mcp.tool(meta={"ui": {"resourceUri": COMPARE_URI}})
def compare_cities(
    cities: list[CityInput],
    variable: str = "pm2p5",
    days: int = 7,
) -> CallToolResult:
    """Luftqualitat mehrerer Stadte auf einer gemeinsamen Zeitachse vergleichen.

    Zeigt eine Kurve pro Stadt fur den gewahlten Schadstoff.

    Args:
        cities: Liste von Stadtobjekten, max 5. Jedes Objekt braucht:
                - lat: Breitengrad (float, z.B. 52.37)
                - lon: Langengrad (float, z.B. 9.73)
                - city: Stadtname (string, z.B. "Hannover")
                Beispiel: [{"lat": 52.37, "lon": 9.73, "city": "Hannover"},
                           {"lat": 53.55, "lon": 9.99, "city": "Hamburg"}]
        variable: Schadstoff - "dust", "so2" oder "pm2p5" (Standard)
        days: Anzahl Tage (Standard 7, max 30)
    """
    if variable not in cams.VARIABLES:
        return _error_result(f"Unbekannte Variable '{variable}'. Verfugbar: dust, so2, pm2p5")

    cities = cities[:5]
    days = min(max(1, days), 30)
    date_from, date_to = cams.date_range(days)
    _, _, label, _ = cams.VARIABLES[variable]

    city_results = []
    for c in cities:
        loc = Location(lat=c["lat"], lon=c["lon"], city=c.get("city", f"{c['lat']:.1f}N"))
        series = remote.get_timeseries(loc.lat, loc.lon, date_from, date_to, "analysis")
        if series and variable in series:
            s = series[variable]
            city_results.append({
                "city":   loc.city,
                "lat":    loc.lat,
                "lon":    loc.lon,
                "time":   [str(t) for t in s["time"]],
                "values": [float(v) for v in s["values"]],
            })

    if not city_results:
        return _error_result("Keine Daten fur die angefragten Stadte verfugbar.")

    data = {
        "variable":       variable,
        "variable_label": label,
        "days":           days,
        "today":          _today_str(),
        "date_from":      str(date_from),
        "date_to":        str(date_to),
        "cities":         city_results,
    }
    city_names = [c["city"] for c in city_results]
    summary = f"{label} Vergleich: {', '.join(city_names)} | {date_from} bis {date_to}"
    return _ok_result(summary, data)




@mcp.tool()
def query_measurements(
    lat: float,
    lon: float,
    variable: str = "dust",
    limit: int = 100,
) -> CallToolResult:
    """Messdaten aus dem CAMS-Datenarchiv abfragen (GitHub Release).

    Liest direkt aus dem remote Parquet via DuckDB httpfs.

    Args:
        lat: Breitengrad (+-1 Grad Toleranz)
        lon: Langengrad (+-1 Grad Toleranz)
        variable: "dust", "so2" oder "pm2p5"
        limit: Maximale Zeilen (Standard 100)
    """
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    try:
        rows = con.execute("""
            SELECT timestamp, lat, lon, level_m, variable, value, data_type
            FROM read_parquet(?)
            WHERE variable = ?
              AND lat BETWEEN ? AND ?
              AND lon BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, [remote.ANALYSIS_URL, variable,
              lat - 1, lat + 1, lon - 1, lon + 1, limit]).fetchall()
    except Exception as e:
        return _error_result(f"Remote-Abfrage fehlgeschlagen: {e}")
    finally:
        con.close()

    if not rows:
        return _error_result(
            f"Keine {variable}-Messungen fur {lat:.1f}N {lon:.1f}E im Datenarchiv."
        )

    data = {
        "count":   len(rows),
        "columns": ["timestamp", "lat", "lon", "level_m", "variable", "value", "data_type"],
        "rows":    [[str(c) if not isinstance(c, (int, float)) else c for c in row] for row in rows],
        "source":  "github-release",
    }
    summary = f"CAMS-Abfrage {variable} bei {lat:.1f}N {lon:.1f}E: {len(rows)} Zeilen"
    return _ok_result(summary, data)


def run_server():
    import argparse
    parser = argparse.ArgumentParser(description="dust-analyzer MCP server")
    parser.add_argument("--mcp", action="store_true", help="Run as MCP server (stdio)")
    args = parser.parse_args()
    if args.mcp:
        mcp.run(transport="stdio")
    else:
        mcp.run()
