"""
pipeline.py
===========
End-to-end orchestration for the e-commerce ETL pipeline.

Run from the project root:
    python -m etl.pipeline
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import get_postgres_url, get_sqlite_url, ensure_dirs
from etl.extract import extract_all
from etl.load import load_to_postgres, load_to_sqlite
from etl.logger import ETLRunLogger, get_logger
from etl.transform import transform_all

console = Console()
log = get_logger("pipeline")


def _row_count(data: dict[str, Any]) -> int:
    """Return total rows across DataFrame values in a dictionary."""
    return sum(len(v) for v in data.values() if isinstance(v, pd.DataFrame))


def _quality_issue_count(quality_report: dict[str, Any]) -> int:
    """Count non-zero rejection categories in the quality report."""
    rejections = quality_report.get("orders", {}).get("rejections", {})
    return sum(1 for value in rejections.values() if int(value or 0) > 0)


def _print_stage_result(stage: str, message: str, seconds: float) -> None:
    """Print one Rich-formatted stage completion line."""
    console.print(
        f"[bold green]OK[/bold green] [bold]{stage}[/bold] complete: "
        f"{message} in {seconds:.2f}s"
    )


def _print_summary(summary: dict[str, Any]) -> None:
    """Render the final ETL summary table."""
    table = Table(title="ETL Pipeline Summary", show_header=True, header_style="bold cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")
    for label, key in (
        ("Rows extracted", "rows_extracted"),
        ("Clean order rows", "clean_order_rows"),
        ("Rows rejected", "rows_rejected"),
        ("Rows loaded", "rows_loaded"),
    ):
        table.add_row(label, f"{summary[key]:,}")
    table.add_row("Quality score", f"{summary['quality_score']:.2f}%")
    table.add_row("SQLite status", summary["sqlite_status"])
    table.add_row("PostgreSQL status", summary["postgres_status"])
    table.add_row("Duration", f"{summary['duration_seconds']:.2f}s")
    console.print(table)


def run_full_pipeline(load_postgres: bool = True) -> dict[str, Any]:
    """Run extract, transform, SQLite load and optional PostgreSQL load.

    Parameters
    ----------
    load_postgres : bool
        Attempt a PostgreSQL load when PG_* credentials are configured.
        SQLite always runs because the Streamlit app depends on it.

    Returns
    -------
    dict[str, Any]
        Execution summary with row counts, quality score and load status.
    """
    ensure_dirs()
    started = time.perf_counter()
    sqlite_url = get_sqlite_url()

    console.print(Panel.fit(
        "[bold]E-Commerce Data Pipeline[/bold]\nExtract -> Transform -> Load",
        border_style="cyan",
    ))

    with ETLRunLogger(sqlite_url, stage="full_pipeline") as run_logger:
        try:
            t0 = time.perf_counter()
            raw = extract_all()
            rows_extracted = _row_count(raw)
            run_logger.add_extracted(rows_extracted)
            _print_stage_result("Extract", f"{rows_extracted:,} rows", time.perf_counter() - t0)

            t0 = time.perf_counter()
            clean = transform_all(raw, write_csv=True)
            quality_report = clean["quality_report"]
            orders_report = quality_report.get("orders", {})
            rows_rejected = int(orders_report.get("total_rejected", 0))
            quality_score = float(orders_report.get("quality_score", 0.0))
            run_logger.add_rejected(rows_rejected)
            issue_count = _quality_issue_count(quality_report)
            _print_stage_result(
                "Transform",
                f"{len(clean['orders']):,} clean order rows, {rows_rejected:,} rejected",
                time.perf_counter() - t0,
            )
            console.print(
                f"[bold yellow]Quality Score:[/bold yellow] "
                f"{quality_score:.2f}% - {issue_count} issue categories flagged"
            )

            t0 = time.perf_counter()
            sqlite_summary = load_to_sqlite(
                clean["orders"], clean["products"], clean["customers"], clean["returns"],
                run_logger=run_logger,
            )
            sqlite_rows = sum(sqlite_summary.get("tables", {}).values())
            _print_stage_result("SQLite load", f"{sqlite_rows:,} warehouse rows", time.perf_counter() - t0)

            postgres_summary = None
            postgres_status = "Skipped (PG_* not configured)"
            if load_postgres and get_postgres_url():
                t0 = time.perf_counter()
                postgres_summary = load_to_postgres(
                    clean["orders"], clean["products"], clean["customers"], clean["returns"],
                    run_logger=run_logger,
                )
                if postgres_summary:
                    postgres_rows = sum(postgres_summary.get("tables", {}).values())
                    postgres_status = f"Loaded {postgres_rows:,} rows"
                    _print_stage_result("PostgreSQL load", postgres_status, time.perf_counter() - t0)
                else:
                    postgres_status = "Failed or unavailable"

            summary = {
                "rows_extracted": rows_extracted,
                "clean_order_rows": int(len(clean["orders"])),
                "rows_rejected": rows_rejected,
                "rows_loaded": sqlite_rows,
                "quality_score": quality_score,
                "sqlite_status": f"Loaded {sqlite_rows:,} rows",
                "postgres_status": postgres_status,
                "sqlite_summary": sqlite_summary,
                "postgres_summary": postgres_summary,
                "duration_seconds": round(time.perf_counter() - started, 2),
            }
            run_logger.note(f"Quality score {quality_score:.2f}%")
            run_logger.note(f"SQLite {summary['sqlite_status']}")
            run_logger.note(f"PostgreSQL {postgres_status}")
            _print_summary(summary)
            return summary
        except Exception as exc:
            run_logger.note(str(exc))
            log.exception("Pipeline failed")
            console.print(f"[bold red]Pipeline failed:[/bold red] {exc}")
            raise


def main() -> None:
    """CLI entry point for direct pipeline execution."""
    run_full_pipeline(load_postgres=True)


if __name__ == "__main__":
    main()
