"""Downloads tab for Streamlit."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.utils.db_connector import read_sql
from reports.excel_generator import generate_weekly_report

TABLEAU_URL = "https://public.tableau.com/views/E-CommerceDataPipelineAnalyticsDashboard/ExecutiveOverview?:language=en-US&publish=yes&:sid=&:redirect=auth&:display_count=n&:origin=viz_share_link"


def _download_file(path: Path, label: str, mime: str) -> None:
    """Render a Streamlit download button for a local file."""
    if path.exists():
        st.download_button(label, path.read_bytes(), file_name=path.name, mime=mime)
    else:
        st.warning(f"Missing file: {path}")


def render() -> None:
    """Render downloads and external links."""
    st.title("Downloads")

    if st.button("Generate Excel Report"):
        with st.spinner("Generating Excel workbook..."):
            path, summary = generate_weekly_report()
        st.success(f"Generated {path.name}")
        st.json(summary)

    reports = sorted((st.session_state["project_root"] / "reports").glob("weekly_report_*.xlsx"))
    if reports:
        _download_file(reports[-1], "Download Latest Excel Report", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    st.subheader("Data Exports")
    for table in ["fact_orders", "fact_returns", "dim_customers", "dim_products", "etl_run_log"]:
        df = read_sql(f"SELECT * FROM {table}")
        st.download_button(f"Download {table}.csv", df.to_csv(index=False), f"{table}.csv", "text/csv")

    st.subheader("External Links")
    st.link_button("View Tableau Dashboard", TABLEAU_URL)
