# dust-analyzer

**Saharan dust, SO₂ and PM2.5** for any European location — as interactive charts in **Claude Desktop** or as a **CLI tool**.

Data: [CAMS European Air Quality Forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts) (Copernicus/ECMWF), updated daily.
Live plot: **[synapticore-io.github.io/dust-analyzer](https://synapticore-io.github.io/dust-analyzer/)**

## How it works

A GitHub Actions workflow downloads CAMS data daily and publishes it as Parquet files in a [GitHub Release](https://github.com/synapticore-io/dust-analyzer/releases/tag/data-latest). The MCP server and CLI read directly from there via DuckDB httpfs — **no local CAMS download, no API key needed**.

```
GitHub Actions (daily 13:30 UTC)
  → CAMS API → analysis.parquet + forecast.parquet
  → GitHub Release "data-latest"

MCP Server / CLI
  → DuckDB read_parquet('https://github.com/.../analysis.parquet')
  → Interactive Plotly charts
```

## MCP Server (Claude Desktop / Cursor)

The server exposes 4 tools as [MCP Apps](https://modelcontextprotocol.io/docs/extensions/apps) with interactive Plotly visualizations:

| Tool | What it does |
|------|-------------|
| `analyze_air_quality` | Time series for all 3 pollutants with forecast stitching + UBA station overlay |
| `show_air_quality_map` | Spatial distribution on a European map (scattergeo), variable dropdown |
| `compare_cities` | Multi-city comparison (max 5) on shared time axis |
| `query_measurements` | Query raw data from the remote Parquet archive |

3 prompts for quick entry: `luftqualitaet`, `staedtevergleich`, `saharastaub_lage`.

### Setup (Claude Desktop)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dust-analyzer": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/dust-analyzer", "python", "-m", "dust_analyzer", "--mcp"]
    }
  }
}
```

No API key required — data is read from the public GitHub Release.

## CLI

```bash
uv sync                                          # Install
uv run dust-analyzer                              # Auto-detect location (IP)
uv run dust-analyzer --lat 52.37 --lon 9.73       # Manual coordinates
uv run dust-analyzer --days 14 --mode auto        # 14 days, analysis + forecast
uv run dust-analyzer --out output/my_plot.html    # Custom output
```

The CLI still supports local CAMS downloads (requires `~/.cdsapirc` with API key).

## Data

| Variable | CAMS request name | Unit |
|---|---|---|
| Saharan dust | `dust` | µg/m³ |
| Sulphur dioxide | `sulphur_dioxide` | µg/m³ |
| PM2.5 | `particulate_matter_2.5um` | µg/m³ |

Resolution: 0.1° × 0.1° (~10 km), hourly. Coverage: Central Europe (44–56°N, 2–18°E).

## Interpretation

- **Dust ↑, SO₂ stable** → Saharan dust intrusion
- **SO₂ ↑, PM2.5 ↑, Dust stable** → anthropogenic accumulation (inversion, industry, traffic)
- **Both ↑** → overlapping sources

## Architecture

```
src/dust_analyzer/
├── server.py     # MCP server — tools return CallToolResult (content + structuredContent)
├── remote.py     # DuckDB httpfs reads from GitHub Release Parquet
├── cams.py       # CAMS API download + NetCDF → Parquet (CI only)
├── cache.py      # UBA station data (DuckDB)
├── uba.py        # UBA REST API — nearest station, hourly measurements
├── mcp_ui/       # MCP App HTML views (Plotly charts)
├── plot.py       # CLI Plotly chart renderer
├── location.py   # IP geolocation + argparse
└── paths.py      # data/ and output/ directories
```

## Self-hosting

Two GitHub Actions workflows:

- `update-data.yml` (13:30 UTC) — downloads CAMS data, uploads Parquet to `data-latest` release
- `update-plot.yml` (14:00 UTC) — generates static HTML, deploys to GitHub Pages

Both require the `CAMS_API_KEY` repository secret.

## Data Attribution

Contains modified Copernicus Atmosphere Monitoring Service information (2026).
Neither the European Commission nor ECMWF is responsible for any use of the information or data it contains.

**DOI:** [10.24381/a4005cee](https://doi.org/10.24381/a4005cee)

## License

MIT
