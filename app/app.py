"""Main Streamlit application for the e-commerce analytics project."""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.tabs import tab_charts, tab_downloads, tab_etl, tab_overview, tab_sql
from app.utils.db_connector import database_ready


def _inject_css() -> None:
    """Apply compact dashboard styling."""
    st.markdown(
        """
        <style>
        .block-container { padding-top: 2.25rem; padding-bottom: 2rem; }
        [data-testid="stMetricValue"] { font-size: 1.85rem; }
        [data-testid="stSidebar"] { border-right: 1px solid #e5e7eb; }
        .stTabs [data-baseweb="tab-list"] {
            gap: 10px;
            padding-top: 0.45rem;
            padding-bottom: 0.25rem;
            border-bottom: 1px solid rgba(160, 174, 192, 0.35);
        }
        .stTabs [data-baseweb="tab"] {
            height: 44px;
            padding: 10px 14px;
            line-height: 1.2;
            font-size: 0.98rem;
            font-weight: 650;
            align-items: center;
            white-space: nowrap;
        }
        .stTabs [aria-selected="true"] {
            color: #ff4b4b;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    """Run the Streamlit app."""
    st.set_page_config(
        page_title="E-Commerce Analytics Pipeline",
        page_icon="ðŸ“Š",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.session_state["project_root"] = PROJECT_ROOT
    _inject_css()

    with st.sidebar:
        st.title("E-Commerce Pipeline")
        st.caption("Python ETL, SQL analytics, Excel reporting, Tableau dashboards.")
        st.divider()
        st.write("Tech stack")
        st.code("Python | pandas | SQLite | SQL | openpyxl | Tableau | Streamlit")
        st.divider()
        st.write("Author")
        st.write("Mohith Kumar M P")

    if not database_ready():
        st.error("SQLite warehouse not found. Run `python -m etl.pipeline` from the project root first.")
        return

    tabs = st.tabs(["Overview", "ETL Pipeline", "SQL Explorer", "Dashboard", "Downloads"])
    with tabs[0]:
        tab_overview.render()
    with tabs[1]:
        tab_etl.render()
    with tabs[2]:
        tab_sql.render()
    with tabs[3]:
        tab_charts.render()
    with tabs[4]:
        tab_downloads.render()


if __name__ == "__main__":
    main()

