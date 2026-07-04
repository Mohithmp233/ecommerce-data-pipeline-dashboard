"""
extract.py
==========
Stage 1 of the ETL pipeline.

Pull raw data from the three project sources:
    1. ``orders.csv``     - Kaggle e-commerce transaction export
    2. ``products.xlsx``  - Product catalog (Excel)
    3. ``customers.json`` - Simulated REST API payload (local file)

Each extractor is self-contained, defensive (handles encoding quirks,
merged cells, nested JSON) and returns a pandas DataFrame with an
``extraction_timestamp`` column so downstream stages can audit when the
row was pulled.

Run standalone:
    python -m etl.extract          # extract everything
    python etl/extract.py          # same, run as script
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd

# Make ``config`` importable when this file is run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import CUSTOMERS_JSON, ORDERS_CSV, PRODUCTS_XLSX, ensure_dirs
from etl.logger import get_logger

log = get_logger("extract")


# ==================================================================
# 1. ORDERS - CSV (Kaggle export)
# ==================================================================
def extract_orders_csv(filepath: str | Path = ORDERS_CSV,
                       encoding: str | None = None) -> pd.DataFrame:
    """Read the raw e-commerce orders CSV.

    The Kaggle file ships as ``latin-1`` (it contains accented
    descriptions and the £-like chars in product names), so we try a
    small cascade of encodings before giving up.

    Parameters
    ----------
    filepath : str | Path
        Path to ``orders.csv``.
    encoding : str | None
        Force a specific encoding. If None the function tries
        ``["utf-8", "latin-1", "cp1252", "iso-8859-1"]`` in order.

    Returns
    -------
    pd.DataFrame
        Raw orders with an extra ``extraction_timestamp`` column.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"orders.csv not found at {filepath}")

    size_mb = filepath.stat().st_size / (1024 * 1024)
    log.info("Extracting orders CSV  | %s (%.2f MB)", filepath.name, size_mb)
    t0 = time.perf_counter()

    # Encoding cascade -------------------------------------------------
    candidates = [encoding] if encoding else ["utf-8", "latin-1", "cp1252", "iso-8859-1"]
    last_exc: Exception | None = None
    df: pd.DataFrame | None = None
    for enc in candidates:
        try:
            df = pd.read_csv(filepath, encoding=enc, dtype={"CustomerID": "string"})
            log.info("  encoding '%s' worked", enc)
            break
        except UnicodeDecodeError as exc:
            log.debug("  encoding '%s' failed: %s", enc, exc)
            last_exc = exc

    if df is None:
        raise last_exc or RuntimeError("Unable to read orders.csv with any encoding")

    # Audit column -----------------------------------------------------
    df["extraction_timestamp"] = pd.Timestamp.now(tz="UTC")
    elapsed = time.perf_counter() - t0
    log.info("  OK  -> %s rows | %d cols | %.2fs",
             f"{len(df):,}", df.shape[1], elapsed)
    return df


# ==================================================================
# 2. PRODUCTS - Excel catalog
# ==================================================================
def extract_products_excel(filepath: str | Path = PRODUCTS_XLSX) -> pd.DataFrame:
    """Read the product catalog from ``.xlsx``.

    Uses the ``openpyxl`` engine so merged cells (common when finance
    teams maintain the file) are handled gracefully. Sheet selection
    is automatic - the function picks the sheet with the most rows.

    Parameters
    ----------
    filepath : str | Path
        Path to ``products.xlsx``.

    Returns
    -------
    pd.DataFrame
        Raw products with an extra ``extraction_timestamp`` column.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"products.xlsx not found at {filepath}")

    size_kb = filepath.stat().st_size / 1024
    log.info("Extracting products XLSX | %s (%.1f KB)", filepath.name, size_kb)
    t0 = time.perf_counter()

    # Identify the sheet with the most data (the workbook may ship with
    # cover / summary tabs alongside the data tab).
    xls = pd.ExcelFile(filepath, engine="openpyxl")
    sheet_rows = {sh: pd.read_excel(xls, sheet_name=sh, nrows=1).shape[1] for sh in xls.sheet_names}
    # Heuristic: pick the sheet whose first row has >=3 non-null columns
    best_sheet = max(sheet_rows, key=sheet_rows.get)
    log.info("  using sheet '%s' (%d cols in header)", best_sheet, sheet_rows[best_sheet])

    # Read the full sheet; openpyxl already collapses merged cells to their
    # top-left value, so pandas sees NaN in the "ghost" cells. We then
    # forward-fill those so each row is self-describing.
    df = pd.read_excel(xls, sheet_name=best_sheet)
    merged_like = df.columns[df.columns.str.contains("category|supplier", case=False, na=False)]
    if len(merged_like):
        df[merged_like] = df[merged_like].ffill()

    df["extraction_timestamp"] = pd.Timestamp.now(tz="UTC")
    elapsed = time.perf_counter() - t0
    log.info("  OK  -> %s rows | %d cols | %.3fs",
             f"{len(df):,}", df.shape[1], elapsed)
    return df


# ==================================================================
# 3. CUSTOMERS - simulated REST API (JSON file)
# ==================================================================
def _flatten_marketing(record: dict) -> dict:
    """Flatten the nested ``Marketing`` block into top-level columns.

    Demonstrates the "parse nested JSON" requirement from the spec.
    """
    flat = dict(record)
    mkt = flat.pop("Marketing", {}) or {}
    flat["email_opt_in"] = mkt.get("email_opt_in")
    flat["sms_opt_in"]   = mkt.get("sms_opt_in")
    flat["preferred_ch"] = mkt.get("preferred_ch")
    return flat


def extract_customers_api(json_filepath: str | Path = CUSTOMERS_JSON,
                          endpoint: str | None = None) -> pd.DataFrame:
    """Simulate a REST API call that returns customer records.

    In production this function would hit a real endpoint, e.g.::

        import requests
        resp = requests.get(
            f"{endpoint}/api/v1/customers",
            headers={"Authorization": f"Bearer {os.getenv('CRM_TOKEN')}"},
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()           # list[dict]

    For this portfolio project the API is simulated by reading a local
    JSON file that mirrors the exact shape a real CRM endpoint returns
    (a list of customer objects, some of which contain a nested
    ``Marketing`` block).

    Parameters
    ----------
    json_filepath : str | Path
        Path to ``customers.json``.
    endpoint : str | None
        Optional real endpoint URL. If provided AND the ``requests``
        library is available AND ``CRM_TOKEN`` is set in the
        environment, a live GET is attempted; otherwise the local
        file is used.

    Returns
    -------
    pd.DataFrame
        Raw customers (nested ``Marketing`` flattened) with an
        ``extraction_timestamp`` column.
    """
    json_filepath = Path(json_filepath)
    log.info("Extracting customers API | %s", json_filepath.name)
    t0 = time.perf_counter()

    payload: list[dict[str, Any]] = []

    # --- Optional real-API path -------------------------------------
    if endpoint and os.getenv("CRM_TOKEN"):
        try:
            import requests  # type: ignore
            log.info("  calling live endpoint %s ...", endpoint)
            resp = requests.get(
                f"{endpoint.rstrip('/')}/api/v1/customers",
                headers={"Authorization": f"Bearer {os.getenv('CRM_TOKEN')}"},
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            log.warning("  live API call failed (%s) - falling back to file", exc)

    # --- File-based fallback / simulation ---------------------------
    if not payload:
        if not json_filepath.exists():
            raise FileNotFoundError(f"customers.json not found at {json_filepath}")
        size_kb = json_filepath.stat().st_size / 1024
        payload = json.loads(json_filepath.read_text(encoding="utf-8"))
        log.info("  simulated GET /api/v1/customers -> %d records (%.1f KB)",
                 len(payload), size_kb)

    # Normalise into a DataFrame, flattening any nested objects.
    rows = [_flatten_marketing(rec) for rec in payload]
    df = pd.DataFrame(rows)
    df["extraction_timestamp"] = pd.Timestamp.now(tz="UTC")

    elapsed = time.perf_counter() - t0
    log.info("  OK  -> %s rows | %d cols | %.3fs",
             f"{len(df):,}", df.shape[1], elapsed)
    return df


# ==================================================================
# Orchestration
# ==================================================================
def extract_all() -> dict[str, pd.DataFrame]:
    """Run all three extractors and return a labelled dict.

    Returns
    -------
    dict
        Keys: ``orders``, ``products``, ``customers``.
    """
    log.info("=" * 60)
    log.info("EXTRACT STAGE")
    log.info("=" * 60)
    ensure_dirs()
    out: dict[str, pd.DataFrame] = {}
    out["orders"]    = extract_orders_csv()
    out["products"]  = extract_products_excel()
    out["customers"] = extract_customers_api()
    log.info("-" * 60)
    log.info("Extract summary:")
    for name, df in out.items():
        log.info("  %-10s %s rows", name, f"{len(df):,}")
    return out


# ------------------------------------------------------------------
if __name__ == "__main__":
    data = extract_all()
    print("\nExtraction complete. Sample shapes:")
    for k, v in data.items():
        print(f"  {k:10s}: {v.shape}")
