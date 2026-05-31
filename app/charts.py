from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


COLOR_SEQUENCE = ["#0f766e", "#e4572e", "#2454a6", "#d49b25", "#6d5dfc", "#64748b", "#2f855a"]


def _polish_chart(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#16202a", family="Inter, -apple-system, BlinkMacSystemFont, sans-serif"),
        margin=dict(l=10, r=10, t=28, b=10),
        xaxis=dict(gridcolor="#e2e8f0", zerolinecolor="#d9e2ec"),
        yaxis=dict(gridcolor="#e2e8f0", zerolinecolor="#d9e2ec"),
    )
    return fig


def ticket_volume_chart(time_df: pd.DataFrame) -> go.Figure:
    fig = px.line(
        time_df,
        x="created_at",
        y="tickets",
        markers=True,
        color_discrete_sequence=["#0f766e"],
    )
    fig.update_traces(line=dict(width=3), marker=dict(size=7, color="#e4572e"))
    return _polish_chart(fig, 280)


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str | None = None) -> go.Figure:
    fig = px.bar(df, x=x, y=y, title=title, color=x, color_discrete_sequence=COLOR_SEQUENCE)
    fig.update_traces(marker_line_color="rgba(255,255,255,.75)", marker_line_width=1)
    fig.update_layout(showlegend=False)
    return _polish_chart(fig, 300)


def theme_chart(themes_df: pd.DataFrame) -> go.Figure:
    fig = px.bar(
        themes_df.head(8),
        x="count",
        y="name",
        orientation="h",
        color="critical_high_count",
        color_continuous_scale=["#dbeafe", "#f8c471", "#e4572e"],
        labels={"name": "Theme", "count": "Tickets", "critical_high_count": "High/Critical"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    return _polish_chart(fig, 360)
