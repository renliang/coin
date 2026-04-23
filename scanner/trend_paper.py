"""Paper trading 执行器 — 把 ScanTrendResult 应用到 SQLite 持仓表。

不下真单, 只维护虚拟持仓状态, 用于:
  1. 验证信号在真实市场的完整生命周期 (开仓 → 加仓 → 止损)
  2. 对比 paper 曲线 vs 回测预期, 发现数据口径或逻辑 bug
  3. Phase 2 上线前最后一道安全验证
"""
from __future__ import annotations

import pandas as pd

from scanner.trend_position_store import (
    add_pyramid,
    close_position,
    get_open_positions,
    get_position,
    open_position,
    update_trailing_high,
)
from scanner.trend_scanner import ScanTrendResult


def paper_execute(
    result: ScanTrendResult,
    today: str,
    level_capital: float = 0.1,
) -> dict:
    """应用扫描结果到 DB。处理顺序: 平仓 → 加仓 → 开仓。

    Args:
        result: scan_trend_actions 的输出。
        today: ISO 日期 'YYYY-MM-DD', 用作入场/平仓时间戳。
        level_capital: 每层仓位占初始权益的比例 (默认 0.1 = 1/10)。
            units = level_capital / execution_price

    Returns:
        {"opened": [...], "added": [...], "closed": [...]} 当日已应用的动作列表。
    """
    applied = {"opened": [], "added": [], "closed": []}

    # ── 1. 平仓 (最优先) ──
    for a in result.exits:
        p = get_position(a.symbol)
        if p is None or p.status != "open":
            continue  # 防御: 信号与 DB 不一致, 安静跳过
        p_closed = close_position(a.symbol, a.price, a.reason, today)
        applied["closed"].append({
            "symbol": a.symbol,
            "price": a.price,
            "reason": a.reason,
            "pnl_pct": p_closed.realized_pnl_pct,
            "levels": p_closed.levels,
        })

    # ── 2. 金字塔加仓 ──
    for a in result.pyramid_adds:
        p = get_position(a.symbol)
        if p is None or p.status != "open":
            continue
        # 幂等: 同日重复加仓直接跳过
        if any(e.date == today for e in p.entries):
            continue
        if a.price <= 0:
            continue
        units = level_capital / a.price
        add_pyramid(a.symbol, a.price, units, today)
        applied["added"].append({
            "symbol": a.symbol,
            "price": a.price,
            "new_level": a.new_level,
        })

    # ── 3. 开仓 ──
    for a in result.entries:
        existing = get_position(a.symbol)
        if existing is not None and existing.status == "open":
            continue
        if a.price <= 0:
            continue
        units = level_capital / a.price
        open_position(a.symbol, a.price, units, a.atr, today)
        applied["opened"].append({
            "symbol": a.symbol,
            "price": a.price,
            "atr": a.atr,
        })

    return applied


def update_all_trailing_highs(klines: dict[str, pd.DataFrame]) -> int:
    """用今日最后一根 K 线的 close 更新所有 open 持仓的 trailing_high。

    只上调, 不下调。
    Returns: 被更新 (实际上调) 的持仓数量。
    """
    n = 0
    for pos in get_open_positions():
        df = klines.get(pos.symbol)
        if df is None or len(df) == 0:
            continue
        today_close = float(df["close"].iloc[-1])
        if today_close > pos.trailing_high:
            update_trailing_high(pos.symbol, today_close)
            n += 1
    return n


def compute_paper_nav(klines: dict[str, pd.DataFrame]) -> dict:
    """计算当前 paper 组合的权益状态 (mark-to-market)。

    starting_equity = 1.0
    nav = 1 + realized_pnl_pct_sum_weighted + unrealized_pnl_sum

    注意: realized_pnl_pct 存的是单笔 PnL / 该笔成本, 不能简单相加。
    这里按"每笔占 1 个 level_capital (0.1)"换算到整体权益的贡献。

    返回汇总字典供外层打印。
    """
    from scanner.trend_position_store import _get_conn  # 私有访问, 仅内部用
    # 算已实现 PnL (单位: 占初始权益比例)
    # 每笔平仓: realized_pnl_pct × (该笔 total_cost) ≈ pnl_absolute
    # 但 total_cost 没直接存; 我们改用"每层 level_capital = 0.1"近似
    # 未实现 PnL: 对所有 open 持仓, 计算 (today_close / avg_price - 1) × total_cost
    # 其中 total_cost ≈ levels × level_capital
    # → unreal_contrib = levels × level_capital × (today_close/avg_price - 1)
    level_capital = 0.1

    realized_contrib = 0.0
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT realized_pnl_pct, entries_json FROM trend_positions WHERE status = 'closed'"
        ).fetchall()
    import json
    for row in rows:
        pnl_pct = row["realized_pnl_pct"] or 0.0
        entries = json.loads(row["entries_json"])
        n_levels = len(entries)
        # 每笔 PnL 的权益贡献 = pnl_pct × (n_levels × level_capital)
        realized_contrib += pnl_pct * n_levels * level_capital

    unreal_contrib = 0.0
    open_positions = get_open_positions()
    for p in open_positions:
        df = klines.get(p.symbol)
        if df is None or len(df) == 0:
            continue
        today_close = float(df["close"].iloc[-1])
        if p.avg_price <= 0:
            continue
        ret_pct = today_close / p.avg_price - 1.0
        unreal_contrib += ret_pct * p.levels * level_capital

    nav = 1.0 + realized_contrib + unreal_contrib
    return {
        "nav": nav,
        "realized_contrib": realized_contrib,
        "unrealized_contrib": unreal_contrib,
        "n_open": len(open_positions),
        "n_closed": len(rows),
    }
