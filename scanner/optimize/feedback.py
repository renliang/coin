"""feedback.py — signal_outcomes table creation, recording, and return backfill."""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timezone
from typing import Optional

_DEFAULT_DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")

_VALID_PERIODS = {"return_3d", "return_7d", "return_14d", "return_30d"}

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_result_id INTEGER,
    symbol TEXT NOT NULL,
    signal_date TEXT NOT NULL,
    signal_price REAL NOT NULL,
    return_3d REAL,
    return_7d REAL,
    return_14d REAL,
    return_30d REAL,
    features_json TEXT,
    btc_price REAL,
    collected_at TEXT,
    UNIQUE(scan_result_id, symbol, signal_date)
)
"""


def ensure_outcomes_table(db_path: str = _DEFAULT_DB_PATH) -> None:
    """Create signal_outcomes table if it does not already exist."""
    with sqlite3.connect(db_path) as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def record_signal_outcome(
    db_path: str,
    scan_result_id: Optional[int],
    symbol: str,
    signal_date: str,
    signal_price: float,
    features_json: Optional[str],
    btc_price: Optional[float],
) -> Optional[int]:
    """Insert a new signal outcome row.

    Uses INSERT OR IGNORE so duplicate (scan_result_id, symbol, signal_date)
    combinations are silently skipped.

    Returns:
        The new row id on success, or None if the row already existed.
    """
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO signal_outcomes
                (scan_result_id, symbol, signal_date, signal_price,
                 features_json, btc_price)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (scan_result_id, symbol, signal_date, signal_price, features_json, btc_price),
        )
        conn.commit()
        if cur.lastrowid and cur.rowcount == 1:
            return cur.lastrowid
    return None


def get_pending_outcomes(
    db_path: str, as_of_date: Optional[str] = None
) -> list[dict]:
    """Return rows where return_3d IS NULL and signal_date + 3 days <= as_of_date.

    Args:
        db_path: Path to the SQLite database.
        as_of_date: ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        List of row dicts for pending outcome records.
    """
    if as_of_date is None:
        as_of_date = date.today().isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT * FROM signal_outcomes
            WHERE return_3d IS NULL
              AND date(signal_date, '+3 days') <= date(?)
            """,
            (as_of_date,),
        ).fetchall()
    return [dict(r) for r in rows]


def backfill_return(
    db_path: str,
    outcome_id: int,
    period: str,
    value: float,
) -> None:
    """Update a single return column for the given outcome row.

    Args:
        db_path: Path to the SQLite database.
        outcome_id: Primary key of the signal_outcomes row to update.
        period: One of 'return_3d', 'return_7d', 'return_14d', 'return_30d'.
        value: The return value to store.

    Raises:
        ValueError: If period is not a valid column name.
    """
    if period not in _VALID_PERIODS:
        raise ValueError(
            f"Invalid period '{period}'. Must be one of {sorted(_VALID_PERIODS)}."
        )

    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"UPDATE signal_outcomes SET {period} = ?, collected_at = ? WHERE id = ?",
            (value, collected_at, outcome_id),
        )
        conn.commit()


def get_labeled_outcomes(db_path: str) -> list[dict]:
    """Return all rows where return_7d IS NOT NULL.

    Args:
        db_path: Path to the SQLite database.

    Returns:
        List of row dicts for labeled outcome records.
    """
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM signal_outcomes WHERE return_7d IS NOT NULL"
        ).fetchall()
    return [dict(r) for r in rows]
