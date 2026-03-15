"""
MCP Server for dust-analyzer — exposes CAMS + UBA air quality data as interactive Plotly charts.
Uses MCP Apps to render charts directly in Claude Desktop.
"""

import json
import logging
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import xarray as xr
from mcp.server.fastmcp import FastMCP

from dust_analyzer import cams, cache, uba
from dust_analyzer.location import Location

logger = logging.getLogger(__name__)

TIMESERIES_URI = "ui://dust-analyzer/timeseries.html"
MAP_URI = "ui://dust-analyzer/map.html"
COMPARE_URI = "ui://dust-analyzer/compare.html"

mcp = FastMCP(
    "dust-analyzer",
    instructions=(
        "Air quality analysis tool using CAMS/Copernicus data and UBA station measurements. "
        "Provides Saharan dust, SO₂, and PM2.5 time series for any European location. "
        "Supports analysis data (validated, ~48h latency), forecast data (near-realtime), "
        "and UBA ground-truth station overlay (hourly, Germany only). "
        "All date ranges are computed automatically from today's date — no manual dates needed."
    ),
)

# ---------------------------------------------------------------------------
# HTML templates for MCP App resources
# ---------------------------------------------------------------------------

TIMESERIES_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f1117; color: #e0e0e0; font-family: system-ui, sans-serif; padding: 16px; }
  h2 { font-size: 16px; margin-bottom: 8px; color: #e0e0e0; }
  .meta { font-size: 12px; color: #888; margin-bottom: 12px; }
  .meta a { color: #7eb8d4; }
  .station-info { font-size: 12px; color: #aaa; margin-bottom: 8px; padding: 6px 10px;
    background: rgba(126,184,212,0.08); border-left: 3px solid #7eb8d4; border-radius: 3px; }
  #chart { width: 100%; height: 700px; }
  .error { color: #e05252; padding: 20px; }
</style>
</head>
<body>
<h2 id="title">Air Quality — loading...</h2>
<div class="meta">
  Source: <a href="https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts" target="_blank">CAMS European Air Quality Forecasts</a>
  · Surface level (ensemble)
</div>
<div id="station-info" class="station-info" style="display:none"></div>
<div id="chart"></div>
<div id="error" class="error" style="display:none"></div>
<script type="module">
import { App } from "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";

const app = new App({ name: "Dust Analyzer Timeseries", version: "2.0.0" });

app.ontoolresult = ({ content }) => {
  try {
    const textBlock = content?.find(c => c.type === 'text');
    if (!textBlock) return;
    const data = JSON.parse(textBlock.text);

    const modeLabel = data.mode === 'forecast' ? ' (forecast)' :
                      data.mode === 'auto' ? '' : ' (analysis only)';
    document.getElementById('title').textContent =
      `Air Quality · ${data.city} (${data.lat.toFixed(2)}°N, ${data.lon.toFixed(2)}°E) · `
      + `${data.date_from} → ${data.date_to}${modeLabel}`;

    if (data.station) {
      const s = data.station;
      document.getElementById('station-info').style.display = 'block';
      document.getElementById('station-info').textContent =
        `UBA Station: ${s.name} (${s.code}) · ${s.distance_km} km entfernt · dashed = station`;
    }

    const variables = data.series;
    const keys = Object.keys(variables);
    const traces = [];
    const n = keys.length;

    keys.forEach((key, idx) => {
      const v = variables[key];
      const hex = v.color;
      const r = parseInt(hex.slice(1,3), 16);
      const g = parseInt(hex.slice(3,5), 16);
      const b = parseInt(hex.slice(5,7), 16);

      traces.push({
        x: v.time, y: v.values,
        name: v.label,
        type: 'scatter', mode: 'lines',
        line: { color: `rgba(${r},${g},${b},0.9)`, width: 2 },
        fill: 'tozeroy',
        fillcolor: `rgba(${r},${g},${b},0.12)`,
        xaxis: idx === 0 ? 'x' : `x${idx + 1}`,
        yaxis: idx === 0 ? 'y' : `y${idx + 1}`,
        hovertemplate: '<b>%{x|%d.%m. %H:%M}</b><br>%{y:.2f} µg/m³<extra>' + v.label + ' (CAMS)</extra>'
      });
    });

    const stationSeries = data.station_series || {};
    Object.keys(stationSeries).forEach(sKey => {
      const sv = stationSeries[sKey];
      const matchIdx = keys.indexOf(sKey);
      if (matchIdx < 0) return;

      const hex = sv.color;
      const r = parseInt(hex.slice(1,3), 16);
      const g = parseInt(hex.slice(3,5), 16);
      const b = parseInt(hex.slice(5,7), 16);

      traces.push({
        x: sv.time, y: sv.values,
        name: sv.label + ' (UBA)',
        type: 'scatter', mode: 'lines+markers',
        line: { color: `rgba(${r},${g},${b},0.7)`, width: 1.5, dash: 'dot' },
        marker: { size: 3, color: `rgba(${r},${g},${b},0.5)` },
        xaxis: matchIdx === 0 ? 'x' : `x${matchIdx + 1}`,
        yaxis: matchIdx === 0 ? 'y' : `y${matchIdx + 1}`,
        hovertemplate: '<b>%{x|%d.%m. %H:%M}</b><br>%{y:.2f} µg/m³<extra>' + sv.label + ' (UBA)</extra>'
      });
    });

    const layout = {
      template: 'plotly_dark',
      paper_bgcolor: '#0f1117',
      plot_bgcolor: '#131720',
      showlegend: Object.keys(stationSeries).length > 0,
      legend: { x: 0, y: 1.02, orientation: 'h', font: { size: 11, color: '#aaa' } },
      hovermode: 'x unified',
      margin: { t: 20, b: 50, l: 55, r: 20 },
    };

    keys.forEach((key, idx) => {
      const v = variables[key];
      const xKey = idx === 0 ? 'xaxis' : `xaxis${idx + 1}`;
      const yKey = idx === 0 ? 'yaxis' : `yaxis${idx + 1}`;
      layout[yKey] = {
        title: { text: v.label, font: { size: 11, color: '#888' } },
        tickfont: { size: 11, color: '#aaa' },
        gridcolor: 'rgba(255,255,255,0.05)',
        domain: [1 - (idx + 1) / n + 0.02, 1 - idx / n - 0.02]
      };
      layout[xKey] = {
        tickfont: { size: 11, color: '#aaa' },
        gridcolor: 'rgba(255,255,255,0.05)',
        tickformat: '%d.%m.\\n%H:%M',
        anchor: yKey.replace('axis', ''),
        showticklabels: idx === n - 1
      };
    });

    // WHO threshold shapes
    const thresholds = { pm2p5: 15, so2: 40, pm10: 50 };
    const shapes = [];
    keys.forEach((key, idx) => {
      if (thresholds[key]) {
        shapes.push({
          type: 'line', x0: 0, x1: 1, xref: 'paper',
          y0: thresholds[key], y1: thresholds[key],
          yref: idx === 0 ? 'y' : `y${idx + 1}`,
          line: { color: 'rgba(255,100,100,0.3)', width: 1, dash: 'dash' },
        });
      }
    });
    layout.shapes = shapes;

    Plotly.newPlot('chart', traces, layout, {
      responsive: true, displayModeBar: true, displaylogo: false,
      modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d']
    });

  } catch (e) {
    document.getElementById('error').style.display = 'block';
    document.getElementById('error').textContent = 'Error: ' + e.message;
  }
};

await app.connect();
</script>
</body>
</html>"""


MAP_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f1117; color: #e0e0e0; font-family: system-ui, sans-serif; padding: 16px; }
  h2 { font-size: 16px; margin-bottom: 12px; }
  #map { width: 100%; height: 700px; }
  .error { color: #e05252; padding: 20px; }
</style>
</head>
<body>
<h2 id="title">Pollution Map — loading...</h2>
<div id="map"></div>
<div id="error" class="error" style="display:none"></div>
<script type="module">
import { App } from "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";

const app = new App({ name: "Dust Analyzer Map", version: "1.0.0" });

app.ontoolresult = ({ content }) => {
  try {
    const textBlock = content?.find(c => c.type === 'text');
    if (!textBlock) return;
    const data = JSON.parse(textBlock.text);

    document.getElementById('title').textContent =
      `${data.variable_label} · ${data.timestamp}`;

    Plotly.newPlot('map', [{
      type: 'scattergeo',
      lat: data.lats, lon: data.lons,
      text: data.values.map((v, i) =>
        `${v.toFixed(2)} µg/m³<br>${data.lats[i].toFixed(2)}°N, ${data.lons[i].toFixed(2)}°E`),
      marker: {
        size: 8, color: data.values,
        colorscale: data.colorscale || 'YlOrRd',
        colorbar: { title: 'µg/m³', tickfont: { color: '#aaa' }, titlefont: { color: '#aaa' } },
        cmin: 0, cmax: Math.max(...data.values) * 1.1 || 1
      },
      hovertemplate: '%{text}<extra></extra>'
    }], {
      template: 'plotly_dark', paper_bgcolor: '#0f1117',
      geo: {
        scope: 'europe', bgcolor: '#131720', lakecolor: '#131720', landcolor: '#1a1f2e',
        center: { lat: data.center_lat, lon: data.center_lon },
        projection: { scale: data.scale || 4 },
        showland: true, showlakes: true,
        countrycolor: 'rgba(255,255,255,0.15)', coastlinecolor: 'rgba(255,255,255,0.2)'
      },
      margin: { t: 10, b: 10, l: 10, r: 10 }
    }, { responsive: true, displaylogo: false });

  } catch (e) {
    document.getElementById('error').style.display = 'block';
    document.getElementById('error').textContent = 'Error: ' + e.message;
  }
};

await app.connect();
</script>
</body>
</html>"""


COMPARE_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="color-scheme" content="light dark">
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0f1117; color: #e0e0e0; font-family: system-ui, sans-serif; padding: 16px; }
  h2 { font-size: 16px; margin-bottom: 12px; }
  #chart { width: 100%; height: 700px; }
  .error { color: #e05252; padding: 20px; }
</style>
</head>
<body>
<h2 id="title">City Comparison — loading...</h2>
<div id="chart"></div>
<div id="error" class="error" style="display:none"></div>
<script type="module">
import { App } from "https://unpkg.com/@modelcontextprotocol/ext-apps@0.4.0/app-with-deps";

const app = new App({ name: "Dust Analyzer Compare", version: "1.0.0" });
const COLORS = ['#7eb8d4', '#e05252', '#c8a96e', '#6ecf72', '#d4a07e'];

app.ontoolresult = ({ content }) => {
  try {
    const textBlock = content?.find(c => c.type === 'text');
    if (!textBlock) return;
    const data = JSON.parse(textBlock.text);

    document.getElementById('title').textContent =
      `${data.variable_label} · ${data.cities.map(c => c.city).join(' vs ')} · ${data.date_from} → ${data.date_to}`;

    const traces = data.cities.map((city, i) => {
      const c = COLORS[i % COLORS.length];
      const r = parseInt(c.slice(1,3), 16), g = parseInt(c.slice(3,5), 16), b = parseInt(c.slice(5,7), 16);
      return {
        x: city.time, y: city.values, name: city.city,
        type: 'scatter', mode: 'lines',
        line: { color: `rgba(${r},${g},${b},0.9)`, width: 2 },
        fill: 'tozeroy', fillcolor: `rgba(${r},${g},${b},0.08)`,
        hovertemplate: '<b>%{x|%d.%m. %H:%M}</b><br>%{y:.2f} µg/m³<extra>' + city.city + '</extra>'
      };
    });

    Plotly.newPlot('chart', traces, {
      template: 'plotly_dark', paper_bgcolor: '#0f1117', plot_bgcolor: '#131720',
      showlegend: true, legend: { x: 0, y: 1.02, orientation: 'h', font: { size: 12, color: '#ccc' } },
      hovermode: 'x unified',
      yaxis: { title: { text: data.variable_label, font: { size: 12, color: '#888' } },
               tickfont: { size: 11, color: '#aaa' }, gridcolor: 'rgba(255,255,255,0.05)' },
      xaxis: { tickfont: { size: 11, color: '#aaa' }, gridcolor: 'rgba(255,255,255,0.05)',
               tickformat: '%d.%m.\\n%H:%M' },
      margin: { t: 20, b: 50, l: 55, r: 20 },
    }, { responsive: true, displayModeBar: true, displaylogo: false });

  } catch (e) {
    document.getElementById('error').style.display = 'block';
    document.getElementById('error').textContent = 'Error: ' + e.message;
  }
};

await app.connect();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# UI Resources (MCP Apps spec)
# ---------------------------------------------------------------------------

@mcp.resource(
    TIMESERIES_URI,
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": ["https://cdn.plot.ly", "https://unpkg.com"]}}},
)
def timeseries_resource() -> str:
    return TIMESERIES_HTML


@mcp.resource(
    MAP_URI,
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": ["https://cdn.plot.ly", "https://unpkg.com"]}}},
)
def map_resource() -> str:
    return MAP_HTML


@mcp.resource(
    COMPARE_URI,
    mime_type="text/html;profile=mcp-app",
    meta={"ui": {"csp": {"resourceDomains": ["https://cdn.plot.ly", "https://unpkg.com"]}}},
)
def compare_resource() -> str:
    return COMPARE_HTML


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _serialize_series(series: dict[str, dict]) -> dict:
    """Convert numpy arrays to JSON-serializable lists."""
    out = {}
    for key, data in series.items():
        out[key] = {
            "time": [str(t) for t in data["time"]],
            "values": [float(v) for v in data["values"]],
            "label": data["label"],
            "color": data["color"],
        }
    return out


def _sort_dedup_series(series: dict[str, dict], keep: str = "first") -> dict[str, dict]:
    """Sort time series by timestamp and remove duplicates.

    keep="first" → first occurrence wins (analysis over forecast).
    keep="last"  → last occurrence wins (latest forecast run).
    """
    for data in series.values():
        times = data["time"]
        values = data["values"]
        sort_idx = np.argsort(times)
        times = times[sort_idx]
        values = values[sort_idx]
        if keep == "last":
            mask = np.concatenate([times[:-1] != times[1:], [True]])
        else:
            mask = np.concatenate([[True], times[1:] != times[:-1]])
        data["time"] = times[mask]
        data["values"] = values[mask]
    return series


def _fetch_cams(loc: Location, date_from, date_to, data_type="analysis"):
    """Download + extract CAMS data, with cache. Internal only."""
    cached = cache.get(loc.lat, loc.lon, date_from, date_to, data_type)
    if cached:
        series = {}
        for key, df in cached.items():
            if key not in cams.VARIABLES:
                continue
            _, _, label, color = cams.VARIABLES[key]
            series[key] = {
                "time": df["time"].values,
                "values": df["value"].values,
                "label": label,
                "color": color,
            }
        return _sort_dedup_series(series, keep="last")

    nc_path = cams.download(loc, date_from, date_to, data_type=data_type)
    series = cams.extract(nc_path, loc, date_from)
    if series:
        if data_type == "forecast":
            series = _sort_dedup_series(series, keep="last")
        cache.put(loc.lat, loc.lon, date_from, date_to, series, data_type)
    return series


def _fetch_station_overlay(lat: float, lon: float, days: int) -> dict | None:
    """Fetch UBA station data for overlay. Returns None if unavailable. Internal only."""
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


def _stitch_analysis_forecast(analysis: dict, forecast: dict) -> dict:
    """Stitch analysis + forecast at boundary. Analysis wins on overlap. Internal only."""
    series = dict(analysis) if analysis else {}
    if not forecast:
        return series

    for key, fc_data in forecast.items():
        if key in series and len(series[key]["time"]) > 0:
            series[key] = {
                "time": np.concatenate([series[key]["time"], fc_data["time"]]),
                "values": np.concatenate([series[key]["values"], fc_data["values"]]),
                "label": series[key]["label"],
                "color": series[key]["color"],
            }
        elif key not in series:
            series[key] = fc_data

    return _sort_dedup_series(series, keep="first")


def _today_str() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# Tools — 4 focused tools, no redundancy
# ---------------------------------------------------------------------------

@mcp.tool(meta={
    "ui": {"resourceUri": TIMESERIES_URI},
    "ui/resourceUri": TIMESERIES_URI,
})
def analyze_air_quality(
    lat: float,
    lon: float,
    days: int = 7,
    city: str = "",
    mode: str = "auto",
) -> str:
    """Analyze Saharan dust, SO₂, and PM2.5 for a European location.

    Downloads CAMS data and renders an interactive time series chart.
    Date range is computed automatically from today.
    In 'auto' mode, analysis data (~48h latency) is extended with forecast data
    for the most recent days, and UBA station measurements are overlaid as
    ground-truth (Germany only, automatic nearest-station lookup).

    Requires CAMS API credentials in ~/.cdsapirc.

    Args:
        lat: Latitude (e.g. 52.37 for Hannover)
        lon: Longitude (e.g. 9.73 for Hannover)
        days: Number of days to analyze (default 7, max 30)
        city: Optional city name for display
        mode: "auto" (analysis + forecast + station, recommended),
              "analysis" (validated only, ~48h lag),
              "forecast" (near-realtime only)
    """
    days = min(max(1, days), 30)
    loc = Location(lat=lat, lon=lon, city=city or f"{lat:.2f}°N, {lon:.2f}°E")

    series = {}
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
        avail = cache.data_availability()
        return json.dumps({"error": "No data available.", "data_availability": avail})

    # Compute actual date range from data for display
    all_times = [t for s in series.values() for t in s["time"]]
    actual_from = str(min(all_times))[:10] if all_times else str(date_from)
    actual_to = str(max(all_times))[:10] if all_times else str(date_to)

    result = {
        "lat": loc.lat,
        "lon": loc.lon,
        "city": loc.city,
        "days": days,
        "mode": mode,
        "today": _today_str(),
        "date_from": actual_from,
        "date_to": actual_to,
        "series": _serialize_series(series),
    }

    # Auto UBA station overlay (internal, no separate tool needed)
    if mode != "forecast":
        station_result = _fetch_station_overlay(lat, lon, days)
        if station_result and station_result["station"]:
            result["station"] = station_result["station"]
            result["station_series"] = station_result["series"]

    return json.dumps(result)


@mcp.tool(meta={
    "ui": {"resourceUri": MAP_URI},
    "ui/resourceUri": MAP_URI,
})
def show_pollution_map(
    lat: float,
    lon: float,
    variable: str = "dust",
    days: int = 3,
) -> str:
    """Show spatial distribution of a pollutant on a map.

    Downloads CAMS data for an area around the location and shows
    concentration values as colored markers on a European map.
    Date range computed automatically from today.

    Args:
        lat: Center latitude
        lon: Center longitude
        variable: One of "dust", "so2", "pm2p5" (default: dust)
        days: Days of data (default 3)
    """
    if variable not in cams.VARIABLES:
        return json.dumps({"error": f"Unknown variable '{variable}'. Use: dust, so2, pm2p5"})

    days = min(max(1, days), 14)
    loc = Location(lat=lat, lon=lon, city="")
    date_from, date_to = cams.date_range(days)

    nc_path = cams.download(loc, date_from, date_to)
    ds = xr.open_dataset(nc_path, decode_timedelta=False)

    _, nc_var, label, _ = cams.VARIABLES[variable]
    if nc_var not in ds:
        ds.close()
        return json.dumps({"error": f"Variable {nc_var} not in downloaded data."})

    timestamps = cams._parse_time_axis(ds, date_from)
    da = ds[nc_var]

    non_time = [d for d in da.dims if d not in ("time", "latitude", "longitude")]
    if non_time:
        da = da.isel({d: 0 for d in non_time})
    da_latest = da.isel(time=-1)

    lats_grid, lons_grid = np.meshgrid(
        ds["latitude"].values.astype(float),
        ds["longitude"].values.astype(float),
        indexing="ij",
    )
    vals = da_latest.values.flatten().astype(float)
    lats_flat = lats_grid.flatten().tolist()
    lons_flat = lons_grid.flatten().tolist()

    valid = [
        (la, lo, v) for la, lo, v in zip(lats_flat, lons_flat, vals.tolist())
        if np.isfinite(v)
    ]
    if not valid:
        ds.close()
        return json.dumps({"error": "No valid data points."})

    lats_out, lons_out, vals_out = zip(*valid)
    ds.close()

    colorscales = {"dust": "YlOrBr", "so2": "Reds", "pm2p5": "Blues"}

    return json.dumps({
        "variable_label": label,
        "timestamp": str(timestamps[-1]),
        "center_lat": lat,
        "center_lon": lon,
        "lats": list(lats_out),
        "lons": list(lons_out),
        "values": list(vals_out),
        "colorscale": colorscales.get(variable, "YlOrRd"),
        "scale": 4,
    })


@mcp.tool(meta={
    "ui": {"resourceUri": COMPARE_URI},
    "ui/resourceUri": COMPARE_URI,
})
def compare_cities(
    cities: list[dict],
    variable: str = "pm2p5",
    days: int = 7,
) -> str:
    """Compare air quality across multiple cities on a shared time axis.

    Renders one trace per city for the selected variable.
    Date range computed automatically from today.

    Args:
        cities: List of {lat, lon, city} dicts, max 5.
                Example: [{"lat": 52.37, "lon": 9.73, "city": "Hannover"},
                          {"lat": 53.55, "lon": 9.99, "city": "Hamburg"}]
        variable: One of "dust", "so2", "pm2p5" (default: pm2p5)
        days: Number of days (default 7, max 30)
    """
    if variable not in cams.VARIABLES:
        return json.dumps({"error": f"Unknown variable '{variable}'. Use: dust, so2, pm2p5"})

    cities = cities[:5]
    days = min(max(1, days), 30)
    date_from, date_to = cams.date_range(days)
    _, _, label, _ = cams.VARIABLES[variable]

    lats = [c["lat"] for c in cities]
    lons = [c["lon"] for c in cities]
    bbox = [max(lats) + 1, min(lons) - 1, min(lats) - 1, max(lons) + 1]  # N, W, S, E
    anchor = Location(lat=lats[0], lon=lons[0], city="compare")
    nc_path = cams.download(anchor, date_from, date_to, area=bbox)
    ds_timestamps = None

    city_results = []
    for c in cities:
        loc = Location(lat=c["lat"], lon=c["lon"], city=c.get("city", f"{c['lat']:.1f}°N"))
        series = cams.extract(nc_path, loc, date_from)
        if series and variable in series:
            city_results.append({
                "city": loc.city,
                "lat": loc.lat,
                "lon": loc.lon,
                "time": [str(t) for t in series[variable]["time"]],
                "values": [float(v) for v in series[variable]["values"]],
            })

    if not city_results:
        return json.dumps({"error": "No data available for any of the requested cities."})

    return json.dumps({
        "variable": variable,
        "variable_label": label,
        "days": days,
        "today": _today_str(),
        "date_from": str(date_from),
        "date_to": str(date_to),
        "cities": city_results,
    })


@mcp.tool()
def query_measurements(
    lat: float,
    lon: float,
    variable: str = "dust",
    limit: int = 100,
) -> str:
    """Query cached air quality measurements from DuckDB.

    Returns tabular data from previously downloaded CAMS measurements.
    No API call — only reads from local cache.

    Args:
        lat: Latitude to filter (±1° tolerance)
        lon: Longitude to filter (±1° tolerance)
        variable: One of "dust", "so2", "pm2p5"
        limit: Max rows to return (default 100)
    """
    db_path = cache.DB_FILE
    if not db_path.exists():
        return json.dumps({"error": "No cache database found. Run analyze_air_quality first."})

    con = duckdb.connect(str(db_path), read_only=True)

    try:
        tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
        if "measurements" not in tables:
            return json.dumps({"error": "No measurements table. Run analyze_air_quality first."})

        rows = con.execute(
            """SELECT timestamp, latitude, longitude, level_m, variable, value, unit
            FROM measurements
            WHERE variable = ?
              AND latitude BETWEEN ? AND ?
              AND longitude BETWEEN ? AND ?
            ORDER BY timestamp DESC
            LIMIT ?""",
            [variable, lat - 1, lat + 1, lon - 1, lon + 1, limit],
        ).fetchall()

        return json.dumps({
            "count": len(rows),
            "columns": ["timestamp", "latitude", "longitude", "level_m", "variable", "value", "unit"],
            "rows": [
                [str(c) if not isinstance(c, (int, float)) else c for c in row]
                for row in rows
            ],
        })
    finally:
        con.close()


def run_server():
    """Run the MCP server (stdio transport)."""
    mcp.run()
