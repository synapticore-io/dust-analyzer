"""
Interactive Plotly chart: dust / SO₂ / PM2.5 in stacked subplots.
Shared X axis, dark theme, responsive/mobile-ready.
"""

from pathlib import Path
import logging

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dust_analyzer.location import Location


REPO_URL   = "https://github.com/synapticore-io/dust-analyzer"
SOURCE_URL = "https://ads.atmosphere.copernicus.eu/datasets/cams-europe-air-quality-forecasts"
SOURCE_LABEL = "CAMS European Air Quality Forecasts (Copernicus / ECMWF)"


logger = logging.getLogger(__name__)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"rgba({r},{g},{b},{alpha})"


def render(series: dict[str, dict], loc: Location, days: int, out: Path) -> None:
    """Write responsive interactive HTML chart to `out`."""
    n = len(series)

    fig = make_subplots(
        rows=n,
        cols=1,
        shared_xaxes=True,
        subplot_titles=[data["label"] for data in series.values()],
        vertical_spacing=0.06,
    )

    for idx, (key, data) in enumerate(series.items(), start=1):
        color      = data["color"]
        fill_color = _hex_to_rgba(color, 0.12)
        line_color = _hex_to_rgba(color, 0.9)

        fig.add_trace(
            go.Scatter(
                x=data["time"],
                y=data["values"],
                name=data["label"],
                mode="lines",
                line=dict(color=line_color, width=2),
                fill="tozeroy",
                fillcolor=fill_color,
                hovertemplate=(
                    "<b>%{x|%d.%m. %H:%M}</b><br>"
                    "%{y:.2f} µg/m³"
                    "<extra>" + data["label"] + "</extra>"
                ),
            ),
            row=idx,
            col=1,
        )

    # Y axis per subplot
        fig.update_yaxes(
            title_text="µg/m³",
            title_font=dict(size=11, color="#888"),
            tickfont=dict(size=11, color="#aaa"),
            gridcolor="rgba(255,255,255,0.05)",
            zerolinecolor="rgba(255,255,255,0.1)",
            row=idx,
            col=1,
        )

    # X axis only on bottom subplot
    fig.update_xaxes(
        tickfont=dict(size=11, color="#aaa"),
        gridcolor="rgba(255,255,255,0.05)",
        tickformat="%d.%m.\n%H:%M",
        row=n,
        col=1,
    )

    # Subplot title styling
    for annotation in fig["layout"]["annotations"]:
        annotation["font"] = dict(size=13, color="#ccc")
        annotation["xanchor"] = "left"
        annotation["x"] = 0

    # Footer: dataset hint + data source + repo
    fig.add_annotation(
        text=(
            "Modelled surface-level concentrations (level 0, ~10 km grid, 9-model ensemble + EEA station data) · "
            "No column integrals — dust aloft does not appear here"
        ),
        xref="paper", yref="paper",
        x=0, y=1.02,
        xanchor="left", yanchor="bottom",
        showarrow=False,
        font=dict(size=11, color="#888"),
    )

    fig.add_annotation(
        text=(
            f'Datenquelle: <a href="{SOURCE_URL}" target="_blank" '
            f'style="color:#7eb8d4">{SOURCE_LABEL}</a>'
            f' &nbsp;|&nbsp; '
            f'<a href="{REPO_URL}" target="_blank" '
            f'style="color:#7eb8d4">github.com/synapticore-io/dust-analyzer</a>'
        ),
        xref="paper", yref="paper",
        x=0, y=-0.04,
        xanchor="left", yanchor="top",
        showarrow=False,
        font=dict(size=11, color="#666"),
    )

    fig.update_layout(
        title=dict(
            text=(
                f"Air quality · surface level — {loc.city} "
                f"({loc.lat:.2f}°N, {loc.lon:.2f}°E) · last {days} days"
            ),
            font=dict(size=16, color="#e0e0e0"),
            x=0,
            xanchor="left",
        ),
        autosize=True,
        height=260 * n + 60,
        template="plotly_dark",
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#1e2a3a",
            font_size=13,
            namelength=-1,
        ),
        margin=dict(t=90, b=70, l=55, r=20),
        paper_bgcolor="#0f1117",
        plot_bgcolor="#131720",
    )

    # Responsive config: scales on any screen
    config = {
        "responsive": True,
        "displayModeBar": True,
        "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
        "displaylogo": False,
        "toImageButtonOptions": {
            "format": "png",
            "filename": f"dust_analyzer_{loc.city.lower()}",
            "scale": 2,
        },
    }

    fig.write_html(
        str(out),
        config=config,
        include_plotlyjs="cdn",  # smaller output, loads Plotly from CDN
        full_html=True,
    )
    logger.info("Chart written to %s", out.resolve())
    logger.info("Open the output HTML in a browser for the interactive view.")
