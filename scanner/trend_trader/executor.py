"""趋势跟踪真实下单执行器 (独立于 scanner/trader/executor.py)。

核心差异 (vs divergence executor):
  - 市价开仓 (突破当日收盘, 限价可能追不上)
  - 不挂 TP (策略没有固定目标价, 靠每日动态 Chand/Donch 止损触发)
  - 挂"保险 STOP_MARKET" (entry - N × ATR, 距离正常止损很远)
    作为进程挂掉时的救命兜底, 不替代正常止损
  - 加仓时重挂保险 SL 覆盖总持仓量

所有函数返回 dict 或 raise; 不自己处理 DB, 状态同步交由 trend_live.py。
"""
from __future__ import annotations

import logging
import time

import ccxt

from scanner.trader.position_mode import position_side_params

logger = logging.getLogger("trend_trader.executor")

MAX_RETRIES = 3
RETRY_DELAY = 5


def _retry(fn, retries: int = MAX_RETRIES, delay: float = RETRY_DELAY):
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
            last_err = e
            logger.warning("网络异常 (第 %d 次): %s", i + 1, e)
            time.sleep(delay)
    raise last_err  # type: ignore[misc]


def _to_precision(exchange: ccxt.binanceusdm, symbol: str, amount: float) -> float:
    """按交易所步长取整 amount。"""
    return float(exchange.amount_to_precision(symbol, amount))


def _fetch_mark_price(exchange: ccxt.binanceusdm, symbol: str) -> float:
    ticker = _retry(lambda: exchange.fetch_ticker(symbol))
    return float(ticker.get("last") or ticker.get("close") or 0.0)


def _place_safety_sl(
    exchange: ccxt.binanceusdm,
    symbol: str,
    total_amount: float,
    sl_price: float,
) -> str:
    """挂保险 STOP_MARKET 单 (reduceOnly), 返回订单 ID。"""
    ps_params = position_side_params(False, exchange)  # 多头
    order = _retry(lambda: exchange.create_order(
        symbol=symbol,
        type="STOP_MARKET",
        side="sell",
        amount=total_amount,
        params={"stopPrice": sl_price, "reduceOnly": True, **ps_params},
    ))
    return order["id"]


def _cancel_safety_sl(exchange: ccxt.binanceusdm, symbol: str, sl_order_id: str | None) -> None:
    """取消旧保险 SL (忽略不存在/已成交错误)。"""
    if not sl_order_id:
        return
    try:
        exchange.cancel_order(sl_order_id, symbol)
    except Exception as e:
        logger.warning("[%s] 取消保险 SL %s 失败 (可能已成交或不存在): %s",
                       symbol, sl_order_id, e)


def open_position_live(
    exchange: ccxt.binanceusdm,
    symbol: str,
    notional_usd: float,
    leverage: int,
    atr: float,
    sl_multiplier: float,
) -> dict:
    """市价开多 + 挂保险 SL。

    Returns:
        {
          "filled_price": float,
          "filled_amount": float,
          "sl_order_id": str,
          "sl_price": float,
        }
    """
    # 1. 设杠杆
    try:
        _retry(lambda: exchange.set_leverage(leverage, symbol))
    except Exception as e:
        logger.warning("[%s] 杠杆设置失败 (可能已是 %dx): %s", symbol, leverage, e)

    # 2. 计算开仓数量
    mark = _fetch_mark_price(exchange, symbol)
    if mark <= 0:
        raise RuntimeError(f"{symbol} 无法取得市价")
    raw_amount = notional_usd / mark
    amount = _to_precision(exchange, symbol, raw_amount)
    if amount <= 0:
        raise RuntimeError(f"{symbol} 精度取整后数量为 0 (notional={notional_usd}, price={mark})")

    # 3. 市价开多
    ps_params = position_side_params(False, exchange)
    order = _retry(lambda: exchange.create_order(
        symbol=symbol,
        type="market",
        side="buy",
        amount=amount,
        params=ps_params,
    ))
    filled_price = float(order.get("average") or order.get("price") or mark)
    filled_amount = float(order.get("filled") or amount)

    # 4. 挂保险 SL
    sl_price = filled_price - sl_multiplier * atr
    if sl_price <= 0:
        logger.error("[%s] 保险 SL 价格 %.6g 无效 (ATR=%.6g × %.1f > entry)",
                     symbol, sl_price, atr, sl_multiplier)
        # 继续 — 开仓已成功, SL 单失败不算致命
        sl_order_id = ""
    else:
        try:
            sl_order_id = _place_safety_sl(exchange, symbol, filled_amount, sl_price)
        except Exception as e:
            logger.error("[%s] 保险 SL 挂单失败: %s (仓位已开但无兜底 SL!)", symbol, e)
            sl_order_id = ""

    logger.info(
        "[%s] OPEN amount=%.6g @ %.6g 杠杆=%dx 保险SL=%.6g (order=%s)",
        symbol, filled_amount, filled_price, leverage, sl_price, sl_order_id,
    )
    return {
        "filled_price": filled_price,
        "filled_amount": filled_amount,
        "sl_order_id": sl_order_id,
        "sl_price": sl_price,
    }


def add_pyramid_live(
    exchange: ccxt.binanceusdm,
    symbol: str,
    notional_usd: float,
    atr: float,
    sl_multiplier: float,
    old_sl_order_id: str | None,
    trailing_high: float,
    total_amount_after_pyramid: float | None = None,
) -> dict:
    """市价加仓一层 + 重挂保险 SL (覆盖总持仓量)。

    Args:
        total_amount_after_pyramid: 如果调用方已知加仓后总数量, 可传入避免多一次
            fetch_positions。否则会查询交易所。
    """
    # 1. 取消旧 SL
    _cancel_safety_sl(exchange, symbol, old_sl_order_id)

    # 2. 市价加仓
    mark = _fetch_mark_price(exchange, symbol)
    if mark <= 0:
        raise RuntimeError(f"{symbol} 无法取得市价")
    raw_amount = notional_usd / mark
    amount = _to_precision(exchange, symbol, raw_amount)
    if amount <= 0:
        raise RuntimeError(f"{symbol} 加仓精度取整后为 0")

    ps_params = position_side_params(False, exchange)
    order = _retry(lambda: exchange.create_order(
        symbol=symbol,
        type="market",
        side="buy",
        amount=amount,
        params=ps_params,
    ))
    filled_price = float(order.get("average") or order.get("price") or mark)
    filled_amount = float(order.get("filled") or amount)

    # 3. 查询或使用传入的总数量
    if total_amount_after_pyramid is None:
        try:
            positions = _retry(lambda: exchange.fetch_positions([symbol]))
            total_amount = sum(
                float(p.get("contracts", 0))
                for p in positions
                if float(p.get("contracts", 0)) > 0
            )
        except Exception as e:
            logger.warning("[%s] 查询总持仓失败, 用本次成交量: %s", symbol, e)
            total_amount = filled_amount
    else:
        total_amount = total_amount_after_pyramid

    # 4. 挂新保险 SL (基于 trailing_high)
    base = max(filled_price, trailing_high)
    new_sl_price = base - sl_multiplier * atr
    if new_sl_price <= 0 or total_amount <= 0:
        logger.error("[%s] 加仓后保险 SL 参数无效", symbol)
        new_sl_order_id = ""
    else:
        try:
            new_sl_order_id = _place_safety_sl(exchange, symbol, total_amount, new_sl_price)
        except Exception as e:
            logger.error("[%s] 加仓后重挂保险 SL 失败: %s", symbol, e)
            new_sl_order_id = ""

    logger.info(
        "[%s] PYRAMID amount=%.6g @ %.6g 总量=%.6g 新保险SL=%.6g (order=%s)",
        symbol, filled_amount, filled_price, total_amount, new_sl_price, new_sl_order_id,
    )
    return {
        "filled_price": filled_price,
        "filled_amount": filled_amount,
        "sl_order_id": new_sl_order_id,
        "sl_price": new_sl_price,
        "total_amount": total_amount,
    }


def close_position_live(
    exchange: ccxt.binanceusdm,
    symbol: str,
    amount: float,
    sl_order_id: str | None,
    reason: str,
) -> dict:
    """市价平多 (reduceOnly) + 取消保险 SL。

    Returns: {"close_price": float, "close_amount": float}
    """
    # 1. 先取消保险 SL
    _cancel_safety_sl(exchange, symbol, sl_order_id)

    # 2. 市价平多
    amt = _to_precision(exchange, symbol, amount)
    if amt <= 0:
        raise RuntimeError(f"{symbol} 平仓精度取整后为 0")
    ps_params = position_side_params(False, exchange)
    order = _retry(lambda: exchange.create_order(
        symbol=symbol,
        type="market",
        side="sell",
        amount=amt,
        params={"reduceOnly": True, **ps_params},
    ))
    close_price = float(order.get("average") or order.get("price") or 0.0)
    logger.info("[%s] CLOSE amount=%.6g @ %.6g 原因=%s", symbol, amt, close_price, reason)
    return {"close_price": close_price, "close_amount": amt}
