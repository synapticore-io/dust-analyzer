# dust-analyzer

Analyzes **Saharan dust, SO₂ and PM2.5** for any European location.  
Data source: [CAMS European Air Quality Forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts) (Copernicus / ECMWF).

## Live Plot — Hannover, last 14 days

👉 **[synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/)**

Updated daily via GitHub Actions (14:00 UTC), as soon as new CAMS analysis data is available.

---

## What it does

Downloads hourly analysis data (not forecasts) for all height levels (surface to 5000 m),
extracts time series for the nearest grid point to the given coordinates,
and renders an interactive HTML chart.

Time series are cached as Parquet under `data/` (plus a small DuckDB file for UBA station overlays) — identical requests skip the API download. NetCDF downloads also go to `data/`. HTML plots default to `output/dust_analysis.html`.

## Data

| Variable | CAMS name | Unit |
|---|---|---|
| Saharan dust | `dust` | µg/m³ |
| Sulphur dioxide | `sulphur_dioxide` | µg/m³ |
| Fine particulate matter PM2.5 | `particulate_matter_2.5um` | µg/m³ |

Resolution: 0.1° × 0.1° (~10 km), hourly, 10 height levels (0–5000 m), rolling archive ~3 years.
Type: `analysis` (assimilated observational data).

## Setup

```bash
# 1. Create a free CAMS account
#    https://ads.atmosphere.copernicus.eu/

# 2. Add API key to ~/.cdsapirc
echo "url: https://ads.atmosphere.copernicus.eu/api
key: YOUR-API-KEY" > ~/.cdsapirc

# 3. Accept the dataset licence once in your browser
#    https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences

# 4. Install dependencies
uv sync
```

If **`uv`** warns about a missing **`RECORD`** file or the env looks broken: delete **`.venv`**, then **`uv sync`** again ([uv project env](https://docs.astral.sh/uv/concepts/projects/layout/#the-project-environment)).

## Installation from Git

```bash
# As a global CLI tool (recommended)
uv tool install git+https://github.com/synapticore-io/dust-analyzer.git

# Library only
pip install "git+https://github.com/synapticore-io/dust-analyzer.git"
```

## Usage

```bash
# Auto-detect location via IP geolocation
dust-analyzer

# Manual coordinates
dust-analyzer --lat 52.37 --lon 9.73

# Time range (default: 7 days)
dust-analyzer --days 14

# Skip cache
dust-analyzer --no-cache

# Custom output file (any path; parent dirs are created)
dust-analyzer --out output/my_analysis.html
```

### MCP server (Cursor / Claude Desktop)

Stdio: **`python -m dust_analyzer --mcp`**.

1. **`uv run`** (recommended): [`uv run --directory <repo> python -m dust_analyzer --mcp`](https://docs.astral.sh/uv/concepts/projects/run/) — updates the project env before running. **Do not** add **`--no-sync`** ([skips syncing `.venv`](https://docs.astral.sh/uv/reference/cli/#uv-run)).
2. **`.venv\Scripts\python.exe`** + **`cwd`** = repo after `uv sync`, or **`scripts/run_mcp.ps1`** — same module, no `uv` each launch.

**Not** **`uvx`**: that is [`uv tool run`](https://docs.astral.sh/uv/reference/cli/#uv-tool-run) (PyPI tools), not the [project `uv run`](https://docs.astral.sh/uv/concepts/projects/run/) workflow.

## Interpretation

- **Dust ↑, SO₂ stable** → Saharan dust intrusion
- **SO₂ ↑, PM2.5 ↑, Dust stable** → anthropogenic accumulation (inversion layer, industry, traffic)
- **both ↑ simultaneously** → overlapping sources

## Self-hosting

For automatic daily updates, the GitHub Actions workflow is at
`.github/workflows/update-plot.yml`. Requires a repository secret `CAMS_API_KEY`
containing the API key from `~/.cdsapirc`.

## Dependencies

- [cdsapi](https://github.com/ecmwf/cdsapi) — ECMWF ADS client
- [duckdb](https://duckdb.org/) — local cache
- [mcp](https://github.com/modelcontextprotocol/python-sdk) — MCP server (`--mcp`)
- [Polars](https://pola.rs/) — Parquet I/O and columnar transforms
- [xarray](https://xarray.dev/) + [netCDF4](https://unidata.github.io/netcdf4-python/) — NetCDF processing
- [plotly](https://plotly.com/python/) — interactive chart

## Data Attribution

Contains modified Copernicus Atmosphere Monitoring Service information (2026).
Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.

**Catalogue citation:**
Copernicus Atmosphere Monitoring Service (2020): CAMS European air quality forecasts.
Copernicus Atmosphere Monitoring Service (CAMS) Atmosphere Data Store (ADS).
DOI: [10.24381/a4005cee](https://doi.org/10.24381/a4005cee)

**ENSEMBLE data:**
METEO FRANCE, Ineris, Aarhus University, MET Norway, IEK, IEP-NRI, KNMI, TNO, SMHI, FMI, ENEA, BSC (2022):
CAMS European air quality forecasts, ENSEMBLE data.
Copernicus Atmosphere Monitoring Service (CAMS) Atmosphere Data Store (ADS).
[ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts)

## License

MIT
