# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CLI tool + MCP server for European air quality analysis (Saharan dust, SO₂, PM2.5) using CAMS/Copernicus data. MCP tools render interactive Plotly charts as MCP Apps in Claude Desktop. Live plot at [synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/).

## Commands

```bash
uv sync                                          # Install dependencies
uv run dust-analyzer                              # Run with IP geolocation
uv run dust-analyzer --lat 52.37 --lon 9.73       # Manual coordinates
uv run dust-analyzer --days 14                    # 14 days
uv run dust-analyzer --mcp                        # Start as MCP server (stdio)
```

No test suite exists. No linter configured.

## Architecture

```
src/dust_analyzer/
├── __init__.py   # Public library API
├── __main__.py   # CLI entry point
├── paths.py      # data/ and output/ directories
├── location.py   # Location dataclass + IP geolocation (ipapi.co)
├── remote.py     # DuckDB httpfs — reads Parquet from GitHub Release (no local download)
├── cams.py       # CAMS API download + NetCDF → Parquet conversion (CI only)
├── cache.py      # UBA station data in DuckDB (station_measurements table)
├── uba.py        # UBA Umweltbundesamt REST API — nearest-station lookup, hourly data
├── plot.py       # CLI Plotly subplots → standalone HTML
├── mcp_ui/       # MCP App HTML views (text/html;profile=mcp-app)
└── server.py     # MCP server — tools, resources, prompts
```

**Data flow (MCP):** Tool → `remote.get_timeseries()` (DuckDB httpfs from GitHub Release) → `CallToolResult.structuredContent` → MCP App HTML

**Data flow (CLI):** `parse_args()` → `resolve_location()` → `remote` or `cams.download()` → `plot.render()`

**Data flow (CI):** `cams.download()` → NetCDF → Parquet → GitHub Release `data-latest`

## MCP Tools

| Tool | Purpose | UI |
|------|---------|-----|
| `analyze_air_quality` | Time series: all 3 pollutants, auto analysis+forecast stitching, UBA overlay | Plotly line chart |
| `show_air_quality_map` | Spatial distribution ±5°, returns metadata; UI loads full data per variable via `get_map_variable` | Plotly scattergeo |
| `get_map_variable` | App-only tool (`visibility: ["app"]`): returns full grid data for one variable | Called by map UI |
| `compare_cities` | Multi-city comparison (max 5) on shared time axis | Plotly multi-trace |
| `query_measurements` | Query remote Parquet archive via DuckDB httpfs | JSON table |

Tools return `CallToolResult`: `content` = short text summary (for model context), `structuredContent` = full data (for UI only, not added to model context).

## MCP Prompts

| Prompt | Description |
|--------|------------|
| `luftqualitaet` | Analyze single location (city or coordinates) |
| `staedtevergleich` | Compare PM2.5 across cities |
| `saharastaub_lage` | Current Saharan dust situation with map + time series |

## Key internals

**Remote data** (`remote.py`): DuckDB httpfs reads `analysis.parquet` and `forecast.parquet` directly from `https://github.com/synapticore-io/dust-analyzer/releases/download/data-latest/`. No local CAMS download needed.

**CAMS variable mapping** (`cams.VARIABLES`): `(request_name, netcdf_name, label, color)`. Request names differ from NetCDF names (e.g., `sulphur_dioxide` → `so2_conc`).

**Data modes:** `analysis` (validated, ~48h latency), `forecast` (near-realtime, leadtimes 0-96h), `auto` (stitches both).

**UBA API** (`uba.py`): Public REST API, no auth. Nearest-station via Haversine.

**MCP Apps protocol** (SEP-1865): Resources with `text/html;profile=mcp-app`, tool meta `{"ui": {"resourceUri": "ui://..."}}`, CSP via `_meta.ui.csp`. App-only tools use `visibility: ["app"]`.

## External dependencies

- **CAMS API credentials** — only needed for CI (`update-data.yml`). MCP/CLI reads from GitHub Release.
- **UBA API** — no credentials, public.
- **GitHub Actions**: `update-data.yml` (13:30 UTC, uploads Parquet), `update-plot.yml` (14:00 UTC, deploys Pages). Both need `CAMS_API_KEY` secret.

## Library usage

- **DuckDB:** `INSTALL httpfs; LOAD httpfs;` then `read_parquet('https://...')` for remote reads.
- **MCP:** `from mcp.server.fastmcp import FastMCP`, `from mcp.types import CallToolResult, TextContent`.
- **Polars:** Used in `cams.py` for Parquet I/O. Not used in `server.py` or `remote.py`.

## Conventions

- German UI strings (chart labels, hover templates, error messages)
- `data/`, `output/`, `*.nc`, `*.duckdb`, `*.html` are gitignored (except `mcp_ui/*.html`)
- Python 3.11, uv, `uv_build` backend
