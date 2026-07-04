"""SQL explorer tab for the Streamlit app."""
from __future__ import annotations

import re
import time
from pathlib import Path

import streamlit as st

from app.utils.db_connector import read_sql


def _load_queries(sql_dir: Path) -> dict[str, dict[str, str]]:
    """Parse SQL files into selectable query blocks."""
    queries: dict[str, dict[str, str]] = {}
    for path in sorted(sql_dir.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        chunks = [chunk.strip() for chunk in text.split(";") if chunk.strip()]
        for chunk in chunks:
            name_match = re.search(r"--\s*(Q\d+:[^\n]+|Query name:[^\n]+)", chunk)
            question_match = re.search(r"--\s*Business question:\s*([^\n]+)", chunk)
            output_match = re.search(r"--\s*Expected output:\s*([^\n]+)", chunk)
            title = name_match.group(1).replace("Query name:", "").strip() if name_match else f"{path.stem} query"
            queries[f"{path.stem} - {title}"] = {
                "sql": chunk,
                "question": question_match.group(1).strip() if question_match else "Business question documented in SQL comments.",
                "output": output_match.group(1).strip() if output_match else "Tabular query output.",
            }
    return queries


def render() -> None:
    """Render the SQL explorer tab."""
    st.title("SQL Explorer")
    query_map = _load_queries(st.session_state["project_root"] / "sql" / "analysis")
    selected = st.selectbox("Select one of the 27 SQL analysis queries", list(query_map))
    query = query_map[selected]
    st.caption(query["question"])
    st.caption(query["output"])
    st.code(query["sql"], language="sql")

    if st.button("Execute Selected Query"):
        start = time.perf_counter()
        try:
            df = read_sql(query["sql"])
            elapsed = time.perf_counter() - start
            st.success(f"Query completed in {elapsed:.3f}s with {len(df):,} rows.")
            st.dataframe(df, use_container_width=True)
            st.download_button("Download Results CSV", df.to_csv(index=False), "query_results.csv", "text/csv")
            st.session_state["last_query_results"] = df
        except Exception as exc:
            st.error(f"Query failed: {exc}")

    st.subheader("Custom SQL")
    custom_sql = st.text_area("Write your own SQLite query", "SELECT * FROM fact_orders LIMIT 20", height=160)
    if st.button("Execute Custom SQL"):
        try:
            df = read_sql(custom_sql)
            st.dataframe(df, use_container_width=True)
            st.download_button("Download Custom Results CSV", df.to_csv(index=False), "custom_query_results.csv", "text/csv")
        except Exception as exc:
            st.error(f"Custom query failed: {exc}")
