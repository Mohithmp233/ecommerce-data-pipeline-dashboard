"""
config.py
=========
Central configuration for the entire E-Commerce pipeline project.

Why a single config module?
    * Every script (etl/*, reports/*, app/*, notebooks) resolves paths
      the same way, so the project works whether it is run from the
      project root, from inside a sub-folder, or on Streamlit Cloud
      (where the working directory differs from local).
    * Database connection details are loaded once from environment
      variables (via python-dotenv) and exposed as simple attributes.

Usage
-----
    >>> from config import PROJECT_ROOT, DATA_RAW, SQLITE_PATH
    >>> from config import get_postgres_url, get_sqlite_url
"""
from __future__ import annotations

import os
from pathlib import Path

# Try to load variables from a .env file if python-dotenv is installed.
try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env") if "PROJECT_ROOT" in dir() else load_dotenv()
except Exception:
    # dotenv is optional - environment variables can still be set manually.
    pass


# ------------------------------------------------------------------
# Path resolution
# ------------------------------------------------------------------
# Walk up from this file until we hit the project root (the folder that
# contains requirements.txt). This makes the module import-safe from any
# working directory.
_THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = _THIS_FILE.parent
while PROJECT_ROOT != PROJECT_ROOT.parent:
    if (PROJECT_ROOT / "requirements.txt").exists():
        break
    PROJECT_ROOT = PROJECT_ROOT.parent

DATA_DIR        = PROJECT_ROOT / "data"
DATA_RAW        = DATA_DIR / "raw"
DATA_PROCESSED  = DATA_DIR / "processed"
DATA_DATABASE   = DATA_DIR / "database"
SQL_DIR         = PROJECT_ROOT / "sql"
REPORTS_DIR     = PROJECT_ROOT / "reports"
ETL_DIR         = PROJECT_ROOT / "etl"
APP_DIR         = PROJECT_ROOT / "app"

# Concrete source / sink files
ORDERS_CSV      = DATA_RAW / "orders.csv"
PRODUCTS_XLSX   = DATA_RAW / "products.xlsx"
CUSTOMERS_JSON  = DATA_RAW / "customers.json"

ORDERS_CLEAN_CSV    = DATA_PROCESSED / "orders_clean.csv"
PRODUCTS_CLEAN_CSV  = DATA_PROCESSED / "products_clean.csv"
CUSTOMERS_CLEAN_CSV = DATA_PROCESSED / "customers_clean.csv"

# Default SQLite location (overridable via env var).
_default_sqlite = os.getenv(
    "SQLITE_PATH", "data/database/ecommerce.db"
)
SQLITE_PATH = (PROJECT_ROOT / _default_sqlite).resolve() if not Path(_default_sqlite).is_absolute() else Path(_default_sqlite)

# Quality / run-log artefacts (regenerated each run).
QUALITY_REPORT_PATH = PROJECT_ROOT / "quality_report.json"


# ------------------------------------------------------------------
# Database connection helpers
# ------------------------------------------------------------------
def get_postgres_url() -> str | None:
    """Build a SQLAlchemy URL for PostgreSQL from env vars.

    Returns
    -------
    str or None
        A ``postgresql+psycopg2://...`` URL, or ``None`` if the required
        environment variables are not set. Returning None lets the
        pipeline gracefully fall back to SQLite-only mode (e.g. on
        Streamlit Cloud where no Postgres is available).
    """
    user = os.getenv("PG_USER")
    pwd  = os.getenv("PG_PASSWORD")
    host = os.getenv("PG_HOST", "localhost")
    port = os.getenv("PG_PORT", "5432")
    name = os.getenv("PG_NAME", "ecommerce")
    if not user or not pwd:
        return None
    return f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}"


def get_sqlite_url() -> str:
    """Build a SQLAlchemy URL for the local SQLite database.

    The parent directory is created on demand so the very first run
    never fails with "unable to open database file".
    """
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{SQLITE_PATH.as_posix()}"


def ensure_dirs() -> None:
    """Create all project data folders if they don't exist yet.

    Safe to call repeatedly - uses ``exist_ok=True``.
    """
    for d in (DATA_RAW, DATA_PROCESSED, DATA_DATABASE, REPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    # Quick sanity check when run directly: ``python config.py``
    print(f"PROJECT_ROOT : {PROJECT_ROOT}")
    print(f"DATA_RAW     : {DATA_RAW}")
    print(f"SQLITE_PATH  : {SQLITE_PATH}")
    print(f"Postgres URL : {get_postgres_url() or '(not configured)'}")
    print(f"SQLite URL   : {get_sqlite_url()}")
