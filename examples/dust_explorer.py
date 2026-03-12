from pathlib import Path
import json

import duckdb
import marimo
import polars as pl
import plotly.graph_objects as go
from plotly.subplots import make_subplots


DB_PATH = Path("dust_cache.duckdb")

cities: dict[str, tuple[float, float]] = {
    "Hanover": (52.37, 9.73),
    "Berlin": (52.52, 13.41),
    "Munich": (48.14, 11.58),
    "Hamburg": (53.55, 9.99),
    "Vienna": (48.21, 16.37),
    "Zurich": (47.38, 8.54),
    "Amsterdam": (52.37, 4.90),
    "Paris": (48.86, 2.35),
    "Barcelona": (41.39, 2.17),
    "Athens": (37.98, 23.73),
}


def _selected_levels_from_labels(labels: list[str]) -> list[int]:
    mapping = {
        "Surface": 0,
        "50m": 50,
        "100m": 100,
        "250m": 250,
        "500m": 500,
        "1000m": 1000,
        "2000m": 2000,
        "3000m": 3000,
        "5000m": 5000,
    }
    return [mapping[label] for label in labels if label in mapping]


def _load_measurements(city: str, days: int, level_labels: list[str]) -> pl.DataFrame:
    if not DB_PATH.exists():
        return pl.DataFrame()

    lat, lon = cities[city]
    levels = _selected_levels_from_labels(level_labels)

    if not levels:
        return pl.DataFrame()

    con = duckdb.connect(DB_PATH.as_posix())
    level_list = ", ".join(str(level) for level in levels)
    query = f"""
        SELECT timestamp, latitude, longitude, level_m, variable, value
        FROM measurements
        WHERE latitude BETWEEN ? AND ?
          AND longitude BETWEEN ? AND ?
          AND timestamp >= current_date - interval ? day
          AND level_m IN ({level_list})
        ORDER BY timestamp, level_m
    """

    df = con.execute(
        query,
        [lat - 0.1, lat + 0.1, lon - 0.1, lon + 0.1, days],
    ).pl()
    con.close()
    return df


def _time_series_figure(df: pl.DataFrame, selected_levels: list[int]) -> go.Figure:
    fig = make_subplots(
        rows=3,
        cols=1,
        shared_xaxes=True,
        subplot_titles=("Sahara-Staub (µg/m³)", "SO₂ (µg/m³)", "PM2.5 (µg/m³)"),
        vertical_spacing=0.08,
    )

    for level in selected_levels:
        level_data = df.filter(pl.col("level_m") == level)
        dust = level_data.filter(pl.col("variable") == "dust")
        so2 = level_data.filter(pl.col("variable") == "sulphur_dioxide")
        pm25 = level_data.filter(pl.col("variable") == "particulate_matter_2.5um")

        if not dust.is_empty():
            fig.add_trace(
                go.Scatter(
                    x=dust["timestamp"],
                    y=dust["value"],
                    name=f"Dust {level}m",
                ),
                row=1,
                col=1,
            )

        if not so2.is_empty():
            fig.add_trace(
                go.Scatter(
                    x=so2["timestamp"],
                    y=so2["value"],
                    name=f"SO₂ {level}m",
                ),
                row=2,
                col=1,
            )

        if not pm25.is_empty():
            fig.add_trace(
                go.Scatter(
                    x=pm25["timestamp"],
                    y=pm25["value"],
                    name=f"PM2.5 {level}m",
                ),
                row=3,
                col=1,
            )

    fig.update_layout(height=800, template="plotly_white", showlegend=True)
    return fig


def _height_profile_figure(df: pl.DataFrame, city: str) -> go.Figure:
    dust = df.filter(pl.col("variable") == "dust")
    if dust.is_empty():
        return go.Figure()

    pivot = dust.pivot(on="level_m", index="timestamp", values="value")
    values = pivot.select(pl.exclude("timestamp")).to_numpy().T

    fig = go.Figure(
        data=go.Heatmap(
            z=values,
            x=pivot["timestamp"],
            y=sorted(dust["level_m"].unique()),
            colorscale="YlOrRd",
            colorbar_title="µg/m³",
        )
    )
    fig.update_layout(
        title=f"Dust vertical profile — {city}",
        yaxis_title="Height (m)",
        xaxis_title="Time",
    )
    return fig


def _correlation_figure(df: pl.DataFrame) -> go.Figure:
    surface = df.filter(pl.col("level_m") == 0)
    if surface.is_empty():
        return go.Figure()

    dust_vals = surface.filter(pl.col("variable") == "dust")["value"]
    pm25_vals = surface.filter(pl.col("variable") == "particulate_matter_2.5um")["value"]
    so2_vals = surface.filter(pl.col("variable") == "sulphur_dioxide")["value"]

    if len(dust_vals) == 0 or len(pm25_vals) == 0 or len(so2_vals) == 0:
        return go.Figure()

    fig = go.Figure(
        data=go.Scatter(
            x=dust_vals,
            y=pm25_vals,
            mode="markers",
            marker=dict(
                color=so2_vals,
                colorscale="Viridis",
                colorbar_title="SO₂",
                size=5,
                opacity=0.6,
            ),
        )
    )
    fig.update_layout(
        xaxis_title="Dust (µg/m³)",
        yaxis_title="PM2.5 (µg/m³)",
        title="Quellen-Attribution: Dust vs PM2.5 (Farbe = SO₂)",
    )
    return fig


def _interpretation_md(df: pl.DataFrame, city: str, days: int) -> str:
    surface = df.filter(pl.col("level_m") == 0)
    if surface.is_empty():
        return f"## Interpretation — {city}, last {days} days\n\nNo data in the selected time range."

    surface_dust = surface.filter(pl.col("variable") == "dust")["value"]
    surface_so2 = surface.filter(pl.col("variable") == "sulphur_dioxide")["value"]
    surface_pm25 = surface.filter(pl.col("variable") == "particulate_matter_2.5um")["value"]

    if len(surface_dust) == 0 or len(surface_so2) == 0 or len(surface_pm25) == 0:
        return (
            f"## Interpretation — {city}, last {days} days\n\n"
            "Incomplete data for interpretation."
        )

    dust_mean = float(surface_dust.mean())
    so2_mean = float(surface_so2.mean())
    pm25_mean = float(surface_pm25.mean())

    dust_threshold = 15.0
    so2_threshold = 5.0

    if dust_mean > dust_threshold and so2_mean < so2_threshold:
        interpretation = (
            "**Saharan dust event detected.** "
            "Elevated dust with stable SO₂ suggests natural long-range transport."
        )
    elif so2_mean > so2_threshold and dust_mean < dust_threshold:
        interpretation = (
            "**Anthropogenic pollution.** "
            "Elevated SO₂ and PM2.5 with low dust suggests industrial/traffic sources."
        )
    elif dust_mean > dust_threshold and so2_mean > so2_threshold:
        interpretation = (
            "**Overlapping sources.** "
            "Both Saharan dust and anthropogenic emissions contribute to the load."
        )
    else:
        interpretation = "**Normal air quality.** No pronounced patterns."

    return (
        f"## Interpretation — {city}, last {days} days\n\n"
        f"{interpretation}\n\n"
        "| Metric | Mean value | Assessment |\n"
        "|--------|------------|------------|\n"
        f"| Dust | {dust_mean:.1f} µg/m³ | "
        f"{'⚠️ elevated' if dust_mean > dust_threshold else '✅ normal'} |\n"
        f"| SO₂ | {so2_mean:.2f} µg/m³ | "
        f"{'⚠️ elevated' if so2_mean > so2_threshold else '✅ normal'} |\n"
        f"| PM2.5 | {pm25_mean:.1f} µg/m³ | "
        f"{'⚠️ elevated' if pm25_mean > 10 else '✅ normal'} |\n"
    )


def _threejs_html(df: pl.DataFrame, city: str) -> str:
    dust = df.filter(pl.col("variable") == "dust")
    if dust.is_empty():
        data_json = json.dumps({"points": [], "city": city, "levels": []})
    else:
        grouped = dust.group_by(["latitude", "longitude", "level_m"]).agg(
            pl.col("value").mean().alias("value")
        )
        points = [
            {
                "lon": row["longitude"],
                "lat": row["latitude"],
                "alt": row["level_m"],
                "value": row["value"],
            }
            for row in grouped.iter_rows(named=True)
        ]
        levels = sorted(dust["level_m"].unique())
        data_json = json.dumps({"points": points, "city": city, "levels": levels})

    html = """
<div id="dust-3d" style="width:100%;height:600px;position:relative;">
<script type="importmap">
{
  "imports": {
    "three": "https://unpkg.com/three@0.183.2/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.183.2/examples/jsm/"
  }
}
</script>
<script type="module">
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const container = document.getElementById('dust-3d');
const data = REPLACE_DATA_JSON;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0a0a1a);
scene.fog = new THREE.FogExp2(0x0a0a1a, 0.015);

const camera = new THREE.PerspectiveCamera(
  60, container.clientWidth / container.clientHeight, 0.1, 1000
);
camera.position.set(30, 20, 30);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.setPixelRatio(window.devicePixelRatio);
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.05;

if (data.points.length > 0) {
  const lons = [...new Set(data.points.map(p => p.lon))].sort((a, b) => a - b);
  const lats = [...new Set(data.points.map(p => p.lat))].sort((a, b) => a - b);
  const lonCenter = (Math.min(...lons) + Math.max(...lons)) / 2;
  const latCenter = (Math.min(...lats) + Math.max(...lats)) / 2;
  const lonScale = 10 / (Math.max(...lons) - Math.min(...lons) || 1);
  const latScale = 10 / (Math.max(...lats) - Math.min(...lats) || 1);
  const altScale = 15 / 5000;

  const maxVal = Math.max(...data.points.map(p => p.value), 1);

  function dustColor(normalizedValue) {
    const v = Math.pow(normalizedValue, 0.6);
    const r = Math.min(1.0, v * 2.5);
    const g = Math.max(0, Math.min(1.0, v * 1.8 - 0.3));
    const b = Math.max(0, 0.3 - v * 0.5);
    return new THREE.Color(r, g, b);
  }

  const geometry = new THREE.BufferGeometry();
  const positions = [];
  const colors = [];

  for (const p of data.points) {
    if (p.value < 0.5) continue;

    const x = (p.lon - lonCenter) * lonScale;
    const z = (p.lat - latCenter) * latScale;
    const y = p.alt * altScale;
    const norm = p.value / maxVal;

    const count = Math.ceil(norm * 8) + 1;
    for (let i = 0; i < count; i++) {
      const jitter = 0.3;
      positions.push(
        x + (Math.random() - 0.5) * jitter,
        y + (Math.random() - 0.5) * jitter * 2,
        z + (Math.random() - 0.5) * jitter
      );
      const color = dustColor(norm);
      colors.push(color.r, color.g, color.b);
    }
  }

  geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

  const material = new THREE.PointsMaterial({
    size: 0.4,
    vertexColors: true,
    transparent: true,
    opacity: 0.6,
    sizeAttenuation: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });

  const particles = new THREE.Points(geometry, material);
  scene.add(particles);
}

const groundGeo = new THREE.PlaneGeometry(22, 22);
const groundMat = new THREE.MeshStandardMaterial({
  color: 0x1a3a1a, transparent: true, opacity: 0.3, side: THREE.DoubleSide
});
const ground = new THREE.Mesh(groundGeo, groundMat);
ground.rotation.x = -Math.PI / 2;
scene.add(ground);

const gridHelper = new THREE.GridHelper(22, 20, 0x333355, 0x222244);
scene.add(gridHelper);

const titleDiv = document.createElement('div');
titleDiv.style.cssText = 'position:absolute;top:10px;left:10px;color:#aab;font:14px monospace;';
titleDiv.textContent = data.city + ' — Dust Concentration 3D (Surface → 5000m)';
container.appendChild(titleDiv);

function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
}
animate();

new ResizeObserver(() => {
  camera.aspect = container.clientWidth / container.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(container.clientWidth, container.clientHeight);
}).observe(container);
</script>
</div>
"""
    return html.replace("REPLACE_DATA_JSON", data_json)


app = marimo.App()


@app.cell
def _( ):
    import marimo as mo
    return mo


@app.cell
def _ui(mo):
    city_dropdown = mo.ui.dropdown(
        options=list(cities.keys()),
        value="Hannover",
        label="Stadt",
    )
    days_slider = mo.ui.slider(
        start=7,
        stop=90,
        step=7,
        value=14,
        label="Time range (days)",
    )
    level_select = mo.ui.multiselect(
        options=[
            "Surface",
            "50m",
            "100m",
            "250m",
            "500m",
            "1000m",
            "2000m",
            "3000m",
            "5000m",
        ],
        value=["Surface", "250m", "1000m", "3000m"],
        label="Height levels",
    )

    header = mo.hstack([city_dropdown, days_slider, level_select])
    return header, city_dropdown, days_slider, level_select


@app.cell
def _(city_dropdown, days_slider, level_select):
    df = _load_measurements(
        city_dropdown.value,
        days_slider.value,
        level_select.value,
    )
    return df


@app.cell
def _(city_dropdown, days_slider, df, header, level_select, mo):
    selected_levels = _selected_levels_from_labels(level_select.value)
    stats = mo.stat(f"{len(df):,} Datenpunkte geladen")

    ts_fig = _time_series_figure(df, selected_levels)
    profile_fig = _height_profile_figure(df, city_dropdown.value)
    corr_fig = _correlation_figure(df)
    interpretation = _interpretation_md(df, city_dropdown.value, days_slider.value)
    threejs = _threejs_html(df, city_dropdown.value)

    mo.vstack(
        [
            header,
            stats,
            mo.ui.plotly(ts_fig),
            mo.ui.plotly(profile_fig),
            mo.ui.plotly(corr_fig),
            mo.md(interpretation),
            mo.iframe(threejs, height="600px"),
        ]
    )


if __name__ == "__main__":
    app.run()
