"""
logger.py
=========
Persistent run-logging for the ETL pipeline.

Every pipeline execution is recorded in the ``etl_run_log`` table so
the Streamlit app (Tab 2 - ETL Pipeline) can show:

    Run ID | Timestamp | Rows Extracted | Rows Loaded |
    Rejected | Duration | Status | Notes

This module deliberately keeps dependencies minimal (only stdlib +
SQLAlchemy) so it can be imported from anywhere in the project.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Make ``config`` importable regardless of where this module is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

try:
    from config import QUALITY_REPORT_PATH, REPORTS_DIR
except Exception:  # pragma: no cover - fallback for unusual invocations
    QUALITY_REPORT_PATH = Path("quality_report.json")
    REPORTS_DIR = Path("reports")

# ------------------------------------------------------------------
# Standard logging
# ------------------------------------------------------------------
_LOGGER_NAME = "ecommerce_etl"
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s",
                      datefmt="%H:%M:%S")
)
logger = logging.getLogger(_LOGGER_NAME)
logger.setLevel(logging.INFO)
if not logger.handlers:
    logger.addHandler(_console_handler)
logger.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the project's root logger."""
    return logger if name is None else logger.getChild(name)


# ------------------------------------------------------------------
# Run context manager - tracks one full ETL execution
# ------------------------------------------------------------------
class ETLRunLogger:
    """Context manager that times an ETL run and persists its summary.

    Example
    -------
    >>> with ETLRunLogger(db_url) as run:
    ...     run.add_extracted(541909)
    ...     run.add_loaded(532618)
    ...     run.add_rejected(8905)
    ...     run.note("Quality score 98.4%")
    ...     # on exit the row is written to etl_run_log

    Parameters
    ----------
    db_url : str | None
        SQLAlchemy URL. If None, the run is only written to a JSON file
        (used during tests / when no DB is available yet).
    stage : str
        Free-text stage label ('full_pipeline', 'extract_only', ...).
    """

    def __init__(self, db_url: str | None = None, stage: str = "full_pipeline") -> None:
        self.db_url = db_url
        self.stage = stage
        self.start_ts: datetime | None = None
        self.start_perf: float = 0.0
        self.rows_extracted = 0
        self.rows_loaded = 0
        self.rows_rejected = 0
        self.status = "RUNNING"
        self.notes: list[str] = []

    # -- accumulator helpers ---------------------------------------
    def add_extracted(self, n: int) -> None:
        self.rows_extracted += int(n)

    def add_loaded(self, n: int) -> None:
        self.rows_loaded += int(n)

    def add_rejected(self, n: int) -> None:
        self.rows_rejected += int(n)

    def note(self, message: str) -> None:
        self.notes.append(message)

    # -- context manager protocol ----------------------------------
    def __enter__(self) -> "ETLRunLogger":
        self.start_ts = datetime.now()
        self.start_perf = time.perf_counter()
        logger.info("ETL run started | stage=%s", self.stage)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration = round(time.perf_counter() - self.start_perf, 2)
        if exc_type is None:
            self.status = "SUCCESS"
        else:
            self.status = "FAILED"
            self.note(f"{exc_type.__name__}: {exc}")
        logger.info("ETL run finished | status=%s | duration=%.2fs",
                    self.status, duration)
        self._persist(duration)

    # -- persistence -----------------------------------------------
    def _persist(self, duration: float) -> None:
        """Insert a row into etl_run_log (if DB reachable) + dump JSON."""
        record = {
            "run_timestamp": self.start_ts.isoformat(timespec="seconds")
                if self.start_ts else datetime.now().isoformat(timespec="seconds"),
            "stage":         self.stage,
            "rows_extracted": self.rows_extracted,
            "rows_loaded":    self.rows_loaded,
            "rows_rejected":  self.rows_rejected,
            "status":         self.status,
            "duration_seconds": duration,
            "notes":          " | ".join(self.notes),
        }

        # 1) Try to persist into the DB ---------------------------------
        if self.db_url:
            try:
                from sqlalchemy import create_engine, text
                engine = create_engine(self.db_url)
                with engine.begin() as conn:
                    # Portable create-if-not-exists (works on SQLite + PG)
                    conn.execute(text(
                        """
                        CREATE TABLE IF NOT EXISTS etl_run_log (
                            run_id            INTEGER PRIMARY KEY,
                            run_timestamp     TIMESTAMP NOT NULL,
                            stage             TEXT,
                            rows_extracted    INTEGER,
                            rows_loaded       INTEGER,
                            rows_rejected     INTEGER,
                            status            TEXT,
                            duration_seconds  REAL,
                            notes             TEXT
                        )
                        """
                    ))
                    # Compute next run_id explicitly so the same DDL works
                    # on both SQLite and PostgreSQL (no SERIAL dependency).
                    res = conn.execute(text("SELECT COALESCE(MAX(run_id), 0) + 1 FROM etl_run_log"))
                    next_id = int(res.scalar() or 1)
                    conn.execute(text(
                        """
                        INSERT INTO etl_run_log
                            (run_id, run_timestamp, stage, rows_extracted, rows_loaded,
                             rows_rejected, status, duration_seconds, notes)
                        VALUES
                            (:id, :ts, :stage, :ex, :ld, :rj, :status, :dur, :notes)
                        """
                    ), {
                        "id":    next_id,
                        "ts":    record["run_timestamp"],
                        "stage": record["stage"],
                        "ex":    record["rows_extracted"],
                        "ld":    record["rows_loaded"],
                        "rj":    record["rows_rejected"],
                        "status": record["status"],
                        "dur":   record["duration_seconds"],
                        "notes": record["notes"],
                    })
                engine.dispose()
            except Exception as exc:  # pragma: no cover
                logger.warning("Could not write etl_run_log to DB: %s", exc)

        # 2) Always mirror to JSON for the Streamlit app / debugging -----
        try:
            QUALITY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            history: list[dict[str, Any]] = []
            if QUALITY_REPORT_PATH.exists():
                try:
                    history = json.loads(QUALITY_REPORT_PATH.read_text())
                    if not isinstance(history, list):
                        history = []
                except Exception:
                    history = []
            history.append(record)
            QUALITY_REPORT_PATH.write_text(json.dumps(history, indent=2, default=str))
        except Exception as exc:  # pragma: no cover
            logger.warning("Could not write quality_report.json: %s", exc)


def write_quality_report(report: dict) -> Path:
    """Persist a structured data-quality report to JSON.

    Parameters
    ----------
    report : dict
        Anything transform.py wishes to surface (per-rule rejection
        counts, sample bad rows, overall quality score ...).
    """
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        out = REPORTS_DIR / "quality_report_detail.json"
        out.write_text(json.dumps(report, indent=2, default=str))
        logger.info("Quality report written -> %s", out)
        return out
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not write detailed quality report: %s", exc)
        return Path()
