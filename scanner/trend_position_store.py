"""趋势跟踪持仓状态 SQLite DAO。

每个持仓一行, 多层金字塔通过 entries_json 存储。
独立于现有 scanner/tracker.py 的 positions 表 (那是给 divergence 用的)。
"""
from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field


DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")


@dataclass(frozen=True)
class Entry:
    date: str      # ISO YYYY-MM-DD
    price: float
    units: float


@dataclass(frozen=True)
class TrendPosition:
    id: int
    symbol: str
    entries: list[Entry]
    trailing_high: float
    atr_at_open: float
    opened_at: str
    status: str                        # 'open' | 'closed'
    closed_at: str | None = None
    close_price: float | None = None
    close_reason: str | None = None
    realized_pnl_pct: float | None = None

    @property
    def total_units(self) -> float:
        return sum(e.units for e in self.entries)

    @property
    def total_cost(self) -> float:
        return sum(e.price * e.units for e in self.entries)

    @property
    def avg_price(self) -> float:
        tu = self.total_units
        return self.total_cost / tu if tu > 0 else 0.0

    @property
    def levels(self) -> int:
        return len(self.entries)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_schema() -> None:
    """创建表 (幂等)。"""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trend_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entries_json TEXT NOT NULL,
                trailing_high REAL NOT NULL,
                atr_at_open REAL NOT NULL,
                opened_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                closed_at TEXT,
                close_price REAL,
                close_reason TEXT,
                realized_pnl_pct REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trend_positions_status ON trend_positions(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trend_positions_symbol_status ON trend_positions(symbol, status)")
        conn.commit()


def _row_to_position(row: sqlite3.Row) -> TrendPosition:
    entries_raw = json.loads(row["entries_json"])
    entries = [Entry(date=e["date"], price=e["price"], units=e["units"]) for e in entries_raw]
    return TrendPosition(
        id=row["id"],
        symbol=row["symbol"],
        entries=entries,
        trailing_high=row["trailing_high"],
        atr_at_open=row["atr_at_open"],
        opened_at=row["opened_at"],
        status=row["status"],
        closed_at=row["closed_at"],
        close_price=row["close_price"],
        close_reason=row["close_reason"],
        realized_pnl_pct=row["realized_pnl_pct"],
    )


def open_position(
    symbol: str,
    entry_price: float,
    units: float,
    atr_at_open: float,
    opened_at: str,
) -> TrendPosition:
    """开新仓。若该 symbol 已有 open 状态持仓则抛 ValueError (必须先 close)。"""
    init_schema()
    if get_position(symbol) is not None:
        existing = get_position(symbol)
        if existing and existing.status == "open":
            raise ValueError(f"{symbol} 已有未关闭的趋势持仓 (id={existing.id})")
    entries = [{"date": opened_at, "price": entry_price, "units": units}]
    with _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO trend_positions
                (symbol, entries_json, trailing_high, atr_at_open, opened_at, status)
            VALUES (?, ?, ?, ?, ?, 'open')
            """,
            (symbol, json.dumps(entries), entry_price, atr_at_open, opened_at),
        )
        conn.commit()
        pos_id = cur.lastrowid
    got = _get_by_id(pos_id)
    assert got is not None
    return got


def add_pyramid(symbol: str, price: float, units: float, date: str) -> TrendPosition:
    """对已 open 仓位加一层金字塔。"""
    pos = get_position(symbol)
    if pos is None or pos.status != "open":
        raise ValueError(f"{symbol} 无未关闭持仓, 无法加仓")
    new_entries = [{"date": e.date, "price": e.price, "units": e.units} for e in pos.entries]
    new_entries.append({"date": date, "price": price, "units": units})
    new_trail = max(pos.trailing_high, price)
    with _get_conn() as conn:
        conn.execute(
            "UPDATE trend_positions SET entries_json = ?, trailing_high = ? WHERE id = ?",
            (json.dumps(new_entries), new_trail, pos.id),
        )
        conn.commit()
    got = _get_by_id(pos.id)
    assert got is not None
    return got


def update_trailing_high(symbol: str, new_high: float) -> None:
    """只允许上调 trailing_high。"""
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE trend_positions
            SET trailing_high = ?
            WHERE symbol = ? AND status = 'open' AND trailing_high < ?
            """,
            (new_high, symbol, new_high),
        )
        conn.commit()


def close_position(
    symbol: str,
    close_price: float,
    reason: str,
    closed_at: str,
) -> TrendPosition:
    """平仓: 计算总 PnL%, 更新 status='closed'。"""
    pos = get_position(symbol)
    if pos is None or pos.status != "open":
        raise ValueError(f"{symbol} 无未关闭持仓, 无法平仓")
    # PnL 按总成本比例
    total_cost = pos.total_cost
    pnl = sum((close_price - e.price) * e.units for e in pos.entries)
    pnl_pct = pnl / total_cost if total_cost > 0 else 0.0
    with _get_conn() as conn:
        conn.execute(
            """
            UPDATE trend_positions
            SET status = 'closed',
                closed_at = ?,
                close_price = ?,
                close_reason = ?,
                realized_pnl_pct = ?
            WHERE id = ?
            """,
            (closed_at, close_price, reason, pnl_pct, pos.id),
        )
        conn.commit()
    got = _get_by_id(pos.id)
    assert got is not None
    return got


def get_position(symbol: str) -> TrendPosition | None:
    """返回该 symbol 最近一条记录 (含已 closed)。"""
    init_schema()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM trend_positions WHERE symbol = ? ORDER BY id DESC LIMIT 1",
            (symbol,),
        ).fetchone()
    return _row_to_position(row) if row else None


def _get_by_id(pos_id: int) -> TrendPosition | None:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM trend_positions WHERE id = ?", (pos_id,)).fetchone()
    return _row_to_position(row) if row else None


def get_open_positions() -> list[TrendPosition]:
    """返回所有 status='open' 的持仓, 按开仓时间升序。"""
    init_schema()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM trend_positions WHERE status = 'open' ORDER BY id ASC"
        ).fetchall()
    return [_row_to_position(r) for r in rows]
