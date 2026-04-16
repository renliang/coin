"""Scanner endpoints — 13 routes migrated from history_ui/api.py."""

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from scanner.stats import (
    compute_stats,
    compute_stats_by_mode,
    compute_stats_by_month,
    compute_stats_by_score_tier,
)
from scanner.tracker import (
    get_active_signals,
    get_closed_trades,
    get_closed_trades_by_symbol,
    get_open_positions,
    get_signal_count_trend,
    get_signal_outcomes,
    get_today_scans,
    query_scan_results,
)

router = APIRouter()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_latest_scan_signals() -> tuple[list[dict], str | None]:
    """获取最近一天的所有扫描信号（跨模式合并），返回 (signals, scan_time_str)。"""
    from scanner.tracker import _get_conn

    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT scan_time FROM scans ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return [], None
        last_time = row["scan_time"]
        last_day = last_time[:10]

        all_signals: list[dict] = []
        for mode in ("accumulation", "divergence", "breakout", "smc"):
            scan_row = conn.execute(
                """SELECT MAX(s.id) AS max_id FROM scans s
                   JOIN scan_results r ON r.scan_id = s.id
                   WHERE r.mode = ? AND s.scan_time >= ?""",
                (mode, last_day + " 00:00:00"),
            ).fetchone()
            max_id = scan_row["max_id"] if scan_row else None
            if max_id is None:
                continue
            rows = conn.execute(
                """SELECT r.symbol, r.price, r.score, r.entry_price,
                          r.stop_loss_price, r.take_profit_price, r.signal_type, r.mode
                   FROM scan_results r WHERE r.scan_id = ? ORDER BY r.score DESC""",
                (max_id,),
            ).fetchall()
            all_signals.extend(dict(r) for r in rows)
        return all_signals, last_time
    finally:
        conn.close()


def _compute_7d_hit_rate(closed_trades: list[dict]) -> list[dict]:
    """近7天每天各模式的胜率。"""
    today = datetime.now().date()
    result: list[dict] = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        day_trades = [
            t
            for t in closed_trades
            if (t.get("closed_at") or "")[:10] == day_str
        ]
        day_data: dict = {"date": day_str, "total": len(day_trades)}
        if day_trades:
            day_data["wins"] = sum(
                1 for t in day_trades if t.get("pnl_pct", 0) > 0
            )
            day_data["win_rate"] = round(day_data["wins"] / len(day_trades), 4)
        else:
            day_data["wins"] = 0
            day_data["win_rate"] = 0
        result.append(day_data)
    return result


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/dashboard")
def dashboard() -> dict:
    """聚合 Dashboard 数据：KPI + Top5 信号 + 活跃持仓 + 7日命中率。"""
    accum = get_today_scans("accumulation")
    div = get_today_scans("divergence")
    breakout = get_today_scans("breakout")
    smc = get_today_scans("smc")

    all_signals = accum + div + breakout + smc
    is_today = True
    last_scan_time = None

    if not all_signals:
        is_today = False
        all_signals, last_scan_time = _get_latest_scan_signals()

    all_signals.sort(key=lambda s: s.get("score", 0), reverse=True)

    signal_counts = {"accumulation": 0, "divergence": 0, "breakout": 0, "smc": 0}
    for s in all_signals:
        m = s.get("mode", "")
        if m in signal_counts:
            signal_counts[m] += 1

    positions = get_open_positions()
    closed = get_closed_trades()

    today_str = datetime.now().strftime("%Y-%m-%d")
    today_closed = [
        t for t in closed if (t.get("closed_at") or "")[:10] == today_str
    ]
    today_pnl_pct = sum(t.get("pnl_pct", 0) for t in today_closed)

    overall = compute_stats(closed)
    hit_rate = _compute_7d_hit_rate(closed)

    return {
        "kpi": {
            "today_signals": len(all_signals),
            "active_positions": len(positions),
            "today_pnl_pct": round(today_pnl_pct, 4),
            "today_pnl_count": len(today_closed),
            "win_rate": overall.get("win_rate", 0),
            "total_trades": overall.get("total", 0),
        },
        "top_signals": all_signals[:5],
        "positions": positions,
        "hit_rate_7d": hit_rate,
        "signal_counts": signal_counts,
        "is_today": is_today,
        "last_scan_time": last_scan_time,
    }


@router.get("/signals")
def signals(
    mode: str = Query(""),
    min_score: Optional[float] = Query(None),
    date_from: str = Query(""),
    date_to: str = Query(""),
    page: int = Query(1),
    per_page: int = Query(20),
) -> dict:
    """分页查询信号，支持筛选。"""
    mode_val = mode.strip() or None
    date_from_val = date_from.strip() or None
    date_to_val = date_to.strip() or None

    rows, total = query_scan_results(
        mode=mode_val,
        scan_time_from=date_from_val,
        scan_time_to=date_to_val,
        page=page,
        per_page=per_page,
    )

    if min_score is not None:
        rows = [r for r in rows if r.get("score", 0) >= min_score]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return {
        "data": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }


@router.get("/positions")
def positions() -> dict:
    """活跃持仓列表。"""
    return {"data": get_open_positions()}


@router.get("/positions/closed")
def positions_closed(
    page: int = Query(1),
    per_page: int = Query(20),
) -> dict:
    """已平仓交易，分页。"""
    all_trades = get_closed_trades()
    total = len(all_trades)
    start = (page - 1) * per_page
    end = start + per_page
    page_trades = all_trades[start:end]

    return {
        "data": page_trades,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


@router.get("/coin/{symbol:path}")
def coin_detail(symbol: str) -> dict:
    """单币种详情：扫描记录 + 交易记录。"""
    symbol = symbol.upper()
    scans, total = query_scan_results(symbol=symbol, per_page=500, max_per_page=500)
    trades = get_closed_trades_by_symbol(symbol)
    return {
        "symbol": symbol,
        "scans": scans,
        "trades": trades,
        "total_scans": total,
    }


@router.get("/performance")
def performance() -> dict:
    """绩效分析：总体 + 按模式/分数/月份。"""
    trades = get_closed_trades()
    overall = compute_stats(trades)
    by_mode = compute_stats_by_mode(trades)
    by_score = compute_stats_by_score_tier(trades)
    by_month = compute_stats_by_month(trades)

    cumulative: list[dict] = []
    cum_pnl = 0.0
    sorted_trades = sorted(trades, key=lambda t: t.get("closed_at", ""))
    for t in sorted_trades:
        cum_pnl += t.get("pnl_pct", 0)
        cumulative.append(
            {
                "date": (t.get("closed_at") or "")[:10],
                "cumulative_pnl": round(cum_pnl, 4),
            }
        )

    return {
        "overall": overall,
        "by_mode": by_mode,
        "by_score": by_score,
        "by_month": by_month,
        "cumulative_pnl": cumulative,
    }


@router.post("/scan")
def trigger_scan(
    mode: str = Query("all"),
) -> dict:
    """触发扫描。mode=all 跑全部，或指定单个模式：accumulation/divergence/breakout/smc。"""
    from api.app import scan_lock, scan_state

    if not scan_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="已有扫描在进行中")

    def _run() -> None:
        scan_state["running"] = True
        scan_state["started_at"] = time.time()
        scan_state["error"] = None
        try:
            from main import load_config, run, run_breakout, run_divergence, run_smc

            cfg, sig_cfg, *_ = load_config(
                os.path.join(os.path.dirname(__file__), "..", "..", "config.yaml")
            )
            all_modes = [
                (run, "accumulation"),
                (run_divergence, "divergence"),
                (run_breakout, "breakout"),
                (run_smc, "smc"),
            ]
            targets = all_modes if mode == "all" else [(fn, n) for fn, n in all_modes if n == mode]
            for fn, name in targets:
                try:
                    fn(cfg, sig_cfg)
                except Exception as e:
                    scan_state["error"] = f"{name}: {e}"
        finally:
            scan_state["running"] = False
            scan_state["finished_at"] = time.time()
            scan_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"started": True}


@router.get("/scan/status")
def scan_status() -> dict:
    """扫描状态。"""
    from api.app import scan_state

    return dict(scan_state)


@router.get("/klines/{symbol:path}")
def klines(
    symbol: str,
    days: int = Query(30),
) -> dict:
    """获取某币种最近 N 天的 OHLCV K线数据。"""
    days = min(max(7, days), 180)
    symbol = symbol.upper()
    try:
        from scanner.kline import fetch_klines

        df = fetch_klines(symbol, days=days)
        if df is None or df.empty:
            raise HTTPException(
                status_code=404, detail=f"No klines for {symbol}"
            )
        data = []
        for _, row in df.iterrows():
            data.append(
                {
                    "timestamp": str(row["timestamp"]),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"]),
                }
            )
        return {"symbol": symbol, "days": days, "data": data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals/active")
def active_signals() -> dict:
    """活跃信号（含当前价格、未实现盈亏）。"""
    signals = get_active_signals()
    for sig in signals:
        sig["approaching"] = None
        current = sig.get("current_price")
        entry = sig.get("entry_price") or sig.get("price")
        sl = sig.get("stop_loss_price")
        tp = sig.get("take_profit_price")
        if current and entry and sl and tp:
            sl_dist = (
                abs(current - sl) / abs(entry - sl)
                if abs(entry - sl) > 0
                else 1
            )
            tp_dist = (
                abs(tp - current) / abs(tp - entry)
                if abs(tp - entry) > 0
                else 1
            )
            if sl_dist < 0.3:
                sig["approaching"] = "sl"
            elif tp_dist < 0.3:
                sig["approaching"] = "tp"
    return {"data": signals}


@router.get("/signals/outcomes")
def signal_outcomes(
    days: int = Query(30),
) -> dict:
    """近 30 天信号结果分布。"""
    outcomes = get_signal_outcomes(days=days)
    return {"data": outcomes}


@router.get("/signals/trend")
def signal_trend(
    days: int = Query(7),
) -> dict:
    """近 7 天每天各模式信号数量趋势。"""
    trend = get_signal_count_trend(days=days)
    return {"data": trend}


@router.get("/config")
def get_config() -> dict:
    """读取 config.yaml（跳过 numpy 序列化字段）。"""
    import yaml

    config_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "config.yaml"
    )
    with open(config_path) as f:
        raw = f.read()
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = {}
    if data is None:
        data = {}
    if "optimized" in data:
        opt = data["optimized"]
        for k, v in list(opt.items()):
            if not isinstance(v, (int, float, bool, str, type(None))):
                opt[k] = None
    return data
