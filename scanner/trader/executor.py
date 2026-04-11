"""下单执行：限价开仓 + TPSL + 异常处理。

关键原则：宁可不开仓，也不开裸仓（没有 TPSL 的仓位不允许存在）。
"""

import logging
import time

import ccxt

from scanner.signal import TradeSignal
from scanner.tracker import save_order, save_position, update_order_status

logger = logging.getLogger("trader.executor")

MAX_RETRIES = 3
RETRY_DELAY = 5


def _retry(fn, retries: int = MAX_RETRIES, delay: float = RETRY_DELAY):
    """通用重试包装。"""
    last_err = None
    for i in range(retries):
        try:
            return fn()
        except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
            last_err = e
            logger.warning("网络异常 (第%d次重试): %s", i + 1, e)
            time.sleep(delay)
    raise last_err


def execute_trade(
    exchange: ccxt.binanceusdm,
    signal: TradeSignal,
    amount: float,
    leverage: int,
) -> bool:
    """执行单笔交易：设杠杆 → 限价开仓 → 挂 TPSL。

    如果 TPSL 挂失败，会撤掉主单保证不出现裸仓。
    Returns True 如果成功，False 如果跳过。
    """
    symbol = signal.symbol
    is_short = signal.signal_type == "顶背离"
    side = "sell" if is_short else "buy"
    position_side = "SHORT" if is_short else "LONG"

    # 1. 设置杠杆
    try:
        _retry(lambda: exchange.set_leverage(leverage, symbol))
        logger.info("[%s] 杠杆设置为 %dx", symbol, leverage)
    except Exception as e:
        logger.error("[%s] 杠杆设置失败: %s，跳过", symbol, e)
        return False

    # 2. 限价开仓（支持双向持仓模式）
    try:
        order = _retry(lambda: exchange.create_order(
            symbol=symbol,
            type="limit",
            side=side,
            amount=amount,
            price=signal.entry_price,
            params={"positionSide": position_side},
        ))
        order_id = order["id"]
        logger.info("[%s] 限价单已下: %s %s %.4f @ %.4f, order_id=%s",
                     symbol, side, amount, signal.entry_price, signal.entry_price, order_id)
    except ccxt.InsufficientFunds:
        logger.warning("[%s] 余额不足，跳过", symbol)
        return False
    except Exception as e:
        logger.error("[%s] 限价单失败: %s，跳过", symbol, e)
        return False

    # 记录主单到 DB
    save_order(
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type="limit",
        price=signal.entry_price,
        amount=amount,
        leverage=leverage,
    )

    # 3. 挂 TPSL
    tp_order_id = None
    sl_order_id = None
    tpsl_ok = True

    # 止盈单
    try:
        tp_side = "buy" if is_short else "sell"
        tp_order = _retry(lambda: exchange.create_order(
            symbol=symbol,
            type="TAKE_PROFIT_MARKET",
            side=tp_side,
            amount=amount,
            params={
                "stopPrice": signal.take_profit_price,
                "positionSide": position_side,
            },
        ))
        tp_order_id = tp_order["id"]
        logger.info("[%s] 止盈单已挂: %.4f, order_id=%s", symbol, signal.take_profit_price, tp_order_id)
    except Exception as e:
        logger.error("[%s] 止盈单失败: %s", symbol, e)
        tpsl_ok = False

    # 止损单
    if tpsl_ok:
        try:
            sl_order = _retry(lambda: exchange.create_order(
                symbol=symbol,
                type="STOP_MARKET",
                side=tp_side,
                amount=amount,
                params={
                    "stopPrice": signal.stop_loss_price,
                    "positionSide": position_side,
                },
            ))
            sl_order_id = sl_order["id"]
            logger.info("[%s] 止损单已挂: %.4f, order_id=%s", symbol, signal.stop_loss_price, sl_order_id)
        except Exception as e:
            logger.error("[%s] 止损单失败: %s", symbol, e)
            tpsl_ok = False

    # TPSL 失败 → 撤主单（宁可不开仓也不开裸仓）
    if not tpsl_ok:
        logger.warning("[%s] TPSL 挂单失败，撤掉主单 %s", symbol, order_id)
        try:
            exchange.cancel_order(order_id, symbol)
            update_order_status(order_id, "cancelled")
            # 如果止盈已挂，也撤掉
            if tp_order_id:
                exchange.cancel_order(tp_order_id, symbol)
        except Exception as e:
            logger.error("[%s] 撤单失败: %s (需手动处理!)", symbol, e)
        return False

    # 4. 记录持仓
    save_position(
        symbol=symbol,
        side="short" if is_short else "long",
        entry_price=signal.entry_price,
        size=amount,
        leverage=leverage,
        score=signal.score,
        tp_order_id=tp_order_id,
        sl_order_id=sl_order_id,
        mode=signal.mode,
    )

    logger.info("[%s] 交易完成: %s %.4f @ %.4f, 杠杆=%dx, TP=%.4f, SL=%.4f",
                 symbol, side, amount, signal.entry_price, leverage,
                 signal.take_profit_price, signal.stop_loss_price)
    return True
