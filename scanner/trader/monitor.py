"""订单监控：限价单超时转市价 + 订单状态同步 + TPSL 触发检查。"""

import logging
from datetime import datetime, timedelta

import ccxt

from scanner.tracker import (
    get_open_orders,
    get_open_positions,
    update_order_status,
    close_position,
    save_order,
    get_order_by_id,
)
from scanner.trader.position_mode import position_side_params

logger = logging.getLogger("trader.monitor")


def check_orders(exchange: ccxt.binanceusdm, timeout_minutes: int = 30) -> None:
    """检查所有 open 状态的限价单，处理超时和成交。"""
    orders = get_open_orders(order_type="limit")
    if not orders:
        return

    now = datetime.now()
    cutoff = now - timedelta(minutes=timeout_minutes)

    for order_row in orders:
        order_id = order_row["order_id"]
        symbol = order_row["symbol"]

        try:
            exchange_order = exchange.fetch_order(order_id, symbol)
        except Exception as e:
            logger.warning("[%s] 查询订单 %s 失败: %s", symbol, order_id, e)
            continue

        status = exchange_order.get("status", "")

        if status == "closed":  # 已完全成交
            update_order_status(order_id, "filled")
            logger.info("[%s] 限价单 %s 已成交", symbol, order_id)

        elif status == "canceled":
            update_order_status(order_id, "cancelled")
            logger.info("[%s] 限价单 %s 已被取消", symbol, order_id)

        elif status == "open":
            created_at = datetime.strptime(order_row["created_at"], "%Y-%m-%d %H:%M:%S")
            if created_at <= cutoff:
                # 超时 → 撤单 → 市价补单
                _handle_timeout(exchange, order_row, exchange_order)


def _handle_timeout(
    exchange: ccxt.binanceusdm,
    order_row: dict,
    exchange_order: dict,
) -> None:
    """处理超时的限价单：撤掉 → 市价补单 → 更新 DB。"""
    order_id = order_row["order_id"]
    symbol = order_row["symbol"]
    side = order_row["side"]
    amount = order_row["amount"]

    filled = float(exchange_order.get("filled", 0))

    # 撤掉剩余
    try:
        exchange.cancel_order(order_id, symbol)
        update_order_status(order_id, "timeout_converted")
        logger.info("[%s] 超时撤单 %s (已成交 %.4f / %.4f)", symbol, order_id, filled, amount)
    except Exception as e:
        logger.error("[%s] 撤单失败: %s", symbol, order_id, e)
        return

    # 未成交部分转市价
    remaining = amount - filled
    if remaining > 0:
        try:
            is_short = side == "sell"
            market_order = exchange.create_order(
                symbol=symbol,
                type="market",
                side=side,
                amount=remaining,
                params=position_side_params(is_short, exchange),
            )
            save_order(
                order_id=market_order["id"],
                symbol=symbol,
                side=side,
                order_type="market",
                price=None,
                amount=remaining,
                leverage=order_row["leverage"],
                related_order_id=order_id,
            )
            update_order_status(market_order["id"], "filled")
            logger.info("[%s] 市价补单 %.4f, order_id=%s", symbol, remaining, market_order["id"])
        except Exception as e:
            logger.error("[%s] 市价补单失败: %s", symbol, e)


def _infer_exit(pos: dict, exchange: ccxt.binanceusdm) -> dict:
    """推断退出原因和价格。返回 {exit_price, exit_reason, pnl, pnl_pct}。"""
    entry_price = pos["entry_price"]
    size = pos["size"]
    is_short = pos["side"] == "short"

    # 查 TP 订单
    if pos.get("tp_order_id"):
        tp_order = get_order_by_id(pos["tp_order_id"])
        if tp_order and tp_order["status"] == "filled":
            exit_price = tp_order["price"]
            pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
            return {
                "exit_price": exit_price,
                "exit_reason": "tp",
                "pnl_pct": round(pnl_pct, 6),
                "pnl": round(pnl_pct * entry_price * size, 4),
            }

    # 查 SL 订单
    if pos.get("sl_order_id"):
        sl_order = get_order_by_id(pos["sl_order_id"])
        if sl_order and sl_order["status"] == "filled":
            exit_price = sl_order["price"]
            pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
            return {
                "exit_price": exit_price,
                "exit_reason": "sl",
                "pnl_pct": round(pnl_pct, 6),
                "pnl": round(pnl_pct * entry_price * size, 4),
            }

    # 手动平仓：取当前市价
    try:
        ticker = exchange.fetch_ticker(pos["symbol"])
        exit_price = ticker["last"]
    except Exception:
        exit_price = entry_price  # 取不到就用入场价（PnL=0）

    pnl_pct = (entry_price - exit_price) / entry_price if is_short else (exit_price - entry_price) / entry_price
    return {
        "exit_price": exit_price,
        "exit_reason": "manual",
        "pnl_pct": round(pnl_pct, 6),
        "pnl": round(pnl_pct * entry_price * size, 4),
    }


def check_positions(exchange: ccxt.binanceusdm) -> None:
    """检查持仓的 TPSL 是否已触发，更新已平仓的记录。"""
    positions = get_open_positions()
    if not positions:
        return

    try:
        exchange_positions = exchange.fetch_positions()
    except Exception as e:
        logger.error("查询交易所持仓失败: %s", e)
        return

    # 交易所当前有仓位的 symbol 集合
    active_symbols = set()
    for p in exchange_positions:
        if float(p.get("contracts", 0)) > 0:
            active_symbols.add(p["symbol"])

    # DB 里标记为 open 但交易所已无仓位 → 已平仓
    for pos in positions:
        if pos["symbol"] not in active_symbols:
            exit_info = _infer_exit(pos, exchange)
            close_position(
                pos["symbol"],
                exit_price=exit_info["exit_price"],
                pnl=exit_info["pnl"],
                pnl_pct=exit_info["pnl_pct"],
                exit_reason=exit_info["exit_reason"],
            )
            reason_label = {"tp": "止盈", "sl": "止损", "manual": "手动"}[exit_info["exit_reason"]]
            logger.info(
                "[%s] 仓位已平仓（%s）exit=%.4f pnl=%.2f%%",
                pos["symbol"], reason_label, exit_info["exit_price"], exit_info["pnl_pct"] * 100,
            )


def run_monitor_cycle(exchange: ccxt.binanceusdm, timeout_minutes: int = 30) -> None:
    """单次监控循环：检查订单 + 检查持仓。"""
    try:
        check_orders(exchange, timeout_minutes)
        check_positions(exchange)
    except Exception as e:
        logger.error("监控循环异常: %s", e)
