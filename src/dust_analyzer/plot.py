"""
Interaktiver Plotly-Chart: Dust / SO₂ / PM2.5 übereinander.
Separate Y-Achsen pro Variable, geteilte X-Achse, Dark Theme.
"""

from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from dust_analyzer.location import Location


def render(series: dict[str, dict], loc: Location, days: int, out: Path) -> None:
    """Schreibt interaktiven HTML-Chart nach `out`."""
    n = len(series)
    fig = make_subplots(
        rows=n,
        cols=1,
        shared_xaxes=True,
        subplot_titles=[data["label"] for data in series.values()],
        vertical_spacing=0.08,
    )

    for idx, (key, data) in enumerate(series.items(), start=1):
        # Hex → rgba für Fill
        hex_color = data["color"]
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        fill_color = f"rgba({r},{g},{b},0.15)"

        fig.add_trace(
            go.Scatter(
                x=data["time"],
                y=data["values"],
                name=data["label"],
                mode="lines",
                line=dict(color=hex_color, width=2),
                fill="tozeroy",
                fillcolor=fill_color,
                hovertemplate="%{x}<br>%{y:.2e}<extra>" + data["label"] + "</extra>",
            ),
            row=idx,
            col=1,
        )

    fig.update_layout(
        title=dict(
            text=f"Luftqualität — {loc} · letzten {days} Tage",
            font=dict(size=18, color="#e0e0e0"),
        ),
        height=280 * n,
        template="plotly_dark",
        showlegend=False,
        hovermode="x unified",
        margin=dict(t=80, b=40, l=60, r=20),
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#16213e",
    )

    fig.write_html(str(out))
    print(f"\n✅ Chart: {out.resolve()}")
    print("   Im Browser öffnen für interaktive Ansicht.")
