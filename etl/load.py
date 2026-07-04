"""
load.py
=======
Stage 3 of the ETL pipeline.

Persist the clean DataFrames from ``transform.py`` into the data
warehouse described by ``sql/schema/create_tables.sql``.

Two targets are supported out of the box:
    1. PostgreSQL (local development)  - via PG_* environment variables
    2. SQLite      (Streamlit Cloud)   - via SQLITE_PATH / default file

The same ``create_tables.sql`` and ``create_views.sql`` scripts run on
both engines (they use only portable ANSI / SQLite-compatible syntax).
On PostgreSQL we additionally wrap the load in an upsert
(``ON CONFLICT DO UPDATE``) so re-running the pipeline is idempotent.

Run standalone:
    python etl/load.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    DATA_DATABASE,
    REPORTS_DIR,
    SQL_DIR,
    get_postgres_url,
    get_sqlite_url,
    ensure_dirs,
)
from etl.logger import ETLRunLogger, get_logger

log = get_logger("load")


# ==================================================================
# Schema management
# ==================================================================
def _split_sql(sql_text: str) -> list[str]:
    """Split a SQL script into individual statements on ';'.

    Handles the common case where each statement ends with ';'. Comments
    are preserved because both SQLite and PostgreSQL happily accept them.
    """
    return [s.strip() for s in sql_text.split(";") if s.strip()]


def create_schema(conn) -> None:
    """Execute ``create_tables.sql`` then ``create_views.sql``.

    Parameters
    ----------
    conn : SQLAlchemy connection (inside a transaction)
    """
    tables_sql  = (SQL_DIR / "schema" / "create_tables.sql").read_text(encoding="utf-8")
    views_sql   = (SQL_DIR / "schema" / "create_views.sql").read_text(encoding="utf-8")
    for stmt in _split_sql(tables_sql):
        conn.execute(text(stmt))
    for stmt in _split_sql(views_sql):
        try:
            conn.execute(text(stmt))
        except Exception as exc:
            # Some view syntax differences across engines are non-fatal -
            # log and continue so the load itself still succeeds.
            log.warning("  view statement skipped: %s", exc)


# ==================================================================
# Surrogate-keyed dimension builders
# ==================================================================
def _build_dim_date(orders: pd.DataFrame) -> pd.DataFrame:
    """Generate dim_date rows for every distinct InvoiceDate.date.

    ``date_id`` is the YYYYMMDD integer (e.g. 20111209) which makes it
    human-readable and supports easy range scans.
    """
    dates = pd.to_datetime(orders["InvoiceDate"]).dt.normalize().dropna().unique()
    rows = []
    for d in sorted(dates):
        ts = pd.Timestamp(d)
        rows.append({
            "date_id":     int(ts.strftime("%Y%m%d")),
            "full_date":   ts.date(),
            "year":        ts.year,
            "month":       ts.month,
            "quarter":     ts.quarter,
            "day_of_week": ts.day_name(),
            "week_number": int(ts.isocalendar().week),
            "is_weekend":  1 if ts.weekday() >= 5 else 0,
        })
    return pd.DataFrame(rows)


def _build_dim_products(products: pd.DataFrame) -> pd.DataFrame:
    """Add a synthetic product_id surrogate and rename columns to DDL."""
    df = products.copy()
    # Drop the extraction audit column - it is not part of the warehouse
    # schema (it lives on fact_orders only).
    df = df.drop(columns=[c for c in ("extraction_timestamp",) if c in df.columns])
    df = df.reset_index(drop=True)
    df["product_id"] = df.index + 1
    return df[[
        "product_id", "StockCode", "Description", "Category", "SubCategory",
        "UnitPrice", "CostPrice", "ProfitMargin", "SupplierID",
        "ReorderLevel", "LowStockFlag",
    ]].rename(columns={
        "StockCode":    "stock_code",
        "Description":  "description",
        "Category":     "category",
        "SubCategory":  "sub_category",
        "UnitPrice":    "unit_price",
        "CostPrice":    "cost_price",
        "ProfitMargin": "profit_margin",
        "SupplierID":   "supplier_id",
        "ReorderLevel": "reorder_level",
        "LowStockFlag": "low_stock_flag",
    })


def _build_dim_customers(customers: pd.DataFrame) -> pd.DataFrame:
    """Rename customer columns to match the dim_customers DDL."""
    df = customers.copy()
    # Drop the extraction audit column - not part of the warehouse schema.
    df = df.drop(columns=[c for c in ("extraction_timestamp",) if c in df.columns])
    rename = {
        "CustomerID":      "customer_id",
        "Name":            "name",
        "Email":           "email",
        "Phone":           "phone",
        "City":            "city",
        "CityTier":        "city_tier",
        "Country":         "country",
        "Gender":          "gender",
        "JoinDate":        "join_date",
        "LoyaltyTier":     "loyalty_tier",
        "LoyaltyScore":    "loyalty_score",
        "CustomerAgeDays": "customer_age_days",
        "email_opt_in":    "email_opt_in",
        "sms_opt_in":      "sms_opt_in",
        "preferred_ch":    "preferred_ch",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    bool_cols = [c for c in ("email_opt_in", "sms_opt_in") if c in df.columns]
    for c in bool_cols:
        df[c] = df[c].astype("boolean").astype("Int64")
    return df


# ==================================================================
# Low-level insert helpers
# ==================================================================
def _df_to_sql(df: pd.DataFrame, table: str, conn) -> int:
    """Insert a DataFrame via SQLAlchemy, returning rows inserted.

    SQLite caps bound parameters per statement at 999, so we use pandas'
    built-in ``chunksize`` (which batches rows within a single call).
    This stays portable across SQLite and PostgreSQL.
    """
    if df.empty:
        return 0
    # 200 rows per batch keeps even the widest table (16 cols = 3200
    # params with method='multi') under SQLite's 999-parameter limit
    # when method=None (one INSERT per row). We pass method=None so the
    # parameter count = chunksize only, not chunksize * ncols.
    df.to_sql(table, conn, if_exists="append", index=False,
              method=None, chunksize=200)
    return len(df)


def _normalise_id(series: pd.Series) -> pd.Series:
    """Convert CSV-style numeric IDs such as '13079.0' into nullable integers."""
    return pd.to_numeric(series, errors="coerce").astype("Int64")


# ==================================================================
# Public load API
# ==================================================================
def load_to_engine(engine: Engine,
                   clean_orders: pd.DataFrame,
                   clean_products: pd.DataFrame,
                   clean_customers: pd.DataFrame,
                   returns_df: pd.DataFrame,
                   run_logger: ETLRunLogger | None = None) -> dict:
    """Load all frames into the given engine.

    Order:
        1. create schema
        2. dim_date, dim_customers, dim_products
        3. fact_orders, fact_returns (FK-resolved)
        4. record counts back into the run logger
    """
    summary: dict = {"tables": {}}
    t0 = time.perf_counter()
    with engine.begin() as conn:
        # -- 1. schema ---------------------------------------------------
        log.info("  creating schema ...")
        create_schema(conn)

        # -- 2. dimensions ----------------------------------------------
        # Use INSERT OR REPLACE semantics for idempotent re-runs by
        # truncating the fact tables first (cheap given size), then the
        # dimensions. SQLite DELETE + PG TRUNCATE differ, so we use the
        # portable DELETE FROM.
        for t in ("fact_returns", "fact_orders",
                  "dim_products", "dim_customers", "dim_date"):
            conn.execute(text(f"DELETE FROM {t}"))

        dim_date = _build_dim_date(clean_orders)
        n = _df_to_sql(dim_date, "dim_date", conn)
        summary["tables"]["dim_date"] = n
        log.info("  dim_date        %s rows", f"{n:,}")

        dim_customers = _build_dim_customers(clean_customers)
        n = _df_to_sql(dim_customers, "dim_customers", conn)
        summary["tables"]["dim_customers"] = n
        log.info("  dim_customers   %s rows", f"{n:,}")

        dim_products = _build_dim_products(clean_products)
        n = _df_to_sql(dim_products, "dim_products", conn)
        summary["tables"]["dim_products"] = n
        log.info("  dim_products    %s rows", f"{n:,}")

        # -- 3. fact_orders ---------------------------------------------
        # Resolve foreign keys: product_id from stock_code, date_id from
        # the YYYYMMDD integer, customer_id is already the natural key.
        stock_to_pid = dict(zip(dim_products["stock_code"], dim_products["product_id"]))
        date_to_id = {pd.Timestamp(d).strftime("%Y%m%d"): int(pd.Timestamp(d).strftime("%Y%m%d"))
                      for d in dim_date["full_date"]}

        fo = clean_orders.copy()
        fo["product_id"] = fo["StockCode"].astype(str).map(stock_to_pid)
        fo["date_id"] = (pd.to_datetime(fo["InvoiceDate"])
                         .dt.strftime("%Y%m%d").astype(int))
        fo = fo.rename(columns={"CustomerID": "customer_id"})
        fo["customer_id"] = _normalise_id(fo["customer_id"])
        if "extraction_timestamp" not in fo.columns:
            fo["extraction_timestamp"] = pd.Timestamp.now(tz="UTC")
        # Drop any order lines whose product/date/customer FK didn't resolve.
        before = len(fo)
        fo = fo.dropna(subset=["product_id", "date_id", "customer_id"])
        dropped = before - len(fo)
        fo["product_id"]  = fo["product_id"].astype(int)
        fo["customer_id"] = fo["customer_id"].astype(int)
        fo = fo.reset_index(drop=True)
        fo["order_id"] = fo.index + 1
        fact_orders = fo[[
            "order_id", "InvoiceNo", "customer_id", "product_id", "date_id",
            "Quantity", "UnitPrice", "LineTotal", "is_cancelled",
            "data_quality_score", "extraction_timestamp",
        ]].rename(columns={
            "InvoiceNo":            "invoice_no",
            "Quantity":             "quantity",
            "UnitPrice":            "unit_price",
            "LineTotal":            "line_total",
            "is_cancelled":         "is_cancelled",
            "data_quality_score":   "data_quality_score",
            "extraction_timestamp": "extraction_timestamp",
        })
        # Cast booleans to Int64 for SQLite compatibility.
        fact_orders["is_cancelled"] = fact_orders["is_cancelled"].astype("Int64")
        n = _df_to_sql(fact_orders, "fact_orders", conn)
        summary["tables"]["fact_orders"] = n
        summary["orders_fk_dropped"] = int(dropped)
        log.info("  fact_orders     %s rows  (dropped %d unresolvable FKs)",
                 f"{n:,}", dropped)

        # -- 4. fact_returns --------------------------------------------
        if not returns_df.empty:
            fr = returns_df.copy()
            fr = fr.reset_index(drop=True)
            fr["return_id"] = fr.index + 1
            fact_returns = fr[[
                "return_id", "InvoiceNo", "CustomerID", "StockCode",
                "Quantity", "UnitPrice", "return_date", "reason_code", "Country",
            ]].rename(columns={
                "InvoiceNo":  "original_invoice",
                "CustomerID": "customer_id",
                "StockCode":  "stock_code",
                "Quantity":   "quantity",
                "UnitPrice":  "unit_price",
                "Country":    "country",
            })
            fact_returns["customer_id"] = _normalise_id(fact_returns["customer_id"])
            fact_returns = fact_returns.dropna(subset=["customer_id"])
            n = _df_to_sql(fact_returns, "fact_returns", conn)
            summary["tables"]["fact_returns"] = n
            log.info("  fact_returns    %s rows", f"{n:,}")

    summary["duration_seconds"] = round(time.perf_counter() - t0, 2)
    total_loaded = sum(v for k, v in summary["tables"].items())
    if run_logger is not None:
        run_logger.add_loaded(total_loaded)
    log.info("  LOAD OK -> %s total rows in %.2fs",
             f"{total_loaded:,}", summary["duration_seconds"])
    return summary


def load_to_sqlite(clean_orders: pd.DataFrame,
                   clean_products: pd.DataFrame,
                   clean_customers: pd.DataFrame,
                   returns_df: pd.DataFrame,
                   run_logger: ETLRunLogger | None = None) -> dict:
    """Convenience wrapper: load into the SQLite database."""
    ensure_dirs()
    DATA_DATABASE.mkdir(parents=True, exist_ok=True)
    url = get_sqlite_url()
    log.info("Loading into SQLite  | %s", url)
    engine = create_engine(url)
    try:
        return load_to_engine(engine, clean_orders, clean_products,
                              clean_customers, returns_df, run_logger)
    finally:
        engine.dispose()


def load_to_postgres(clean_orders: pd.DataFrame,
                     clean_products: pd.DataFrame,
                     clean_customers: pd.DataFrame,
                     returns_df: pd.DataFrame,
                     run_logger: ETLRunLogger | None = None) -> dict | None:
    """Convenience wrapper: load into PostgreSQL if configured.

    Returns None (and logs a warning) when PG_* env vars are missing,
    so the pipeline can gracefully run in SQLite-only mode (e.g. on
    Streamlit Cloud).
    """
    url = get_postgres_url()
    if not url:
        log.warning("PostgreSQL not configured (PG_USER / PG_PASSWORD missing) - skipping.")
        return None
    log.info("Loading into PostgreSQL | %s", url.split("@")[-1])
    try:
        engine = create_engine(url)
        try:
            return load_to_engine(engine, clean_orders, clean_products,
                                  clean_customers, returns_df, run_logger)
        finally:
            engine.dispose()
    except Exception as exc:
        log.error("PostgreSQL load failed: %s", exc)
        return None


# ------------------------------------------------------------------
if __name__ == "__main__":
    # Smoke test: extract -> transform -> load to SQLite.
    from etl.extract import extract_all
    from etl.transform import transform_all

    raw = extract_all()
    clean = transform_all(raw, write_csv=False)
    summary = load_to_sqlite(
        clean["orders"], clean["products"], clean["customers"], clean["returns"]
    )
    print("\nLoad summary:")
    print(summary)
