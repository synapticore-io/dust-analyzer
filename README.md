# dust-analyzer

Analysiert **Saharastaub, SO₂ und PM2.5** für beliebige europäische Koordinaten.  
Datenquelle: [CAMS European Air Quality Forecasts](https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts) (Copernicus / ECMWF).

## Was es tut

Lädt stündliche Analysis-Daten (kein Forecast) für einen konfigurierbaren Zeitraum,
extrahiert die Zeitreihen für den nächsten Gitterpunkt zu den angegebenen Koordinaten
und rendert einen interaktiven HTML-Chart.

Zeitreihen werden lokal in DuckDB gecacht — gleiche Anfragen lösen keinen erneuten
API-Download aus.

## Daten

| Variable | CAMS-Name | Einheit |
|---|---|---|
| Saharastaub | `dust` | µg/m³ |
| Schwefeldioxid | `sulphur_dioxide` | µg/m³ |
| Feinstaub PM2.5 | `particulate_matter_2.5um` | µg/m³ |

Auflösung: 0.1° × 0.1° (~10 km), stündlich, rolling archive ~3 Jahre.  
Typ: `analysis` (assimilierte Beobachtungsdaten, kein Forecast).

## Setup

```bash
# 1. CAMS-Account anlegen (kostenlos)
#    https://ads.atmosphere.copernicus.eu/

# 2. API-Key in ~/.cdsapirc
echo "url: https://ads.atmosphere.copernicus.eu/api/v2
key: DEIN-API-KEY" > ~/.cdsapirc

# 3. Lizenz einmalig im Browser akzeptieren
#    https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts?tab=download#manage-licences

# 4. Abhängigkeiten
uv sync
```

## Verwendung

```bash
# Standort via IP-Geolocation
dust-analyzer

# Koordinaten manuell
dust-analyzer --lat 52.37 --lon 9.73

# Zeitraum (Standard: 7 Tage)
dust-analyzer --days 14

# Cache ignorieren
dust-analyzer --no-cache

# Output-Datei
dust-analyzer --out analyse.html
```

## Interpretation

- **Dust ↑, SO₂ stabil** → Sahara-Staubeintrag
- **SO₂ ↑, PM2.5 ↑, Dust stabil** → anthropogene Akkumulation (Wetterlage, Industrie, Verkehr)
- **beide gleichzeitig ↑** → Überlagerung beider Quellen

## Abhängigkeiten

- [cdsapi](https://github.com/ecmwf/cdsapi) — ECMWF ADS Client
- [xarray](https://xarray.dev/) + [netCDF4](https://unidata.github.io/netcdf4-python/) — NetCDF-Verarbeitung
- [duckdb](https://duckdb.org/) — lokaler Cache
- [plotly](https://plotly.com/python/) — interaktiver Chart

## Lizenz

MIT
