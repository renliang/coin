"""SQLite persistence for sentiment data."""
import os
import sqlite3
from datetime import datetime

from sentiment.models import SentimentItem, SentimentSignal

_DEFAULT_DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or os.environ.get("COIN_DB_PATH", _DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            symbol TEXT NOT NULL,
            score REAL NOT NULL,
            confidence REAL NOT NULL,
            raw_text TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            score REAL NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_items(items: list[SentimentItem], db_path: str | None = None) -> None:
    """Bulk insert a list of SentimentItem records."""
    if not items:
        return
    conn = _get_conn(db_path)
    try:
        conn.executemany(
            "INSERT INTO sentiment_items (source, symbol, score, confidence, raw_text, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    item.source,
                    item.symbol,
                    item.score,
                    item.confidence,
                    item.raw_text,
                    item.timestamp.isoformat(),
                )
                for item in items
            ],
        )
        conn.commit()
    finally:
        conn.close()


def query_items(
    symbol: str | None = None,
    source: str | None = None,
    limit: int = 100,
    db_path: str | None = None,
) -> list[SentimentItem]:
    """Query sentiment items with optional filters."""
    conn = _get_conn(db_path)
    try:
        conditions: list[str] = []
        params: list = []
        if symbol is not None:
            conditions.append("symbol = ?")
            params.append(symbol)
        if source is not None:
            conditions.append("source = ?")
            params.append(source)

        where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(
            f"SELECT source, symbol, score, confidence, raw_text, timestamp "
            f"FROM sentiment_items{where_sql} "
            f"ORDER BY id DESC LIMIT ?",
            params + [limit],
        ).fetchall()

        return [
            SentimentItem(
                source=row["source"],
                symbol=row["symbol"],
                score=row["score"],
                confidence=row["confidence"],
                raw_text=row["raw_text"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]
    finally:
        conn.close()


def save_signal(signal: SentimentSignal, db_path: str | None = None) -> None:
    """Insert a SentimentSignal record."""
    conn = _get_conn(db_path)
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO sentiment_signals (symbol, score, direction, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (signal.symbol, signal.score, signal.direction, signal.confidence, now),
        )
        conn.commit()
    finally:
        conn.close()


def query_latest_signal(symbol: str, db_path: str | None = None) -> SentimentSignal | None:
    """Return the most recently inserted signal for the given symbol, or None."""
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT symbol, score, direction, confidence "
            "FROM sentiment_signals WHERE symbol = ? "
            "ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        if row is None:
            return None
        return SentimentSignal(
            symbol=row["symbol"],
            score=row["score"],
            direction=row["direction"],
            confidence=row["confidence"],
        )
    finally:
        conn.close()
