"""Database helpers for the Streamlit app."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config import SQLITE_PATH


def get_connection(db_path: Path = SQLITE_PATH) -> sqlite3.Connection:
    """Return a SQLite connection with row dictionaries enabled."""
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def read_sql(query: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
    """Execute a SQL query against the project SQLite warehouse."""
    with sqlite3.connect(SQLITE_PATH) as conn:
        return pd.read_sql_query(query, conn, params=params or {})


def table_counts() -> pd.DataFrame:
    """Return row counts for the core warehouse tables."""
    tables = ["dim_date", "dim_customers", "dim_products", "fact_orders", "fact_returns", "etl_run_log"]
    rows = []
    with sqlite3.connect(SQLITE_PATH) as conn:
        for table in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            rows.append({"table_name": table, "row_count": count})
    return pd.DataFrame(rows)


def database_ready() -> bool:
    """Return True when the SQLite warehouse exists and is queryable."""
    if not SQLITE_PATH.exists():
        return False
    try:
        counts = table_counts()
        return not counts.empty
    except Exception:
        return False
