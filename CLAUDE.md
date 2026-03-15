# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CLI tool + MCP server that downloads CAMS European Air Quality data (Copernicus/ECMWF) and UBA station measurements for any European location, rendering interactive Plotly charts showing Saharan dust, SO₂, and PM2.5 time series. Live instance at [synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/).

## Commands

```bash
uv sync                                          # Install dependencies
uv run dust-analyzer                              # Run with IP geolocation
uv run dust-analyzer --lat 52.37 --lon 9.73       # Manual coordinates
uv run dust-analyzer --days 14 --no-cache         # 14 days, skip cache
uv run dust-analyzer --mcp                        # Start as MCP server (stdio)
```

No test suite exists. No linter configured.

## Architecture

```
src/dust_analyzer/
├── __init__.py   # Public library API
├── __main__.py   # CLI entry point, orchestrates: location → cache → download → extract → render
├── location.py   # Location dataclass + IP geolocation (ipapi.co) + argparse
├── cams.py       # CAMS API download (cdsapi) — analysis + forecast mode — NetCDF extraction (xarray)
├── cache.py      # DuckDB cache — timeseries + measurements + station_measurements tables
├── uba.py        # UBA Umweltbundesamt REST API — real-time station data (no auth), nearest-station lookup
├── plot.py       # Plotly subplots (dark theme, responsive) → standalone HTML (CLI mode)
└── server.py     # MCP server — 4 tools with MCP Apps Plotly visualizations
```

**Data flow (MCP):** `analyze_air_quality()` → `_fetch_cams(analysis)` → `_stitch_analysis_forecast(forecast)` → `_fetch_station_overlay(uba)` → JSON → MCP App HTML

**Data flow (CLI):** `parse_args()` → `resolve_location()` → `cache.get()` → if miss: `cams.download()` → `cams.extract()` → `cache.put()` → `plot.render()`

## MCP Tools (4 tools, focused)

| Tool | Purpose | Visualization |
|------|---------|---------------|
| `analyze_air_quality` | Time series: dust/SO₂/PM2.5 with auto UBA station overlay, auto analysis+forecast stitching | Plotly subplots |
| `show_pollution_map` | Spatial distribution of a single variable | Plotly scattergeo |
| `compare_cities` | Multi-city comparison (max 5) on shared time axis | Plotly multi-trace |
| `query_measurements` | Raw DuckDB cache query for downstream analysis | JSON table |

All tools compute date ranges automatically from today's date. No manual dates needed.

Station lookup, forecast stitching, and data availability diagnostics are internal — not exposed as separate tools.

## Key internals

**CAMS variable mapping** (`cams.VARIABLES`): Each entry is `(request_name, netcdf_name, label, color)`. Request names differ from NetCDF variable names (e.g., `sulphur_dioxide` → `so2_conc`).

**Data modes:**
- `analysis` — validated, ~48h latency, same dataset with `type: ["analysis"]`
- `forecast` — near-realtime, same dataset with `type: ["forecast"]`, leadtimes 0-96h
- `auto` — stitches analysis + forecast at boundary, recommended default

**UBA API** (`uba.py`): Public REST API, no auth required. Automatic nearest-station matching via Haversine. Components: PM2.5, PM10, SO₂, NO₂, O₃.

**Cache key format**: `"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}_{data_type}"` — includes data_type to separate analysis/forecast.

**DuckDB tables**: `timeseries` (CAMS cache), `measurements` (volumetric), `station_measurements` (UBA)

## External dependencies

- **CAMS API credentials** required in `~/.cdsapirc` (url + key). Covers both analysis and forecast data (same dataset). Dataset licence must be accepted once in browser.
- **UBA API** — no credentials required, public API.
- **GitHub Actions** (`.github/workflows/update-plot.yml`): daily at 14:00 UTC, deploys to GitHub Pages. Requires `CAMS_API_KEY` repository secret.

## Conventions

- German UI strings (print messages, chart labels, hover templates)
- Output files (`.nc`, `.duckdb`, `.html`) are gitignored — generated locally or in CI
- Python 3.11, uv as package manager, `uv_build` backend
- All imports at module top level
- WHO thresholds rendered as reference lines in charts (PM2.5: 15, SO₂: 40 µg/m³)
