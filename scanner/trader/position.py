"""仓位管理：查交易所持仓、过滤已持有 / 已挂单、卡上限。"""

import logging

import ccxt

from scanner.signal import TradeSignal
from scanner.tracker import get_open_orders

logger = logging.getLogger("trader.position")


def get_exchange_positions(exchange: ccxt.binanceusdm) -> list[dict]:
    """查询交易所当前所有持仓（非零）。"""
    try:
        positions = exchange.fetch_positions()
        return [
            p for p in positions
            if float(p.get("contracts", 0)) > 0
        ]
    except Exception as e:
        logger.error("查询持仓失败: %s", e)
        raise


def get_pending_limit_symbols() -> set[str]:
    """从本地 DB 获取所有 open 状态的限价开仓单所覆盖的 symbol 集合。"""
    try:
        rows = get_open_orders(order_type="limit")
        return {r["symbol"] for r in rows}
    except Exception as e:
        logger.warning("查询本地挂单失败，跳过挂单去重: %s", e)
        return set()


def filter_signals(
    exchange: ccxt.binanceusdm,
    signals: list[TradeSignal],
    max_positions: int,
) -> list[TradeSignal]:
    """过滤信号：去掉已持有的币 + 已有 open 限价单的币，按评分排序，卡持仓上限。

    卡上限时也把已挂未成交的限价单计入占用槽位，避免重复下单。

    Returns:
        过滤后可开仓的信号列表。
    """
    current = get_exchange_positions(exchange)
    held_symbols = {p["symbol"] for p in current}
    pending_symbols = get_pending_limit_symbols()
    occupied = held_symbols | pending_symbols

    available = [s for s in signals if s.symbol not in occupied]
    available.sort(key=lambda s: s.score, reverse=True)

    slots = max_positions - len(occupied)
    if slots <= 0:
        logger.info(
            "仓位已满 (持仓 %d + 挂单 %d / 上限 %d)，跳过本轮下单",
            len(held_symbols), len(pending_symbols), max_positions,
        )
        return []

    result = available[:slots]
    if len(available) > slots:
        logger.info(
            "可用信号 %d 个（已剔除 %d 个持仓 + %d 个挂单），空余仓位 %d，取前 %d",
            len(available), len(held_symbols), len(pending_symbols), slots, slots,
        )

    return result
