"""
generate_mock_data.py
=====================
Generate the two auxiliary data sources the project requires on top
of the Kaggle "E-Commerce Data" CSV:

    1. data/raw/products.xlsx   - product catalog (StockCode, Category,
        CostPrice, SupplierID, ReorderLevel). Joined to orders on StockCode.
    2. data/raw/customers.json  - simulated REST API payload
        (CustomerID, Name, Email, CityTier, JoinDate, Gender,
        LoyaltyTier). Joined to orders on CustomerID.

If the Kaggle ``orders.csv`` is NOT present in ``data/raw/``, this script
also synthesises a realistic fallback ``orders.csv`` so the entire
pipeline can be exercised end-to-end without an internet connection
(e.g. inside Streamlit Cloud's build step).

Run it standalone:
    python scripts/generate_mock_data.py
"""
from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make ``config`` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from faker import Faker

from config import CUSTOMERS_JSON, ORDERS_CSV, PRODUCTS_XLSX, ensure_dirs

fake = Faker("en_GB")
Faker.seed(42)
random.seed(42)
np.random.seed(42)

# ------------------------------------------------------------------
# Reference dictionaries used to make the synthetic data realistic.
# ------------------------------------------------------------------
CATEGORIES = {
    "Home": ["Decoration", "Furniture", "Lighting", "Storage", "Kitchenware"],
    "Apparel": ["Clothing", "Accessories", "Footwear"],
    "Electronics": ["Gadgets", "Accessories", "Audio"],
    "Beauty": ["Skincare", "Fragrance", "Cosmetics"],
    "Sports": ["Outdoor", "Fitness", "Bicycles"],
    "Toys": ["Games", "Puzzles", "Plush"],
    "Stationery": ["Paper", "Writing", "Art"],
    "Grocery": ["Snacks", "Beverages", "Pantry"],
}

CITY_TIERS = ["Tier 1", "Tier 2", "Tier 3"]
CITY_TIER_WEIGHTS = [0.45, 0.35, 0.20]   # most customers in metro cities
LOYALTY_TIERS = ["Bronze", "Silver", "Gold", "Platinum"]
LOYALTY_WEIGHTS = [0.45, 0.30, 0.18, 0.07]
GENDERS = ["Male", "Female", "Other"]
GENDER_WEIGHTS = [0.48, 0.49, 0.03]

# Sale-month spikes (used by dark-pattern detection queries later).
SALE_MONTHS = {11, 12, 1, 7}    # Black Friday, Christmas, New Year, Summer Sale

# A small fraction of products will exhibit a deliberate "dark pattern":
# price hikes ~3 weeks before a sale month, then a deep discount during it.
DARK_PATTERN_FRACTION = 0.10


# ==================================================================
# Product catalog generation
# ==================================================================
def _generate_stock_codes(n: int = 4_000) -> list[str]:
    """Return ``n`` unique 5-digit stock codes like '85123A'."""
    codes: set[str] = set()
    while len(codes) < n:
        num = random.randint(10000, 99999)
        suffix = random.choice(["", "", "", random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")])
        codes.add(f"{num}{suffix}")
    return sorted(codes)


def generate_products_catalog(stock_codes: list[str] | None = None,
                              n_products: int = 4_000,
                              output_path: Path = PRODUCTS_XLSX) -> pd.DataFrame:
    """Build ``products.xlsx`` keyed on StockCode.

    Parameters
    ----------
    stock_codes : list[str] or None
        If provided (typically extracted from the real orders.csv), the
        catalog is generated for exactly those codes so the join in
        load.py never misses. If None, ``n_products`` random codes are
        generated.
    n_products : int
        How many products to create when ``stock_codes`` is None.
    output_path : Path
        Destination ``.xlsx`` file.

    Returns
    -------
    pd.DataFrame
        The generated catalog.
    """
    if stock_codes is None:
        stock_codes = _generate_stock_codes(n_products)

    rows = []
    suppliers = [f"SUP-{1000 + i}" for i in range(60)]
    for code in stock_codes:
        category, sub = random.choice(list(CATEGORIES.items()))
        # Cost price mirrors the Kaggle "E-Commerce Data" range: most
        # items are inexpensive (£0.50 - £15) with a long tail.
        cost = round(random.uniform(0.30, 15.0), 2)
        # Markup 1.3x - 2.6x so profit margins land in a realistic
        # 20-75 % band (Kaggle prices cluster under £20).
        markup = random.uniform(1.3, 2.6)
        unit_price = round(cost * markup, 2)
        rows.append({
            "StockCode":     code,
            "Description":   fake.catch_phrase().title(),
            "Category":      category,
            "SubCategory":   sub,
            "UnitPrice":     unit_price,
            "CostPrice":     cost,
            "SupplierID":    random.choice(suppliers),
            "ReorderLevel":  random.randint(5, 100),
        })

    df = pd.DataFrame(rows).drop_duplicates(subset="StockCode")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_path, engine="openpyxl") as xl:
        df.to_excel(xl, index=False, sheet_name="products")
    print(f"  [products] wrote {len(df):,} rows -> {output_path}")
    return df


# ==================================================================
# Customers "API" payload generation
# ==================================================================
def generate_customers_api(customer_ids: list[int] | None = None,
                           n_customers: int = 6_000,
                           output_path: Path = CUSTOMERS_JSON) -> list[dict]:
    """Build ``customers.json`` keyed on CustomerID.

    The output mimics what a real REST endpoint would return:
    a JSON list of customer objects. See module docstring for the
    real ``requests.get()`` equivalent.
    """
    if customer_ids is None:
        customer_ids = random.sample(range(12000, 20000), n_customers)

    today = datetime(2011, 12, 9)   # anchor to the e-commerce dataset's horizon
    join_start = datetime(2008, 12, 9)   # customers joined up to 3 yrs before
    customers = []
    for cid in customer_ids:
        gender = random.choices(GENDERS, GENDER_WEIGHTS)[0]
        # Explicit anchors so JoinDate is reproducible and sits before the
        # dataset horizon (otherwise CustomerAgeDays computes as 0).
        join = fake.date_time_between(start_date=join_start, end_date=today)
        customers.append({
            "CustomerID":  cid,
            "Name":        fake.name(),
            "Email":       fake.unique.email(),
            "Phone":       fake.phone_number(),
            "CityTier":    random.choices(CITY_TIERS, CITY_TIER_WEIGHTS)[0],
            "City":        fake.city(),
            "Country":     "United Kingdom",
            "Gender":      gender,
            "JoinDate":    join.date().isoformat(),
            "LoyaltyTier": random.choices(LOYALTY_TIERS, LOYALTY_WEIGHTS)[0],
            # Nested block to exercise "parse nested JSON" in extract.py
            "Marketing":   {
                "email_opt_in":  random.random() > 0.2,
                "sms_opt_in":    random.random() > 0.6,
                "preferred_ch":  random.choice(["email", "sms", "app"]),
            },
        })
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(customers, fh, indent=2, default=str)
    print(f"  [customers] wrote {len(customers):,} rows -> {output_path}")
    return customers


# ==================================================================
# Optional fallback orders generator
# ==================================================================
def _synthesise_orders(catalog_df: pd.DataFrame,
                       n_rows: int = 60_000) -> pd.DataFrame:
    """Create a realistic orders DataFrame from the product catalog.

    Unit prices are derived from the catalog so the profit-margin
    analysis downstream tells a consistent business story. A small
    fraction of products is flagged as "dark pattern": their price
    is inflated ~3 weeks before each sale month then discounted
    heavily during the sale, which gives the price-inflation queries
    (Q19-Q21) real signal to detect.

    Parameters
    ----------
    catalog_df : pd.DataFrame
        Output of ``generate_products_catalog``. Must contain at least
        ``StockCode``, ``UnitPrice`` and ``Description``.
    n_rows : int
        Number of order lines to synthesise.

    Returns
    -------
    pd.DataFrame
        Columns mirror the Kaggle "E-Commerce Data" schema.
    """
    countries = (
        ["United Kingdom"] * 10
        + ["Germany", "France", "EIRE", "Spain", "Netherlands",
           "Belgium", "Switzerland", "Portugal", "Australia",
           "Norway", "Italy", "Poland", "Japan", "Sweden"]
    )

    codes = catalog_df["StockCode"].tolist()
    base_price = dict(zip(catalog_df["StockCode"], catalog_df["UnitPrice"]))
    desc = dict(zip(catalog_df["StockCode"], catalog_df["Description"]))

    # Pick which products exhibit the dark-pattern behaviour.
    rng = random.Random(7)
    dark_codes = set(rng.sample(codes, max(1, int(len(codes) * DARK_PATTERN_FRACTION))))

    start = datetime(2010, 12, 1)
    end   = datetime(2011, 12, 9)
    span_seconds = int((end - start).total_seconds())

    invoice_no = 500000
    rows = []
    current_dt = None
    customer = None
    items_in_invoice = 0

    for _ in range(n_rows):
        # ~70 % chance to start a new invoice every line
        if current_dt is None or items_in_invoice >= random.randint(1, 8) or random.random() < 0.25:
            invoice_no += 1
            current_dt = start + timedelta(seconds=random.randint(0, span_seconds))
            customer = random.randint(12000, 18000)
            items_in_invoice = 0
        items_in_invoice += 1

        # ~7 % of lines are cancellations (InvoiceNo starts with 'C')
        is_cancel = random.random() < 0.07
        inv = f"C{invoice_no}" if is_cancel else f"{invoice_no}"
        qty = -abs(random.randint(1, 50)) if is_cancel else random.randint(1, 50)
        # Inject some negative/zero garbage for the data-quality rules
        if random.random() < 0.01:
            qty = random.choice([0, -qty if qty > 0 else qty])

        code = random.choice(codes)
        price = float(base_price[code])

        # Price dynamics ------------------------------------------------
        if code in dark_codes:
            # Inflate 14-21 days before a sale month, then drop during it.
            month = current_dt.month
            if month in SALE_MONTHS:
                price *= 0.70                       # deep sale discount
            elif current_dt + timedelta(days=21) >= datetime(current_dt.year, min(current_dt.month + 1, 12), 1) \
                 and (current_dt.month + 1) in SALE_MONTHS:
                price *= 1.25                       # pre-sale inflation
        # Normal per-invoice jitter (+/-5%)
        price *= random.uniform(0.95, 1.05)

        if random.random() < 0.005:
            price = 0.0   # rare bad-data row for the cleaning rules

        rows.append({
            "InvoiceNo":    inv,
            "StockCode":    code,
            "Description":  desc[code],
            "Quantity":     qty,
            "InvoiceDate":  current_dt,
            "UnitPrice":    round(price, 2),
            "CustomerID":   customer if random.random() > 0.02 else None,
            "Country":      random.choice(countries),
        })
    df = pd.DataFrame(rows)
    return df


def generate_orders_fallback(catalog_df: pd.DataFrame,
                             output_path: Path = ORDERS_CSV,
                             n_rows: int = 60_000) -> Path:
    """Synthesise orders.csv when the Kaggle dataset is unavailable."""
    df = _synthesise_orders(catalog_df, n_rows=n_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="latin-1")
    print(f"  [orders] wrote {len(df):,} synthetic rows -> {output_path}")
    return output_path


# ==================================================================
# Orchestration
# ==================================================================
def main(force_orders: bool = False, n_orders: int = 60_000) -> None:
    """Generate all three raw sources.

    Order of operations is important: the product catalog is generated
    FIRST so the synthetic orders can derive their UnitPrice from it.
    If a real Kaggle orders.csv is present it is kept untouched, and
    the catalog is then aligned to the real StockCodes.

    Parameters
    ----------
    force_orders : bool
        If True, always (re)generate the synthetic orders.csv even if a
        real file already exists. Default False - we keep the
        real data when present.
    n_orders : int
        Row count for the synthetic orders fallback.
    """
    print("=" * 60)
    print("  E-Commerce mock-data generator")
    print("=" * 60)
    ensure_dirs()

    # --- 1. Decide whether real orders exist ----------------------
    real_present = ORDERS_CSV.exists() and ORDERS_CSV.stat().st_size > 1_000_000

    # --- 2. Build the product catalog ------------------------------
    # When real orders exist, align the catalog to their StockCodes.
    # Otherwise the catalog uses random codes and orders are derived
    # from it afterwards.
    stock_codes = None
    if real_present and not force_orders:
        try:
            orders_df = pd.read_csv(ORDERS_CSV, encoding="latin-1",
                                    dtype={"CustomerID": "Float64"})
            if "StockCode" in orders_df.columns:
                stock_codes = sorted(set(orders_df["StockCode"].dropna().astype(str)))
                stock_codes = [c for c in stock_codes if any(ch.isdigit() for ch in c)]
        except Exception as exc:
            print(f"  [warn] could not read existing {ORDERS_CSV}: {exc}")

    catalog_df = generate_products_catalog(stock_codes=stock_codes)

    # --- 3. Orders -------------------------------------------------
    if real_present and not force_orders:
        print(f"  [orders] real dataset found at {ORDERS_CSV} - keeping it.")
    else:
        print("  [orders] no real dataset found - generating synthetic fallback.")
        generate_orders_fallback(catalog_df, ORDERS_CSV, n_rows=n_orders)

    # (Re)read orders so customer alignment uses the actual ids.
    try:
        orders_df = pd.read_csv(ORDERS_CSV, encoding="latin-1",
                                dtype={"CustomerID": "Float64"})
    except Exception as exc:
        print(f"  [warn] could not read {ORDERS_CSV}: {exc}")
        orders_df = pd.DataFrame()

    # --- 4. Customers (aligned to real CustomerIDs) ---------------
    customer_ids = None
    if not orders_df.empty and "CustomerID" in orders_df.columns:
        customer_ids = sorted(set(orders_df["CustomerID"].dropna().astype(int).tolist()))
    generate_customers_api(customer_ids=customer_ids)

    print("=" * 60)
    print("  Done. All raw sources are ready in data/raw/")
    print("=" * 60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate mock e-commerce data.")
    parser.add_argument("--force-orders", action="store_true",
                        help="Regenerate the synthetic orders.csv even if a real one exists.")
    parser.add_argument("--n-orders", type=int, default=60_000,
                        help="Row count for the synthetic orders fallback.")
    args = parser.parse_args()
    main(force_orders=args.force_orders, n_orders=args.n_orders)
