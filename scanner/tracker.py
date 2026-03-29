import sqlite3
from datetime import datetime


DB_PATH = "scanner.db"


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
    conn.commit()
    return conn


def save_scan(results: list[dict], mode: str = "accumulation") -> int:
    """保存一次扫描结果，返回scan_id"""
    conn = _get_conn()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("INSERT INTO scans (scan_time) VALUES (?)", (ts,))
    scan_id = cur.lastrowid
    for r in results:
        conn.execute(
            "INSERT INTO scan_results (scan_id, symbol, price, market_cap_m, drop_pct, volume_ratio, window_days, score, mode) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (scan_id, r["symbol"], r["price"], r.get("market_cap_m", 0),
             r["drop_pct"], r["volume_ratio"], r["window_days"], r["score"], mode),
        )
    conn.commit()
    conn.close()
    return scan_id


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


def get_tracked_symbols() -> list[dict]:
    """获取所有被跟踪的币种及其出现次数和最新价格"""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT r.symbol, COUNT(*) as times,
               MAX(s.scan_time) as last_seen,
               (SELECT r2.price FROM scan_results r2 JOIN scans s2 ON r2.scan_id = s2.id
                WHERE r2.symbol = r.symbol ORDER BY s2.scan_time DESC LIMIT 1) as last_price,
               (SELECT r2.price FROM scan_results r2 JOIN scans s2 ON r2.scan_id = s2.id
                WHERE r2.symbol = r.symbol ORDER BY s2.scan_time ASC LIMIT 1) as first_price
        FROM scan_results r JOIN scans s ON r.scan_id = s.id
        GROUP BY r.symbol
        ORDER BY times DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]
