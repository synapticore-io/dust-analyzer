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

**MCP (Cursor):** Use **`uv run --directory <repo> python -m dust_analyzer --mcp`** (or `uv run` from repo root) — [uv project run](https://docs.astral.sh/uv/concepts/projects/run/). Do not use **`uv run --no-sync`** (skips env sync). **`uvx`** is for PyPI tools, not this workflow.

No test suite exists. No linter configured.

## Architecture

```
src/dust_analyzer/
├── __init__.py   # Public library API
├── __main__.py   # CLI entry point, orchestrates: location → cache → download → extract → render
├── paths.py      # data/ (NetCDF + DuckDB) and output/ (HTML) — relative to cwd
├── location.py   # Location dataclass + IP geolocation (ipapi.co) + argparse
├── cams.py       # CAMS API download (cdsapi) — analysis + forecast mode — NetCDF extraction (xarray)
├── cache.py      # DuckDB cache — timeseries + measurements + station_measurements tables
├── uba.py        # UBA Umweltbundesamt REST API — real-time station data (no auth), nearest-station lookup
├── plot.py       # Plotly subplots (dark theme, responsive) → standalone HTML (CLI mode)
├── mcp_ui/       # MCP App views: `*.html` (`text/html;profile=mcp-app`), loaded by `load_mcp_html()`
└── server.py     # MCP server — tools + `resources/read` for `ui://…` (HTML from `mcp_ui/`)
```

**Data flow (MCP):** `analyze_air_quality()` → `_fetch_cams(analysis)` → `_stitch_analysis_forecast(forecast)` → `_fetch_station_overlay(uba)` → JSON → MCP App HTML

**Data flow (CLI):** `parse_args()` → `resolve_location()` → `cache.get()` → if miss: `cams.download()` → `cams.extract()` → `cache.put()` → `plot.render()`

## MCP Tools (4 tools, focused)

| Tool | Wann nutzen | UI |
|------|-------------|-----|
| `analyze_air_quality` | Einzelstandort — Zeitreihe aller 3 Schadstoffe mit UBA-Overlay + Forecast-Stitching | Plotly subplots |
| `show_air_quality_map` | Räumliche Verteilung — Heatmap auf OSM ±5° um Standort, Dropdown für Variable | Plotly Densitymapbox + OpenStreetMap |
| `compare_cities` | Mehrere Städte (max 5) — eine Variable auf gemeinsamer Zeitachse | Plotly multi-trace |
| `query_measurements` | Cache-Abfrage — kein API-Call, setzt vorherigen Download voraus | JSON table |

All tools compute date ranges automatically from today's date. No manual dates needed.

Station lookup, forecast stitching, and data availability diagnostics are internal — not exposed as separate tools.

## MCP Prompts (3 Einstiegspunkte)

| Prompt | Beschreibung |
|--------|-------------|
| `luftqualitaet` | Einzelstandort analysieren (Stadt oder Koordinaten) |
| `staedtevergleich` | PM2.5 mehrerer Städte vergleichen |
| `saharastaub_lage` | Aktuelle Saharastaub-Situation mit Karte + Zeitreihe |

## Key internals

**CAMS variable mapping** (`cams.VARIABLES`): Each entry is `(request_name, netcdf_name, label, color)`. Request names differ from NetCDF variable names (e.g., `sulphur_dioxide` → `so2_conc`).

**Data modes:**
- `analysis` — validated, ~48h latency, same dataset with `type: ["analysis"]`
- `forecast` — near-realtime, same dataset with `type: ["forecast"]`, leadtimes 0-96h
- `auto` — stitches analysis + forecast at boundary, recommended default

**UBA API** (`uba.py`): Public REST API, no auth required. Automatic nearest-station matching via Haversine. Components: PM2.5, PM10, SO₂, NO₂, O₃.

**Cache key format**: `"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}_{data_type}"` — includes data_type to separate analysis/forecast.

**Local cache**: CAMS as Parquet under `data/cams_*.parquet`; UBA station rows in DuckDB table `station_measurements` (`dust_cache.duckdb`).

## External dependencies

- **CAMS API credentials** required in `~/.cdsapirc` (url + key). Covers both analysis and forecast data (same dataset). Dataset licence must be accepted once in browser.
- **UBA API** — no credentials required, public API.
- **GitHub Actions** (`.github/workflows/update-plot.yml`): daily at 14:00 UTC, deploys to GitHub Pages. Requires `CAMS_API_KEY` repository secret.

## Library usage (don’t guess)

- **xarray:** Use **`Dataset.sizes`** / **`DataArray.sizes`** for iterating dimensions and **`in da.sizes`** checks — aligned with current [xarray API](https://docs.xarray.dev/en/stable/generated/xarray.Dataset.sizes.html).
- **MCP:** `from mcp.server.fastmcp import FastMCP` — [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (`mcp` on PyPI). Run the project with **`uv run`**, not **`uv tool run` / `uvx`**.

## Conventions

- German UI strings (print messages, chart labels, hover templates)
- **Paths:** NetCDF + `dust_cache.duckdb` under `data/`; CLI HTML under `output/` (default `output/dust_analysis.html`). CI may pass `--out _site/index.html` for Pages.
- `data/`, `output/`, and loose `*.nc` / `*.duckdb` / `*.html` are gitignored — generated locally or in CI
- Python 3.11, uv as package manager, `uv_build` backend
- All imports at module top level
- WHO thresholds rendered as reference lines in charts (PM2.5: 15, SO₂: 40 µg/m³)
