"""仓位管理：查交易所持仓、过滤已持有、卡上限。"""

import logging

import ccxt

from scanner.signal import TradeSignal

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


def filter_signals(
    exchange: ccxt.binanceusdm,
    signals: list[TradeSignal],
    max_positions: int,
) -> list[TradeSignal]:
    """过滤信号：去掉已持有的币，按评分排序，卡持仓上限。

    Returns:
        过滤后可开仓的信号列表。
    """
    current = get_exchange_positions(exchange)
    held_symbols = {p["symbol"] for p in current}

    # 过滤掉已持有的
    available = [s for s in signals if s.symbol not in held_symbols]

    # 按评分排序
    available.sort(key=lambda s: s.score, reverse=True)

    # 卡上限
    slots = max_positions - len(current)
    if slots <= 0:
        logger.info("持仓已满 (%d/%d)，跳过本轮下单", len(current), max_positions)
        return []

    result = available[:slots]
    if len(available) > slots:
        logger.info("可用信号 %d 个，空余仓位 %d 个，取前 %d 个", len(available), slots, slots)

    return result
