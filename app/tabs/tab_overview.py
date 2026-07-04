"""Overview tab for the Streamlit app."""
from __future__ import annotations

import streamlit as st

from app.utils.db_connector import read_sql

TABLEAU_URL = "https://public.tableau.com/views/E-CommerceDataPipelineAnalyticsDashboard/ExecutiveOverview?:language=en-US&publish=yes&:sid=&:redirect=auth&:display_count=n&:origin=viz_share_link"


def render() -> None:
    """Render the project overview tab."""
    st.title("E-Commerce Data Pipeline & Analytics Dashboard")
    st.caption("ETL pipeline, SQL analytics, Excel automation, Tableau dashboard, and Streamlit project viewer.")

    kpi = read_sql((st.session_state["project_root"] / "sql" / "kpis" / "master_kpis.sql").read_text(encoding="utf-8")).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue", f"GBP {kpi.total_revenue/1_000_000:.2f}M")
    c2.metric("Orders", f"{int(kpi.total_orders):,}")
    c3.metric("Customers", f"{int(kpi.active_customers):,}")
    c4.metric("Products", f"{int(kpi.total_products):,}")

    st.info(
        "Start with the Tableau dashboard, inspect the SQL explorer, then download the Excel report. "
        "The app is backed by the SQLite warehouse produced by the ETL pipeline."
    )

    st.subheader("Architecture")
    a, b, c, d = st.columns(4)
    a.info("Sources\n\nOrders CSV\n\nProducts Excel\n\nCustomers JSON")
    b.info("ETL\n\nExtract\n\nTransform\n\nLoad")
    c.info("Warehouse\n\nSQLite\n\nProcessed CSVs")
    d.info("Outputs\n\nSQL Explorer\n\nExcel Report\n\nTableau")

    st.subheader("Project Links")
    st.link_button("Open Tableau Public Dashboard", TABLEAU_URL)
