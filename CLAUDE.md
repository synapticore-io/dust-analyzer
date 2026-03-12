# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

CLI tool that downloads CAMS European Air Quality analysis data (Copernicus/ECMWF) for any European location and renders an interactive Plotly chart showing Saharan dust, SO₂, and PM2.5 time series. Live instance at [synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/).

## Commands

```bash
uv sync                                          # Install dependencies
uv run dust-analyzer                              # Run with IP geolocation
uv run dust-analyzer --lat 52.37 --lon 9.73       # Manual coordinates
uv run dust-analyzer --days 14 --no-cache         # 14 days, skip cache
```

No test suite exists. No linter configured.

## Architecture

```
src/dust_analyzer/
├── __init__.py   # Public library API (download/extract/date_range/Location/render)
├── __main__.py   # CLI entry point, orchestrates: location → cache check → download → extract → render
├── location.py   # Location dataclass + IP geolocation (ipapi.co) + argparse
├── cams.py       # CAMS API download (cdsapi) + NetCDF extraction (xarray)
├── cache.py      # DuckDB cache — keyed by lat/lon/date range, avoids re-downloads and stores 3D measurements for notebooks
├── plot.py       # Plotly subplots (dark theme, responsive) → standalone HTML
```

**Data flow:** `parse_args()` → `resolve_location()` → `cache.get()` → if miss: `cams.download()` → `cams.extract()` → `cache.put()` → `plot.render()`

**CAMS variable mapping** (`cams.VARIABLES`): Each entry is `(request_name, netcdf_name, label, color)`. Request names differ from NetCDF variable names (e.g., `sulphur_dioxide` → `so2_conc`).

**Time axis**: NetCDF stores time as float32 hours since a reference date. `_parse_time_axis()` converts to datetime64 using the `long_name` attribute.

**Cache key format**: `"{lat:.2f}_{lon:.2f}_{date_from}_{date_to}"` — same format used for NetCDF filenames.

## Notebooks & examples

- `examples/dust_explorer.py`: Marimo notebook for interactive exploration (surface time series + 3D volumetric measurements from the DuckDB cache).

## External dependencies

- **CAMS API credentials** required in `~/.cdsapirc` (url + key). Dataset licence must be accepted once in browser.
- **GitHub Actions** (`.github/workflows/update-plot.yml`): daily at 10:00 UTC, deploys to GitHub Pages. Requires `CAMS_API_KEY` repository secret.

## Conventions

- German UI strings (print messages, chart labels, hover templates)
- Output files (`.nc`, `.duckdb`, `.html`) are gitignored — generated locally or in CI
- Python 3.11, uv as package manager, `uv_build` backend
