"""趋势跟踪 Live 执行层 — 真实下单 + 同步 SQLite 持仓状态。

和 scanner/trend_paper.py 结构一致, 但调真实下单。
顺序: 平仓 (含取消保险 SL) → 加仓 (含重挂保险 SL) → 开仓 (含挂保险 SL)。

所有下单失败都 try/except 包住, 错误不中断其它信号处理。
DB 写入仅在下单成功后进行, 避免"DB 有记录但交易所无单"的漂移。
"""
from __future__ import annotations

import logging

import ccxt

from scanner.trend_position_store import (
    add_pyramid,
    close_position,
    get_position,
    open_position,
    update_safety_sl_order_id,
)
from scanner.trend_scanner import ScanTrendResult
from scanner.trend_trader.executor import (
    add_pyramid_live,
    close_position_live,
    open_position_live,
)

logger = logging.getLogger("trend_trader.live")


def live_execute(
    result: ScanTrendResult,
    exchange: ccxt.binanceusdm,
    notional_per_level: float,
    leverage: int,
    sl_multiplier: float,
    today: str,
) -> dict:
    """把 ScanTrendResult 真实执行到交易所, 同步 DB 持仓状态。

    Args:
        result: scan_trend_actions 的输出。
        exchange: 带 API key 的 ccxt.binanceusdm 实例。
        notional_per_level: 每层名义仓位 USDT (e.g. 20)。
        leverage: 杠杆倍数 (e.g. 10)。
        sl_multiplier: 保险 SL 距离 (entry - N × ATR)。
        today: ISO 日期, 用于 DB 记录。

    Returns:
        {
          "opened": [...], "added": [...], "closed": [...],
          "errors": [{"action", "symbol", "error"}, ...],
        }
    """
    applied = {"opened": [], "added": [], "closed": [], "errors": []}

    # ── 1. 平仓 ──
    for a in result.exits:
        pos = get_position(a.symbol)
        if pos is None or pos.status != "open":
            continue
        try:
            r = close_position_live(
                exchange, a.symbol, pos.total_units, pos.safety_sl_order_id, a.reason,
            )
            # 下单成功 → 写 DB
            close_position(a.symbol, r["close_price"], a.reason, today)
            applied["closed"].append({
                "symbol": a.symbol,
                "price": r["close_price"],
                "reason": a.reason,
                "levels": pos.levels,
            })
        except Exception as e:
            logger.error("[%s] LIVE CLOSE 失败: %s", a.symbol, e)
            applied["errors"].append({
                "action": "close", "symbol": a.symbol, "error": str(e),
            })

    # ── 2. 金字塔加仓 ──
    for a in result.pyramid_adds:
        pos = get_position(a.symbol)
        if pos is None or pos.status != "open":
            continue
        # 幂等: 同日重复加仓跳过
        if any(e.date == today for e in pos.entries):
            continue
        try:
            total_after = pos.total_units  # 近似: 加仓前 + 本次预估 → 由 executor 查真相
            r = add_pyramid_live(
                exchange, a.symbol, notional_per_level,
                atr=pos.atr_at_open, sl_multiplier=sl_multiplier,
                old_sl_order_id=pos.safety_sl_order_id,
                trailing_high=max(pos.trailing_high, a.trailing_high),
            )
            # 下单成功 → 写 DB
            add_pyramid(a.symbol, r["filled_price"], r["filled_amount"], today)
            update_safety_sl_order_id(a.symbol, r["sl_order_id"])
            applied["added"].append({
                "symbol": a.symbol,
                "price": r["filled_price"],
                "amount": r["filled_amount"],
                "new_level": a.new_level,
                "sl_order_id": r["sl_order_id"],
            })
        except Exception as e:
            logger.error("[%s] LIVE PYRAMID 失败: %s", a.symbol, e)
            applied["errors"].append({
                "action": "pyramid", "symbol": a.symbol, "error": str(e),
            })

    # ── 3. 开仓 ──
    for a in result.entries:
        existing = get_position(a.symbol)
        if existing is not None and existing.status == "open":
            continue
        try:
            r = open_position_live(
                exchange, a.symbol,
                notional_usd=notional_per_level,
                leverage=leverage,
                atr=a.atr,
                sl_multiplier=sl_multiplier,
            )
            # 下单成功 → 写 DB (包含 sl_order_id)
            open_position(
                a.symbol, r["filled_price"], r["filled_amount"],
                a.atr, today,
                safety_sl_order_id=r["sl_order_id"],
            )
            applied["opened"].append({
                "symbol": a.symbol,
                "price": r["filled_price"],
                "amount": r["filled_amount"],
                "atr": a.atr,
                "sl_order_id": r["sl_order_id"],
            })
        except Exception as e:
            logger.error("[%s] LIVE OPEN 失败: %s", a.symbol, e)
            applied["errors"].append({
                "action": "open", "symbol": a.symbol, "error": str(e),
            })

    return applied
