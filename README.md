# dust-analyzer

Analyzes **Saharan dust, SO₂ and PM2.5** for any European location.  
Data source: [CAMS European Air Quality Forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts) (Copernicus / ECMWF).

## Live Plot — Hannover, last 14 days

👉 **[synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/)**

Updated daily via GitHub Actions (10:00 UTC), as soon as new CAMS analysis data is available.

---

## What it does

Downloads hourly analysis data (not forecasts) for a configurable time range,
extracts time series for the nearest grid point to the given coordinates,
and renders an interactive HTML chart.

Time series are cached locally in DuckDB — identical requests skip the API download.

## Data

| Variable | CAMS name | Unit |
|---|---|---|
| Saharan dust | `dust` | µg/m³ |
| Sulphur dioxide | `sulphur_dioxide` | µg/m³ |
| Fine particulate matter PM2.5 | `particulate_matter_2.5um` | µg/m³ |

Resolution: 0.1° × 0.1° (~10 km), hourly, rolling archive ~3 years.  
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

# Custom output file
dust-analyzer --out my_analysis.html
```

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
- [xarray](https://xarray.dev/) + [netCDF4](https://unidata.github.io/netcdf4-python/) — NetCDF processing
- [duckdb](https://duckdb.org/) — local cache
- [plotly](https://plotly.com/python/) — interactive chart

## License

MIT
