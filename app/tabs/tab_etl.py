"""ETL status tab for the Streamlit app."""
from __future__ import annotations

import json
import subprocess
import sys

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.utils.db_connector import read_sql, table_counts


def _quality_report() -> dict:
    """Load the latest detailed quality report."""
    path = st.session_state["project_root"] / "reports" / "quality_report_detail.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def render() -> None:
    """Render the ETL pipeline tab."""
    st.title("ETL Pipeline")

    st.subheader("Pipeline Flow")
    c1, c2, c3, c4 = st.columns(4)
    c1.info("Extract\nCSV, Excel, JSON")
    c2.info("Transform\nClean, validate, enrich")
    c3.info("Load\nSQLite warehouse")
    c4.info("Analyze\nSQL, Excel, Tableau")

    st.subheader("Warehouse Tables")
    st.dataframe(table_counts(), use_container_width=True, hide_index=True)

    st.subheader("ETL Run Log")
    try:
        runs = read_sql("SELECT * FROM etl_run_log ORDER BY run_id DESC LIMIT 20")
        st.dataframe(runs, use_container_width=True, hide_index=True)
    except Exception as exc:
        st.warning(f"Run log is not available yet: {exc}")

    report = _quality_report()
    score = float(report.get("overall_quality_score", 0))
    fig = go.Figure(go.Indicator(mode="gauge+number", value=score, gauge={"axis": {"range": [0, 100]}}))
    fig.update_layout(height=280, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Quality Issues"):
        rejections = report.get("orders", {}).get("rejections", {})
        if rejections:
            st.dataframe(pd.DataFrame(rejections.items(), columns=["issue", "rows"]), use_container_width=True, hide_index=True)
        else:
            st.write("No quality report found.")

    if st.button("Re-run ETL Pipeline"):
        with st.spinner("Running full ETL pipeline..."):
            result = subprocess.run(
                [sys.executable, "-m", "etl.pipeline"],
                cwd=st.session_state["project_root"],
                capture_output=True,
                text=True,
                timeout=180,
            )
        if result.returncode == 0:
            st.success("Pipeline completed successfully.")
            st.code(result.stdout[-4000:])
        else:
            st.error("Pipeline failed.")
            st.code(result.stderr[-4000:] or result.stdout[-4000:])

    st.subheader("Raw vs Clean Samples")
    left, right = st.columns(2)
    with left:
        st.caption("Clean orders")
        st.dataframe(read_sql("SELECT * FROM fact_orders LIMIT 10"), use_container_width=True)
    with right:
        st.caption("Returns")
        st.dataframe(read_sql("SELECT * FROM fact_returns LIMIT 10"), use_container_width=True)
