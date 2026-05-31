from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


COLOR_SEQUENCE = ["#2563eb", "#16a34a", "#f97316", "#dc2626", "#7c3aed", "#0891b2"]


def ticket_volume_chart(time_df: pd.DataFrame) -> go.Figure:
    fig = px.line(
        time_df,
        x="created_at",
        y="tickets",
        markers=True,
        color_discrete_sequence=["#2563eb"],
    )
    fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), height=280)
    return fig


def bar_chart(df: pd.DataFrame, x: str, y: str, title: str | None = None) -> go.Figure:
    fig = px.bar(df, x=x, y=y, title=title, color=x, color_discrete_sequence=COLOR_SEQUENCE)
    fig.update_layout(showlegend=False, margin=dict(l=10, r=10, t=40 if title else 20, b=10), height=300)
    return fig


def theme_chart(themes_df: pd.DataFrame) -> go.Figure:
    fig = px.bar(
        themes_df.head(8),
        x="count",
        y="name",
        orientation="h",
        color="critical_high_count",
        color_continuous_scale="Reds",
        labels={"name": "Theme", "count": "Tickets", "critical_high_count": "High/Critical"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(l=10, r=10, t=20, b=10), height=360)
    return fig
