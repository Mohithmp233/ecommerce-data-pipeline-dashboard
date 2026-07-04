"""
transform.py
============
Stage 2 of the ETL pipeline.

Receives raw DataFrames from ``extract.py`` and produces:
    * clean_* DataFrames ready to load into the data warehouse
    * a returns DataFrame (cancelled orders split off for fraud analysis)
    * a quality report dict (per-rule rejection counts + overall score)

Transformation rules are taken verbatim from the project brief:
    - drop null CustomerID
    - drop Quantity <= 0      (kept separately in returns_df)
    - drop UnitPrice <= 0
    - drop duplicate (InvoiceNo, StockCode) rows
    - parse InvoiceDate, derive calendar columns + LineTotal
    - standardise Country names
    - flag cancellations (InvoiceNo startswith 'C') into returns_df
    - compute a per-row data-quality score (0-100)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    CUSTOMERS_CLEAN_CSV,
    ORDERS_CLEAN_CSV,
    PRODUCTS_CLEAN_CSV,
    ensure_dirs,
)
from etl.logger import get_logger, write_quality_report

log = get_logger("transform")


# ------------------------------------------------------------------
# Reference data for standardisation
# ------------------------------------------------------------------
# Map common short codes / variants to canonical country names so the
# later "revenue by country" analysis is consistent.
COUNTRY_REMAP = {
    "UK":           "United Kingdom",
    "U.K.":         "United Kingdom",
    "England":      "United Kingdom",
    "EIRE":         "Ireland",
    "RSA":          "South Africa",
    "USA":          "United States",
    "UAE":          "United Arab Emirates",
}

# Loyalty tier -> numeric score (higher = more loyal). Used by both the
# customers transform and downstream SQL analysis.
LOYALTY_SCORE = {
    "Bronze":   1,
    "Silver":   2,
    "Gold":     3,
    "Platinum": 4,
}


# ==================================================================
# 1. ORDERS
# ==================================================================
def transform_orders(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Clean, validate and enrich the raw orders DataFrame.

    Returns
    -------
    (clean_orders_df, returns_df, quality_report) :
        - clean_orders_df : validated sale rows with derived columns
        - returns_df      : cancellation / refund rows (kept for the
                            fraud & return-rate analysis later)
        - quality_report  : dict of per-rule rejection counts + score
    """
    log.info("Transforming orders ...")
    t0 = time.perf_counter()
    report: dict = {"stage": "orders", "input_rows": int(len(df)), "rejections": {}}
    initial = len(df)

    # --- 0. Defensive copy + InvoiceDate parse ---------------------
    df = df.copy()
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")

    # --- 1. Flag cancellations (InvoiceNo starts with 'C') ---------
    df["InvoiceNo_str"] = df["InvoiceNo"].astype(str)
    df["is_cancelled"] = df["InvoiceNo_str"].str.startswith("C")

    # Pull cancellations out into a dedicated returns frame. These are
    # NOT deleted - they power the 06_return_fraud_analysis queries.
    returns_mask = df["is_cancelled"] | (df["Quantity"] <= 0)
    returns_df = df.loc[returns_mask].copy()
    returns_df["return_date"] = returns_df["InvoiceDate"]
    # Reason code = simple heuristic for later fraud analysis.
    returns_df["reason_code"] = np.where(
        returns_df["is_cancelled"], "CANCELLATION", "NEGATIVE_QTY"
    )
    report["rejections"]["cancellations_or_negative_qty"] = int(len(returns_df))

    # --- 2. Apply the hard cleaning rules --------------------------
    def _reject(mask: pd.Series, label: str) -> None:
        n = int(mask.sum())
        report["rejections"][label] = n

    # null CustomerID
    m = df["CustomerID"].isna()
    _reject(m, "null_customer_id")
    df = df.loc[~m]

    # Quantity <= 0 (already pulled into returns_df above)
    m = df["Quantity"] <= 0
    _reject(m, "quantity_le_zero")
    df = df.loc[~m]

    # UnitPrice <= 0
    m = df["UnitPrice"] <= 0
    _reject(m, "unitprice_le_zero")
    df = df.loc[~m]

    # duplicate (InvoiceNo, StockCode) combinations
    before = len(df)
    df = df.drop_duplicates(subset=["InvoiceNo", "StockCode"], keep="first")
    report["rejections"]["duplicate_invoice_stockcode"] = int(before - len(df))

    # --- 3. Derive calendar columns --------------------------------
    dt = df["InvoiceDate"]
    df["Year"]      = dt.dt.year
    df["Month"]     = dt.dt.month
    df["Quarter"]   = dt.dt.quarter
    df["DayOfWeek"] = dt.dt.day_name()
    df["Hour"]      = dt.dt.hour
    df["Date"]      = dt.dt.date

    # --- 4. Line total ---------------------------------------------
    df["LineTotal"] = (df["Quantity"] * df["UnitPrice"]).round(2)

    # --- 5. Standardise Country ------------------------------------
    df["Country"] = (
        df["Country"].astype(str).str.strip().replace(COUNTRY_REMAP)
    )

    # --- 6. Per-row data-quality score (0-100) ---------------------
    # Start at 100 and deduct for each "soft" issue. This is a relative
    # signal, not an absolute truth - used to surface suspicious rows.
    score = pd.Series(100, index=df.index, dtype=int)
    score -= np.where(df["Description"].isna() | (df["Description"].astype(str).str.strip() == ""), 15, 0)
    score -= np.where(df["UnitPrice"] > df["UnitPrice"].quantile(0.99), 10, 0)
    score -= np.where(df["Quantity"]  > df["Quantity"].quantile(0.99),  10, 0)
    df["data_quality_score"] = score.clip(lower=0, upper=100)

    # --- 7. Final column order -------------------------------------
    clean_cols = [
        "InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate",
        "UnitPrice", "CustomerID", "Country",
        "Year", "Month", "Quarter", "DayOfWeek", "Hour", "Date",
        "LineTotal", "is_cancelled", "data_quality_score",
    ]
    clean_orders = df.reindex(columns=clean_cols).reset_index(drop=True)

    # --- 8. Quality roll-up ----------------------------------------
    total_rejected = initial - len(clean_orders)
    report["clean_rows"]    = int(len(clean_orders))
    report["returns_rows"]  = int(len(returns_df))
    report["total_rejected"] = int(total_rejected)
    report["quality_score"] = round(
        100 * len(clean_orders) / max(initial, 1), 2
    )
    report["duration_seconds"] = round(time.perf_counter() - t0, 2)

    log.info("  clean=%s  returns=%s  rejected=%s  score=%.2f%%  (%.2fs)",
             f"{len(clean_orders):,}",
             f"{len(returns_df):,}",
             f"{total_rejected:,}",
             report["quality_score"],
             report["duration_seconds"])
    return clean_orders, returns_df, report


# ==================================================================
# 2. PRODUCTS
# ==================================================================
def transform_products(df: pd.DataFrame,
                       orders_prices: pd.DataFrame | None = None,
                       recent_units: pd.DataFrame | None = None) -> pd.DataFrame:
    """Standardise the product catalog and derive margin + stock flags.

    Parameters
    ----------
    df : pd.DataFrame
        Raw products frame from extract.py.
    orders_prices : pd.DataFrame | None
        Optional median price observed per StockCode in the orders data.
        When supplied it overrides the synthetic ``UnitPrice`` from the
        catalog so margin reflects the price customers actually paid.
    recent_units : pd.DataFrame | None
        Optional DataFrame with columns ``StockCode`` and ``UnitsSold``
        representing total quantity sold over a recent window (e.g. the
        last 6 months). Used to compute ``LowStockFlag`` - True when a
        product sold fewer units than its ``ReorderLevel``.
    """
    log.info("Transforming products ...")
    t0 = time.perf_counter()
    df = df.copy()

    # Title-case category + sub-category
    df["Category"]    = df["Category"].astype(str).str.strip().str.title()
    df["SubCategory"] = df.get("SubCategory", pd.Series(index=df.index)).astype(str).str.strip().str.title()
    df["Description"] = df["Description"].astype(str).str.strip().str.title()

    # Use observed median price from orders when available
    if orders_prices is not None and not orders_prices.empty:
        price_map = orders_prices.set_index("StockCode")["UnitPrice"].to_dict()
        df["UnitPrice"] = df["StockCode"].map(price_map).fillna(df["UnitPrice"])

    # Profit margin = (price - cost) / price * 100
    df["ProfitMargin"] = (
        (df["UnitPrice"] - df["CostPrice"]) / df["UnitPrice"].replace(0, np.nan) * 100
    ).round(2)

    # Low-stock flag: a product is "low stock" when recent sales volume
    # is below its reorder level (i.e. we are selling slower than we
    # restock, which signals dead inventory the business should clear).
    if recent_units is not None and not recent_units.empty:
        units_map = recent_units.set_index("StockCode")["UnitsSold"].to_dict()
        recent = df["StockCode"].map(units_map).fillna(0)
        df["LowStockFlag"] = recent < df["ReorderLevel"]
    else:
        df["LowStockFlag"] = False

    df = df.drop_duplicates(subset="StockCode").reset_index(drop=True)
    log.info("  clean=%s  avg margin=%.1f%%  low-stock=%d  (%.2fs)",
             f"{len(df):,}",
             float(df["ProfitMargin"].mean() or 0),
             int(df["LowStockFlag"].sum()),
             time.perf_counter() - t0)
    return df


# ==================================================================
# 3. CUSTOMERS
# ==================================================================
def transform_customers(df: pd.DataFrame,
                        reference_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """Standardise customer attributes and derive age + loyalty score.

    Parameters
    ----------
    df : pd.DataFrame
        Raw customers frame from extract.py.
    reference_date : pd.Timestamp | None
        "Today" for the CustomerAge calculation. Defaults to the
        e-commerce dataset's horizon (2011-12-09) so the metric is
        reproducible across runs.
    """
    log.info("Transforming customers ...")
    t0 = time.perf_counter()
    df = df.copy()

    if reference_date is None:
        reference_date = pd.Timestamp("2011-12-09")

    # Normalise CityTier -> "Tier 1" / "Tier 2" / "Tier 3"
    def _norm_tier(val) -> str:
        s = str(val).strip().lower().replace("_", " ")
        for n in ("1", "2", "3"):
            if n in s:
                return f"Tier {n}"
        return "Tier 3"   # safe default
    df["CityTier"] = df["CityTier"].apply(_norm_tier)

    df["Gender"]      = df["Gender"].fillna("Unknown").astype(str).str.title()
    df["LoyaltyTier"] = df["LoyaltyTier"].fillna("Bronze").astype(str).str.title()
    df["LoyaltyScore"] = df["LoyaltyTier"].map(LOYALTY_SCORE).fillna(1).astype(int)

    # Customer age in days since JoinDate
    join = pd.to_datetime(df["JoinDate"], errors="coerce")
    df["CustomerAgeDays"] = (reference_date - join).dt.days.clip(lower=0).fillna(0).astype(int)
    df["JoinDate"] = join.dt.date

    df = df.drop_duplicates(subset="CustomerID").reset_index(drop=True)
    log.info("  clean=%s  (%.2fs)", f"{len(df):,}", time.perf_counter() - t0)
    return df


# ==================================================================
# Orchestration
# ==================================================================
def transform_all(raw: dict[str, pd.DataFrame],
                  write_csv: bool = True) -> dict[str, pd.DataFrame | dict]:
    """Run every transform and (optionally) write clean CSVs.

    Parameters
    ----------
    raw : dict
        Output of ``extract_all()`` - keys ``orders``, ``products``,
        ``customers``.
    write_csv : bool
        If True, write the three clean frames to ``data/processed/``.

    Returns
    -------
    dict
        Keys: ``orders``, ``products``, ``customers``, ``returns``,
        ``quality_report``.
    """
    log.info("=" * 60)
    log.info("TRANSFORM STAGE")
    log.info("=" * 60)

    clean_orders, returns_df, q_orders = transform_orders(raw["orders"])

    # Build observed price table so the catalog margin uses real prices.
    obs = (
        raw["orders"]
        .groupby("StockCode")["UnitPrice"]
        .median()
        .reset_index()
    )

    # Build recent-units table (last 6 months) for the low-stock flag.
    # We use clean_orders here because it already has InvoiceDate parsed
    # and excludes cancellations.
    recent_units: pd.DataFrame | None = None
    if not clean_orders.empty and pd.api.types.is_datetime64_any_dtype(clean_orders["InvoiceDate"]):
        cutoff = clean_orders["InvoiceDate"].max() - pd.DateOffset(months=6)
        recent = clean_orders.loc[clean_orders["InvoiceDate"] >= cutoff]
        recent_units = (
            recent.groupby("StockCode")["Quantity"].sum()
                  .reset_index().rename(columns={"Quantity": "UnitsSold"})
        )

    clean_products = transform_products(
        raw["products"], orders_prices=obs, recent_units=recent_units
    )
    clean_customers = transform_customers(raw["customers"])

    quality_report = {
        "orders":   q_orders,
        "products": {"clean_rows": int(len(clean_products))},
        "customers":{"clean_rows": int(len(clean_customers))},
        "overall_quality_score": q_orders["quality_score"],
    }
    write_quality_report(quality_report)

    if write_csv:
        ensure_dirs()
        clean_orders.to_csv(ORDERS_CLEAN_CSV, index=False)
        clean_products.to_csv(PRODUCTS_CLEAN_CSV, index=False)
        clean_customers.to_csv(CUSTOMERS_CLEAN_CSV, index=False)
        log.info("  wrote %s, %s, %s",
                 ORDERS_CLEAN_CSV.name, PRODUCTS_CLEAN_CSV.name, CUSTOMERS_CLEAN_CSV.name)

    return {
        "orders":    clean_orders,
        "products":  clean_products,
        "customers": clean_customers,
        "returns":   returns_df,
        "quality_report": quality_report,
    }


# ------------------------------------------------------------------
if __name__ == "__main__":
    # Quick smoke test: extract -> transform
    from etl.extract import extract_all
    raw = extract_all()
    out = transform_all(raw)
    print("\nTransform complete:")
    for k, v in out.items():
        if isinstance(v, pd.DataFrame):
            print(f"  {k:15s}: {v.shape}")
        else:
            print(f"  {k:15s}: {v}")
