# dust-analyzer v0.2 — Product Requirements Document

**Author:** Björn Bethge (synapticore.io)
**Date:** 2026-03-14
**Status:** Draft
**Repository:** [synapticore-io/dust-analyzer](https://github.com/synapticore-io/dust-analyzer)

---

## 1. Problem Statement

dust-analyzer v0.1 delivers CAMS analysis data as interactive time series and spatial maps via MCP tools. Two critical gaps limit real-world usefulness:

1. **48h data blind spot** — CAMS analysis data has ~48h latency. Users asking "how's the air right now?" get no answer for the most recent two days.
2. **Single-source, single-city** — Only CAMS model data, only one location at a time. No ground-truth validation, no spatial comparison, no automatic event detection.

These gaps were directly observed in production use (March 2026): Hannover and Hamburg queries returned data ending 2026-03-12 despite being queried on 2026-03-14.

## 2. Goals

- Close the real-time gap with station data and forecast fallback
- Enable multi-city comparison in a single query
- Automate the dust-vs-industrial event classification that was done manually in March 2025
- Maintain the existing MCP tool interface — additive changes only

## 3. Non-Goals

- Global coverage (remains Europe-focused via CAMS EU)
- Mobile app or standalone web frontend beyond GitHub Pages
- Historical reanalysis (ERA5 integration)
- Air quality index (AQI) calculation or health advice

## 4. Architecture Context (v0.1 baseline)

```
src/dust_analyzer/
├── server.py      MCP server — 3 tools: analyze_air_quality, show_pollution_map, query_measurements
├── cams.py        CAMS API download + NetCDF extraction (xarray, cdsapi)
├── cache.py       DuckDB cache — timeseries + measurements tables
├── location.py    Location dataclass + IP geolocation
├── plot.py        Plotly HTML rendering (CLI mode)
```

**Data flow:** location → cache check → CAMS download → extract → cache → serialize → MCP response

**Current dependencies:** cdsapi, xarray, netCDF4, plotly, duckdb, fastmcp

**DuckDB schema:** `timeseries` (key, variable, lat, lon, date_from, date_to, timestamp, value), `measurements` (timestamp, latitude, longitude, level_m, variable, value, unit, model, request_hash)

---

## 5. Features

### F1: Real-Time Ground Truth — UBA Station API

**Priority:** P0 (Phase 1)
**Effort:** M

**Problem:** No measured ground-truth data. CAMS is a model — station measurements are the validation baseline.

**Solution:**
- New module `src/dust_analyzer/uba.py`
- Fetch hourly station data from [Umweltbundesamt REST API](https://www.umweltbundesamt.de/daten/luft/luftdaten/doc)
- Components: PM10, PM2.5, SO₂, NO₂, O₃
- New DuckDB table `station_measurements` (station_id, station_name, lat, lon, component, timestamp, value, unit)
- Station matching: nearest station to requested lat/lon via Haversine distance
- No authentication required — public API, rate limit ~100 req/min

**MCP interface change:**
- Station lookup and overlay happens automatically inside `analyze_air_quality` (no separate tools)
- Station info (name, code, distance) included in response JSON
- Station data rendered as dashed overlay in timeseries chart

**Key stations:**
- Hannover-Linden (DENI011), Hamburg-Sternschanze (DEHH021), Berlin-Neukölln (DEBE034)

**API endpoints:**
```
GET /air_data/v3/measures/json?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&time_from=1&time_to=24&station={id}&component={id}
GET /air_data/v3/stations/json  (station metadata + coordinates)
GET /air_data/v3/components/json  (component IDs)
```

**Acceptance criteria:**
- [ ] Station data available within 1h of measurement
- [ ] Auto-selects nearest station per location
- [ ] Overlays cleanly on CAMS timeseries without breaking existing chart
- [ ] Falls back gracefully if UBA API unreachable

---

### F2: CAMS Forecast Mode

**Priority:** P0 (Phase 1)
**Effort:** S

**Problem:** Analysis data ends ~48h before now. The gap is confusing to users.

**Solution:**
- Extend `cams.py`: new parameter `data_type: Literal["analysis", "forecast"] = "analysis"`
- Forecast uses same dataset (`cams-europe-air-quality-forecasts`) but with `type: ["forecast"]` and `leadtime_hour: ["0", "24", "48", "72", "96"]`
- Cache key includes data_type to avoid mixing analysis and forecast data
- No new module — extends existing `cams.download()` and `cams.extract()`

**MCP interface change:**
- `analyze_air_quality` gains optional `mode: Literal["analysis", "forecast", "auto"] = "auto"`
- `auto` mode: analysis for dates >48h ago, forecast for recent 48h + next 72h
- Station overlay is automatic in `auto` and `analysis` modes (internal, not a separate tool)
- `today` field in response shows current date for transparency

**Acceptance criteria:**
- [ ] Forecast data available for current day + 4 days ahead
- [ ] `auto` mode seamlessly stitches analysis → forecast at the boundary
- [ ] Forecast data visually distinguishable (lighter opacity or dashed line)

---

### F3: Multi-Source Fusion View

**Priority:** P1 (Phase 2)
**Effort:** L

**Problem:** Each data source has tradeoffs (latency vs. accuracy, model vs. measurement). Users need one unified view.

**Solution:**
- New module `src/dust_analyzer/fusion.py`
- Unified timeline: CAMS analysis (historical, validated) → CAMS forecast (recent 48h + outlook) → UBA stations (real-time overlay)
- Source metadata per data point: `source` enum (cams_analysis, cams_forecast, uba_station, sensor_community)
- Confidence banding in chart: analysis = solid, forecast = dashed, station = markers
- DuckDB view `unified_timeseries` joining all source tables with source column

**MCP interface change:**
- `analyze_air_quality` returns unified data by default when `mode="auto"`
- Response JSON gains `source` field per data point

**Acceptance criteria:**
- [ ] Single chart shows all sources with clear visual distinction
- [ ] Tooltip shows data source and latency for each point
- [ ] No data duplication — each timestamp/variable/location appears once per source

---

### F4: Multi-City Comparison

**Priority:** P1 (Phase 2)
**Effort:** M

**Problem:** Comparing Hamburg vs. Hannover requires two separate tool calls, no aligned visualization.

**Solution:**
- New MCP tool `compare_cities(cities: list[dict], variable: str, days: int)`
- Input: `[{"lat": 52.37, "lon": 9.73, "city": "Hannover"}, {"lat": 53.55, "lon": 9.99, "city": "Hamburg"}]`
- Output: Normalized timeseries on shared time axis, one trace per city
- New MCP App HTML resource for multi-city chart
- Max 5 cities per comparison (performance bound)

**MCP interface change:**
- New tool `compare_cities` with dedicated visualization
- Reuses existing CAMS download + cache infrastructure per city

**Acceptance criteria:**
- [ ] Up to 5 cities in one chart with shared time axis
- [ ] Clear city labels and color coding
- [ ] Per-city data fetched in parallel where possible

---

### F5: Satellite Aerosol Layer (Sentinel-5P / TROPOMI)

**Priority:** P2 (Phase 3)
**Effort:** L

**Problem:** CAMS is a model, UBA stations are point measurements. Satellite provides independent spatial observation.

**Solution:**
- New module `src/dust_analyzer/sentinel.py`
- Copernicus Data Space Ecosystem API for Sentinel-5P Level 2
- Variables: SO₂ total column, UV Aerosol Index (UVAI)
- Daily granularity, ~3.5 km × 7 km resolution
- Overlay as spatial heatmap layer in `show_pollution_map`

**API:** Copernicus Data Space (`dataspace.copernicus.eu`) — requires separate free account + OAuth2 token

**Acceptance criteria:**
- [ ] Daily TROPOMI SO₂ and aerosol index retrievable for Europe
- [ ] Renders as spatial overlay on existing pollution map
- [ ] Independent confirmation of dust events vs. industrial SO₂

---

### F6: Citizen Science Overlay (Sensor.Community)

**Priority:** P2 (Phase 3)
**Effort:** M

**Problem:** Official UBA stations have sparse spatial coverage (~500 stations for all of Germany).

**Solution:**
- New module `src/dust_analyzer/sensors.py`
- [Sensor.Community API](https://api.sensor.community/) — thousands of low-cost PM sensors
- New DuckDB table `citizen_measurements` with quality_tier flag
- Spatial query: all sensors within radius of requested location
- Quality caveat displayed in chart (citizen science data, not calibrated)

**API:** Public, no authentication, rate-limited

**Acceptance criteria:**
- [ ] Sensor data retrievable for any European location
- [ ] Quality tier clearly marked in visualization
- [ ] Does not affect core analysis when sensors unavailable

---

### F7: Threshold Alerts & Event Detection

**Priority:** P1 (Phase 2)
**Effort:** M

**Problem:** Users must manually inspect charts to identify critical events. The dust-vs-industrial classification was done manually in March 2025.

**Solution:**
- New module `src/dust_analyzer/events.py`
- WHO threshold annotations: PM2.5 daily mean >15 µg/m³, SO₂ 24h >40 µg/m³
- Event classification logic:
  - `dust_event`: Saharan dust > 5 µg/m³ AND PM2.5 > 15 µg/m³ AND SO₂ stable
  - `industrial_event`: SO₂ > 5 µg/m³ AND PM2.5 > 15 µg/m³ AND dust < 2 µg/m³
  - `mixed_event`: Both dust and SO₂ elevated
- Events stored in DuckDB table `detected_events` (timestamp, event_type, severity, variables, location)
- Visual: horizontal threshold lines + event annotations in timeseries chart

**MCP interface change:**
- `analyze_air_quality` response gains `events: list[dict]` field
- New tool `detect_events(lat, lon, days)` for standalone event query

**Acceptance criteria:**
- [ ] WHO thresholds rendered as reference lines in chart
- [ ] Events auto-classified with >80% agreement with manual classification
- [ ] Event list returned in JSON for programmatic use

---

### F8: Data Provenance & Quality Metadata

**Priority:** P2 (Phase 3)
**Effort:** S

**Problem:** No transparency about data origin, latency, or reliability per data point.

**Solution:**
- Add columns to all DuckDB tables: `source` (enum), `ingested_at` (timestamp), `quality_tier` (validated/provisional/citizen)
- Response JSON includes provenance per series
- Tooltip in charts shows source + latency

**Acceptance criteria:**
- [ ] Every data point traceable to source
- [ ] Quality tier visible in UI tooltips

---

## 6. Phasing

| Phase | Features | Target | Key Dependency |
|-------|----------|--------|----------------|
| **Phase 1** | F1 (UBA) + F2 (Forecast) | v0.2.0 | UBA API (no key), CAMS forecast (existing key) |
| **Phase 2** | F3 (Fusion) + F4 (Multi-City) + F7 (Events) | v0.3.0 | Phase 1 complete |
| **Phase 3** | F5 (Sentinel) + F6 (Sensors) + F8 (Provenance) | v0.4.0 | Copernicus Data Space account |

## 7. API Keys & Credentials Required

### Existing (already configured)

| Credential | Location | Used by | Notes |
|---|---|---|---|
| **CAMS API Key** | `~/.cdsapirc` | cams.py (cdsapi) | Covers F2 (forecast) — same key, same dataset |
| **CAMS_API_KEY** | GitHub Secret | CI workflow | Same key as above, for GitHub Actions |

### New — Phase 1

| Credential | Location | Used by | How to get |
|---|---|---|---|
| *(none)* | — | F1 (UBA API) | Public API, no authentication required |

### New — Phase 3

| Credential | Location | Used by | How to get |
|---|---|---|---|
| **Copernicus Data Space OAuth2** | `~/.dataspace_token` or env var `CDSE_CLIENT_ID` + `CDSE_CLIENT_SECRET` | F5 (Sentinel-5P) | Free account at [dataspace.copernicus.eu](https://dataspace.copernicus.eu/), register OAuth2 client |

### Summary: What you need to do

**Right now (Phase 1): Nothing.** Dein existierender CAMS Key in `~/.cdsapirc` reicht für F1 + F2. UBA braucht keinen Key.

**Für Phase 3 (Sentinel-5P):**
1. Geh auf https://dataspace.copernicus.eu/ → Account erstellen (gratis)
2. Unter "OAuth Clients" → neuen Client anlegen
3. Client ID + Secret in env vars oder config file

## 8. New Dependencies (estimated)

| Feature | New dependency | Size | Justification |
|---|---|---|---|
| F1 (UBA) | `httpx` | ~1 MB | Async HTTP client for UBA REST API (stdlib urllib insufficient for async) |
| F5 (Sentinel) | `sentinelsat` or raw `httpx` | ~2 MB | Copernicus Data Space API access |
| F6 (Sensors) | *(none, reuse httpx)* | — | Sensor.Community API is simple REST |
| F7 (Events) | *(none)* | — | Pure Python logic on existing data |

## 9. New Files (planned)

| File | Phase | Purpose | Est. Lines |
|---|---|---|---|
| `src/dust_analyzer/uba.py` | 1 | UBA station API client + station matching | ~200 |
| `src/dust_analyzer/events.py` | 2 | Event detection + WHO thresholds | ~150 |
| `src/dust_analyzer/fusion.py` | 2 | Multi-source timeline stitching | ~150 |
| `src/dust_analyzer/sentinel.py` | 3 | Sentinel-5P/TROPOMI data access | ~250 |
| `src/dust_analyzer/sensors.py` | 3 | Sensor.Community API client | ~150 |

**Existing files modified:**

| File | Changes |
|---|---|
| `server.py` | New MCP tools (compare_cities, detect_events, query_station_data), updated analyze_air_quality params |
| `cams.py` | `data_type` parameter for forecast mode, updated `download()` request building |
| `cache.py` | New tables (station_measurements, citizen_measurements, detected_events), provenance columns |
| `pyproject.toml` | Add httpx dependency |
| `CLAUDE.md` | Updated architecture, new modules documented |
| `README.md` | New setup instructions for Phase 3 credentials, updated feature list |

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| UBA API rate limiting or downtime | F1 blocked | Cache aggressively, retry with backoff, degrade gracefully |
| CAMS forecast data format differs from analysis | F2 broken | Verified: same dataset, same NetCDF structure, only `type` and `leadtime_hour` differ |
| Sentinel-5P data volume too large | F5 slow | Subset spatially before download, daily granularity only |
| Low-cost sensor data unreliable | F6 misleading | Quality tier flag, visual caveat, never use for event detection |

---

*This PRD is a living document. Features will be refined during implementation.*
