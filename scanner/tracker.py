import os
import sqlite3
from datetime import datetime


DB_PATH = os.environ.get("COIN_DB_PATH", "scanner.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            market_cap_m REAL,
            drop_pct REAL NOT NULL,
            volume_ratio REAL NOT NULL,
            window_days INTEGER NOT NULL,
            score REAL NOT NULL,
            mode TEXT NOT NULL DEFAULT 'accumulation',
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            price REAL,
            amount REAL NOT NULL,
            leverage INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL DEFAULT 'open',
            related_order_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry_price REAL NOT NULL,
            size REAL NOT NULL,
            leverage INTEGER NOT NULL,
            score REAL NOT NULL,
            tp_order_id TEXT,
            sl_order_id TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            opened_at TEXT NOT NULL,
            closed_at TEXT
        )
    """)
    conn.commit()

    # 迁移：positions 表新增列（兼容已有数据库）
    existing = {row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
    migrations = [
        ("exit_price", "REAL"),
        ("pnl", "REAL"),
        ("pnl_pct", "REAL"),
        ("exit_reason", "TEXT"),
        ("mode", "TEXT DEFAULT ''"),
    ]
    for col_name, col_type in migrations:
        if col_name not in existing:
            conn.execute(f"ALTER TABLE positions ADD COLUMN {col_name} {col_type}")
    conn.commit()

    # 迁移：scan_results 表新增信号列
    sr_existing = {row[1] for row in conn.execute("PRAGMA table_info(scan_results)").fetchall()}
    sr_migrations = [
        ("entry_price",       "REAL"),
        ("stop_loss_price",   "REAL"),
        ("take_profit_price", "REAL"),
        ("signal_type",       "TEXT DEFAULT ''"),
        ("score_breakdown",   "TEXT DEFAULT ''"),
        ("lifecycle_state",   "TEXT DEFAULT 'detected'"),
        ("entered_at",        "TEXT"),
        ("closed_at",         "TEXT"),
        ("current_price",     "REAL"),
        ("unrealized_pnl_pct","REAL"),
        ("price_updated_at",  "TEXT"),
    ]
    for col_name, col_type in sr_migrations:
        if col_name not in sr_existing:
            conn.execute(f"ALTER TABLE scan_results ADD COLUMN {col_name} {col_type}")
    conn.commit()

    return conn


def save_scan(signals: list, mode: str = "accumulation") -> int:
    """保存一次扫描结果（TradeSignal 列表），返回 scan_id。"""
    import json as _json
    conn = _get_conn()
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute("INSERT INTO scans (scan_time) VALUES (?)", (ts,))
        scan_id = cur.lastrowid
        for s in signals:
            breakdown_json = ""
            if hasattr(s, "score_breakdown") and s.score_breakdown:
                breakdown_json = _json.dumps(s.score_breakdown, ensure_ascii=False)
            conn.execute(
                "INSERT INTO scan_results "
                "(scan_id, symbol, price, market_cap_m, drop_pct, volume_ratio, window_days, score, mode, "
                "entry_price, stop_loss_price, take_profit_price, signal_type, score_breakdown) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (scan_id, s.symbol, s.price, s.market_cap_m,
                 s.drop_pct, s.volume_ratio, s.window_days, s.score, mode,
                 s.entry_price, s.stop_loss_price, s.take_profit_price,
                 s.signal_type, breakdown_json),
            )
        conn.commit()
        return scan_id
    finally:
        conn.close()


def get_history(symbol: str, limit: int = 10) -> list[dict]:
    """查询某币种的历史扫描记录"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT s.scan_time, r.price, r.drop_pct, r.volume_ratio, r.window_days, r.score
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        WHERE r.symbol = ?
        ORDER BY s.scan_time DESC LIMIT ?
    """, (symbol, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query_scan_results(
    symbol: str | None = None,
    mode: str | None = None,
    scan_time_from: str | None = None,
    scan_time_to: str | None = None,
    page: int = 1,
    per_page: int = 50,
    max_per_page: int = 200,
) -> tuple[list[dict], int]:
    """分页查询扫描历史（只读）。空字符串视为未设置筛选条件。"""
    def _norm(s: str | None) -> str | None:
        if s is None:
            return None
        t = s.strip()
        return t if t else None

    symbol = _norm(symbol)
    mode = _norm(mode)
    scan_time_from = _norm(scan_time_from)
    scan_time_to = _norm(scan_time_to)

    per_page = min(max(1, per_page), max_per_page)
    page = max(1, page)
    offset = (page - 1) * per_page

    conditions: list[str] = []
    params: list = []
    if symbol is not None:
        conditions.append("r.symbol = ?")
        params.append(symbol)
    if mode is not None:
        conditions.append("r.mode = ?")
        params.append(mode)
    if scan_time_from is not None:
        conditions.append("s.scan_time >= ?")
        params.append(scan_time_from)
    if scan_time_to is not None:
        conditions.append("s.scan_time <= ?")
        params.append(scan_time_to)

    where_sql = (" WHERE " + " AND ".join(conditions)) if conditions else ""

    conn = _get_conn()
    count_row = conn.execute(
        f"SELECT COUNT(*) FROM scan_results r JOIN scans s ON r.scan_id = s.id{where_sql}",
        params,
    ).fetchone()
    total = int(count_row[0])

    rows = conn.execute(
        f"""
        SELECT s.scan_time, r.symbol, r.price, r.market_cap_m, r.drop_pct,
               r.volume_ratio, r.window_days, r.score, r.mode,
               r.entry_price, r.stop_loss_price, r.take_profit_price, r.signal_type,
               r.score_breakdown
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        {where_sql}
        ORDER BY s.scan_time DESC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()
    conn.close()
    import json as _json
    results = []
    for r in rows:
        d = dict(r)
        raw = d.get("score_breakdown", "")
        if raw and isinstance(raw, str):
            try:
                d["score_breakdown"] = _json.loads(raw)
            except (ValueError, TypeError):
                d["score_breakdown"] = None
        else:
            d["score_breakdown"] = None
        results.append(d)
    return results, total


def save_order(
    order_id: str,
    symbol: str,
    side: str,
    order_type: str,
    price: float | None,
    amount: float,
    leverage: int = 1,
    related_order_id: str | None = None,
) -> int:
    """保存一条订单记录，返回本地 id。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO orders (order_id, symbol, side, order_type, price, amount, leverage, status, related_order_id, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)",
        (order_id, symbol, side, order_type, price, amount, leverage, related_order_id, now, now),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def update_order_status(order_id: str, status: str) -> None:
    """更新订单状态。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?",
        (status, now, order_id),
    )
    conn.commit()
    conn.close()


def get_open_orders(order_type: str | None = None) -> list[dict]:
    """获取所有 status='open' 的订单。可按 order_type 过滤。"""
    conn = _get_conn()
    if order_type:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status = 'open' AND order_type = ? ORDER BY created_at",
            (order_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM orders WHERE status = 'open' ORDER BY created_at",
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_position(
    symbol: str,
    side: str,
    entry_price: float,
    size: float,
    leverage: int,
    score: float,
    tp_order_id: str | None = None,
    sl_order_id: str | None = None,
    mode: str = "",
) -> int:
    """保存一条持仓记录，返回本地 id。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute(
        "INSERT INTO positions (symbol, side, entry_price, size, leverage, score, tp_order_id, sl_order_id, status, opened_at, mode) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)",
        (symbol, side, entry_price, size, leverage, score, tp_order_id, sl_order_id, now, mode),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def close_position(
    symbol: str,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_pct: float | None = None,
    exit_reason: str | None = None,
) -> None:
    """关闭某币种的持仓。"""
    conn = _get_conn()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE positions SET status = 'closed', closed_at = ?, "
        "exit_price = ?, pnl = ?, pnl_pct = ?, exit_reason = ? "
        "WHERE symbol = ? AND status = 'open'",
        (now, exit_price, pnl, pnl_pct, exit_reason, symbol),
    )
    conn.commit()
    conn.close()


def get_open_positions() -> list[dict]:
    """获取所有 status='open' 的持仓。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status = 'open' ORDER BY opened_at",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_order_by_id(order_id: str) -> dict | None:
    """按 order_id 查询单条订单。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_id = ?", (order_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_closed_trades() -> list[dict]:
    """获取所有已关闭且有盈亏记录的持仓。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status = 'closed' AND pnl_pct IS NOT NULL "
        "ORDER BY closed_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_closed_trades_by_symbol(symbol: str) -> list[dict]:
    """获取指定币种所有已关闭且有盈亏记录的持仓。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM positions WHERE status = 'closed' AND pnl_pct IS NOT NULL "
        "AND symbol = ? ORDER BY closed_at DESC",
        (symbol,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracked_symbols() -> list[dict]:
    """获取所有被跟踪的币种及其出现次数、最新价格和最新得分"""
    conn = _get_conn()
    rows = conn.execute("""
        WITH ranked AS (
            SELECT
                r.symbol,
                r.price,
                r.score,
                s.scan_time,
                ROW_NUMBER() OVER (PARTITION BY r.symbol ORDER BY s.scan_time DESC) AS rn_last,
                ROW_NUMBER() OVER (PARTITION BY r.symbol ORDER BY s.scan_time ASC) AS rn_first
            FROM scan_results r
            JOIN scans s ON r.scan_id = s.id
        )
        SELECT
            symbol,
            COUNT(*) AS times,
            MAX(scan_time) AS last_seen,
            MAX(CASE WHEN rn_last = 1 THEN price END) AS last_price,
            MAX(CASE WHEN rn_first = 1 THEN price END) AS first_price,
            MAX(CASE WHEN rn_last = 1 THEN score END) AS last_score
        FROM ranked
        GROUP BY symbol
        ORDER BY times DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_scans(mode: str) -> list[dict]:
    """查询今天该模式最新一次扫描（scan_id 最大）的信号列表。"""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = _get_conn()
    try:
        row = conn.execute(
            """
            SELECT MAX(s.id) AS max_scan_id
            FROM scans s
            JOIN scan_results r ON r.scan_id = s.id
            WHERE r.mode = ? AND s.scan_time >= ?
            """,
            (mode, today + " 00:00:00"),
        ).fetchone()
        max_scan_id = row["max_scan_id"] if row else None
        if max_scan_id is None:
            return []
        rows = conn.execute(
            """
            SELECT r.symbol, r.price, r.score, r.entry_price,
                   r.stop_loss_price, r.take_profit_price, r.signal_type, r.mode
            FROM scan_results r
            WHERE r.scan_id = ?
            ORDER BY r.score DESC
            """,
            (max_scan_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_signals() -> list[dict]:
    """获取 lifecycle_state in ('detected', 'entered') 的活跃信号。"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT r.id, r.symbol, r.price, r.score, r.mode, r.signal_type,
               r.entry_price, r.stop_loss_price, r.take_profit_price,
               r.lifecycle_state, r.current_price, r.unrealized_pnl_pct,
               r.price_updated_at, r.entered_at, r.score_breakdown,
               s.scan_time
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        WHERE r.lifecycle_state IN ('detected', 'entered')
        ORDER BY s.scan_time DESC
    """).fetchall()
    conn.close()
    import json as _json
    results = []
    for r in rows:
        d = dict(r)
        raw = d.get("score_breakdown", "")
        if raw and isinstance(raw, str):
            try:
                d["score_breakdown"] = _json.loads(raw)
            except (ValueError, TypeError):
                d["score_breakdown"] = None
        else:
            d["score_breakdown"] = None
        results.append(d)
    return results


def update_signal_lifecycle(result_id: int, state: str, **kwargs) -> None:
    """更新信号生命周期状态。kwargs 可含 entered_at, closed_at, current_price, unrealized_pnl_pct 等。"""
    conn = _get_conn()
    sets = ["lifecycle_state = ?"]
    params: list = [state]
    for col in ("entered_at", "closed_at", "current_price", "unrealized_pnl_pct", "price_updated_at"):
        if col in kwargs:
            sets.append(f"{col} = ?")
            params.append(kwargs[col])
    params.append(result_id)
    conn.execute(f"UPDATE scan_results SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def get_signal_outcomes(days: int = 30) -> dict:
    """近 N 天信号结果分布统计。"""
    conn = _get_conn()
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT r.lifecycle_state, COUNT(*) as cnt
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        WHERE s.scan_time >= ?
        GROUP BY r.lifecycle_state
    """, (cutoff,)).fetchall()
    conn.close()
    return {r["lifecycle_state"]: r["cnt"] for r in rows}


def get_signal_count_trend(days: int = 7) -> list[dict]:
    """近 N 天每天各模式信号数量趋势。"""
    conn = _get_conn()
    cutoff = (datetime.now() - __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT DATE(s.scan_time) as day, r.mode, COUNT(*) as cnt
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        WHERE s.scan_time >= ?
        GROUP BY DATE(s.scan_time), r.mode
        ORDER BY day
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
