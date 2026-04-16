"""Portfolio endpoints — 5 routes migrated from history_ui/api.py."""

from fastapi import APIRouter, HTTPException, Query

router = APIRouter()


@router.get("/portfolio/status")
def portfolio_status() -> dict:
    """当前策略权重 + NAV + 最大回撤。"""
    from portfolio.store import query_latest_weights, query_nav_history

    weights = query_latest_weights()
    nav_rows = query_nav_history(limit=1)
    nav = nav_rows[0]["nav"] if nav_rows else 0.0
    hwm = nav_rows[0]["hwm"] if nav_rows else 0.0
    drawdown = (hwm - nav) / hwm if hwm > 0 else 0.0
    return {
        "weights": weights,
        "nav": nav,
        "high_water_mark": hwm,
        "drawdown_pct": round(drawdown, 4),
        "portfolio_halted": drawdown > 0.05,
        "halted_strategies": [],
    }


@router.get("/portfolio/nav-history")
def portfolio_nav_history(
    days: int = Query(90),
) -> dict:
    """NAV 历史（按日期升序）。"""
    from portfolio.store import query_nav_history

    history = query_nav_history(limit=days)
    history.reverse()
    return {"history": history}


@router.get("/portfolio/weights-history")
def portfolio_weights_history() -> dict:
    """策略权重历史（按日期分组）。"""
    from portfolio.store import _get_conn

    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT date, strategy_id, weight FROM strategy_weights ORDER BY date ASC"
        ).fetchall()
        by_date: dict = {}
        for r in rows:
            d = r["date"]
            if d not in by_date:
                by_date[d] = {"date": d, "weights": {}}
            by_date[d]["weights"][r["strategy_id"]] = r["weight"]
        return {"history": list(by_date.values())}
    finally:
        conn.close()


@router.get("/portfolio/risk-events")
def portfolio_risk_events(
    limit: int = Query(20),
) -> dict:
    """风险事件列表。"""
    from portfolio.store import query_risk_events

    return {"events": query_risk_events(limit=limit)}


@router.post("/portfolio/rebalance")
def portfolio_rebalance() -> dict:
    """触发组合再平衡。"""
    try:
        from main import load_config, run_portfolio_rebalance

        _, _, _, _, _, portfolio_config = load_config()
        run_portfolio_rebalance(portfolio_config)
        from portfolio.store import query_latest_weights

        return {"success": True, "weights": query_latest_weights()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
