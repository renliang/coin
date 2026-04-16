"""Sentiment endpoints — 3 routes migrated from history_ui/api.py."""

from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/sentiment/latest")
def sentiment_latest() -> dict:
    """每个 symbol 的最新情绪信号。"""
    from sentiment.store import _get_conn

    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT s1.* FROM sentiment_signals s1
            INNER JOIN (
                SELECT symbol, MAX(id) as max_id
                FROM sentiment_signals GROUP BY symbol
            ) s2
            ON s1.id = s2.max_id ORDER BY s1.created_at DESC
            """
        ).fetchall()
        return {"signals": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/sentiment/history")
def sentiment_history(
    symbol: str = Query(""),
    days: int = Query(7),
) -> dict:
    """指定 symbol 的每日平均情绪分数历史。"""
    from sentiment.store import _get_conn

    conn = _get_conn()
    try:
        rows = conn.execute(
            """
            SELECT date(created_at) as date, AVG(score) as score,
                   CASE WHEN AVG(score) > 0.1 THEN 'bullish'
                        WHEN AVG(score) < -0.1 THEN 'bearish'
                        ELSE 'neutral' END as direction
            FROM sentiment_signals
            WHERE (? = '' OR symbol = ?)
              AND created_at >= date('now', ? || ' days')
            GROUP BY date(created_at) ORDER BY date ASC
            """,
            (symbol, symbol, f"-{days}"),
        ).fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        conn.close()


@router.get("/sentiment/items")
def sentiment_items(
    source: str = Query(""),
    symbol: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(20),
) -> dict:
    """分页查询原始情绪条目。"""
    offset = (page - 1) * per_page
    from sentiment.store import _get_conn

    conn = _get_conn()
    try:
        clauses: list[str] = []
        params: list = []
        if source:
            clauses.append("source = ?")
            params.append(source)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM sentiment_items {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM sentiment_items {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
        return {
            "items": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "per_page": per_page,
        }
    finally:
        conn.close()
