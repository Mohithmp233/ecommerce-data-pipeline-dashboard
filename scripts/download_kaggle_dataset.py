"""
download_kaggle_dataset.py
==========================
One-shot helper that downloads the primary Kaggle dataset
"carrie1/ecommerce-data" into ``data/raw/orders.csv``.

Two modes:
    1. If the ``kaggle`` CLI + credentials are configured, it uses
       ``kagglehub`` to fetch the dataset directly.
    2. Otherwise it prints step-by-step instructions for the manual
       download (click "Download" on the Kaggle page, unzip, move file).

Environment variables (set in .env or your shell):
    KAGGLE_USERNAME
    KAGGLE_KEY
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import DATA_RAW, ORDERS_CSV, ensure_dirs

DATASET_SLUG = "carrie1/ecommerce-data"
KAGGLE_URL   = "https://www.kaggle.com/datasets/carrie1/ecommerce-data"


def download_via_kagglehub() -> bool:
    """Attempt an automatic download using kagglehub.

    Returns True on success, False if it could not run.
    """
    try:
        import kagglehub  # type: ignore
    except ImportError:
        print("[kaggle] kagglehub not installed - skipping auto-download.")
        print("         Install with:  pip install kagglehub")
        return False

    if not (os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")):
        print("[kaggle] KAGGLE_USERNAME / KAGGLE_KEY not set - skipping auto-download.")
        return False

    print(f"[kaggle] downloading {DATASET_SLUG} ...")
    try:
        path = kagglehub.dataset_download(DATASET_SLUG)
    except Exception as exc:
        print(f"[kaggle] download failed: {exc}")
        return False

    # The dataset ships as 'data.csv' or 'e-commerce-data.csv' depending
    # on the API version - locate the largest CSV and copy it.
    candidates = sorted(Path(path).rglob("*.csv"), key=lambda p: p.stat().st_size, reverse=True)
    if not candidates:
        print("[kaggle] no CSV found in the downloaded bundle.")
        return False

    ensure_dirs()
    shutil.copy(candidates[0], ORDERS_CSV)
    print(f"[kaggle] copied {candidates[0].name} -> {ORDERS_CSV} "
          f"({ORDERS_CSV.stat().st_size / 1e6:.1f} MB)")
    return True


def manual_instructions() -> None:
    """Print fallback instructions for a manual download."""
    print("-" * 60)
    print("Manual download steps:")
    print(f"  1. Open:  {KAGGLE_URL}")
    print("  2. Click 'Download' (you need a free Kaggle account).")
    print("  3. Unzip the archive - it contains a file named 'data.csv'.")
    print(f"  4. Rename / move that file to:  {ORDERS_CSV}")
    print("-" * 60)


def main() -> int:
    ensure_dirs()
    if ORDERS_CSV.exists() and ORDERS_CSV.stat().st_size > 1_000_000:
        print(f"[kaggle] {ORDERS_CSV} already present "
              f"({ORDERS_CSV.stat().st_size / 1e6:.1f} MB) - nothing to do.")
        return 0
    if download_via_kagglehub():
        return 0
    manual_instructions()
    print("\nAfter downloading, re-run the mock-data generator:")
    print("    python scripts/generate_mock_data.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
