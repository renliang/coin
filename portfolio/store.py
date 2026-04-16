"""SQLite persistence for portfolio data."""
import os
import sqlite3
from datetime import date

_DEFAULT_DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("COIN_DB_PATH", _DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_nav (
            date TEXT PRIMARY KEY,
            nav REAL NOT NULL,
            hwm REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            weight REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            level TEXT NOT NULL,
            strategy_id TEXT,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_nav(d: date, nav: float, hwm: float, db_path: str | None = None) -> None:
    """Insert or replace NAV record for a given date."""
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_nav (date, nav, hwm) VALUES (?, ?, ?)",
            (d.isoformat(), nav, hwm),
        )
        conn.commit()
    finally:
        conn.close()


def query_nav_history(limit: int = 90, db_path: str | None = None) -> list[dict]:
    """Return NAV history ordered by date DESC."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT date, nav, hwm FROM portfolio_nav ORDER BY date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def save_weights(
    d: date, weights: dict[str, float], db_path: str | None = None
) -> None:
    """Delete existing weights for a date and insert new ones."""
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "DELETE FROM strategy_weights WHERE date = ?", (d.isoformat(),)
        )
        conn.executemany(
            "INSERT INTO strategy_weights (date, strategy_id, weight) VALUES (?, ?, ?)",
            [(d.isoformat(), sid, w) for sid, w in weights.items()],
        )
        conn.commit()
    finally:
        conn.close()


def query_latest_weights(db_path: str | None = None) -> dict[str, float]:
    """Return the most recently saved strategy weights."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT date FROM strategy_weights ORDER BY date DESC, id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return {}
        latest_date = row["date"]
        rows = conn.execute(
            "SELECT strategy_id, weight FROM strategy_weights WHERE date = ?",
            (latest_date,),
        ).fetchall()
        return {r["strategy_id"]: r["weight"] for r in rows}
    finally:
        conn.close()


def save_risk_event(
    level: str,
    strategy_id: str | None,
    event_type: str,
    details: str,
    db_path: str | None = None,
) -> None:
    """Insert a risk event record."""
    from datetime import datetime

    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT INTO risk_events (created_at, level, strategy_id, event_type, details) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.now().isoformat(), level, strategy_id, event_type, details),
        )
        conn.commit()
    finally:
        conn.close()


def query_risk_events(limit: int = 50, db_path: str | None = None) -> list[dict]:
    """Return risk events ordered by id DESC (most recent first)."""
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT created_at, level, strategy_id, event_type, details "
            "FROM risk_events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
