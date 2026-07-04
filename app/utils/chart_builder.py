"""Reusable Plotly chart builders for the Streamlit dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


TEMPLATE = "plotly_white"
ACCENT = "#ff7a1a"
BLUE = "#3b82f6"
GREEN = "#22c55e"


def monthly_revenue_chart(df: pd.DataFrame) -> go.Figure:
    """Build a monthly revenue line/bar chart."""
    fig = go.Figure()
    fig.add_bar(x=df["year_month"], y=df["revenue"], name="Revenue", marker_color=BLUE)
    fig.add_scatter(x=df["year_month"], y=df["revenue"], name="Trend", mode="lines+markers", line_color=ACCENT)
    fig.update_layout(template=TEMPLATE, height=360, margin=dict(l=10, r=10, t=35, b=10), legend_orientation="h")
    fig.update_yaxes(title_text="Revenue")
    fig.update_xaxes(title_text="Month")
    return fig


def country_revenue_chart(df: pd.DataFrame) -> go.Figure:
    """Build a revenue-by-country horizontal bar chart."""
    fig = px.bar(
        df.sort_values("revenue"),
        x="revenue",
        y="country",
        orientation="h",
        color_discrete_sequence=[ACCENT],
        template=TEMPLATE,
        height=360,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=35, b=10), xaxis_title="Revenue", yaxis_title="")
    return fig


def rfm_donut_chart(df: pd.DataFrame) -> go.Figure:
    """Build an RFM segment donut chart."""
    fig = px.pie(
        df,
        names="segment",
        values="customers",
        hole=0.52,
        color_discrete_sequence=px.colors.qualitative.Set2,
        template=TEMPLATE,
        height=340,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=35, b=10), legend_orientation="h")
    return fig


def category_treemap(df: pd.DataFrame) -> go.Figure:
    """Build a category revenue treemap."""
    fig = px.treemap(
        df,
        path=["category"],
        values="revenue",
        color="avg_margin_pct",
        color_continuous_scale="RdYlGn",
        template=TEMPLATE,
        height=340,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=35, b=10))
    return fig


def cohort_heatmap(df: pd.DataFrame) -> go.Figure:
    """Build a cohort retention heatmap from the retention matrix query."""
    matrix = df.set_index("cohort_month").drop(columns=["cohort_customers"], errors="ignore")
    fig = px.imshow(
        matrix,
        labels=dict(x="Month", y="Cohort", color="Retention %"),
        color_continuous_scale="Blues",
        aspect="auto",
        template=TEMPLATE,
        height=360,
    )
    fig.update_layout(margin=dict(l=10, r=10, t=35, b=10))
    return fig
