"""Interactive dashboard tab for Streamlit."""
from __future__ import annotations

import streamlit as st

from app.utils.chart_builder import category_treemap, cohort_heatmap, country_revenue_chart, monthly_revenue_chart, rfm_donut_chart
from app.utils.db_connector import read_sql


def render() -> None:
    """Render Plotly dashboard charts."""
    st.title("Dashboard")

    kpi = read_sql((st.session_state["project_root"] / "sql" / "kpis" / "master_kpis.sql").read_text(encoding="utf-8")).iloc[0]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Revenue", f"GBP {kpi.total_revenue/1_000_000:.2f}M")
    c2.metric("Orders", f"{int(kpi.total_orders):,}")
    c3.metric("AOV", f"GBP {kpi.avg_order_value:,.2f}")
    c4.metric("Return Rate", f"{kpi.return_rate_pct:.1f}%")

    monthly = read_sql("""
        SELECT printf('%04d-%02d', d.year, d.month) AS year_month,
               ROUND(SUM(o.line_total), 2) AS revenue,
               COUNT(DISTINCT o.invoice_no) AS orders
        FROM fact_orders o
        JOIN dim_date d ON o.date_id = d.date_id
        GROUP BY d.year, d.month
        ORDER BY d.year, d.month
    """)
    country = read_sql("""
        SELECT c.country, ROUND(SUM(o.line_total), 2) AS revenue
        FROM fact_orders o
        JOIN dim_customers c ON o.customer_id = c.customer_id
        GROUP BY c.country
        ORDER BY revenue DESC
        LIMIT 12
    """)
    left, right = st.columns(2)
    left.plotly_chart(monthly_revenue_chart(monthly), use_container_width=True)
    right.plotly_chart(country_revenue_chart(country), use_container_width=True)

    rfm = read_sql("""
        SELECT segment, COUNT(*) AS customers
        FROM v_rfm
        GROUP BY segment
        ORDER BY customers DESC
    """)
    category = read_sql("SELECT category, revenue, avg_margin_pct FROM v_category_performance")
    left, right = st.columns(2)
    left.plotly_chart(rfm_donut_chart(rfm), use_container_width=True)
    right.plotly_chart(category_treemap(category), use_container_width=True)

    cohort_sql = (st.session_state["project_root"] / "sql" / "analysis" / "04_cohort_retention.sql").read_text(encoding="utf-8").split(";")[0]
    cohort = read_sql(cohort_sql)
    st.plotly_chart(cohort_heatmap(cohort), use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.subheader("Pricing Flags")
        price_sql = (st.session_state["project_root"] / "sql" / "analysis" / "05_dark_pattern_detection.sql").read_text(encoding="utf-8").split(";")[1]
        st.dataframe(read_sql(price_sql).head(20), use_container_width=True, hide_index=True)
    with right:
        st.subheader("Churn Risk Customers")
        churn_sql = (st.session_state["project_root"] / "sql" / "analysis" / "02_customer_rfm.sql").read_text(encoding="utf-8").split(";")[3]
        st.dataframe(read_sql(churn_sql).head(20), use_container_width=True, hide_index=True)
