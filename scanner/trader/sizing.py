"""评分 → 仓位百分比 + 杠杆计算 + 下单数量计算。"""

import logging
import math

import ccxt

logger = logging.getLogger("trader.sizing")

DEFAULT_SCORE_LEVERAGE = {0.6: 0.4, 0.7: 0.6, 0.8: 0.8, 0.9: 1.0}


def get_position_pct(score: float, score_sizing: dict[float, float]) -> float:
    """根据评分查找仓位百分比。取 <= score 的最大阈值对应的百分比。"""
    thresholds = sorted(score_sizing.keys(), reverse=True)
    for t in thresholds:
        if score >= t:
            return score_sizing[t]
    return 0.0


def _lookup_tiered(score: float, tiers: dict[float, float]) -> float:
    """通用分档查找：取 <= score 的最大阈值对应的值。"""
    thresholds = sorted(tiers.keys(), reverse=True)
    for t in thresholds:
        if score >= t:
            return tiers[t]
    return 0.0


def calculate_leverage(
    stop_distance: float,
    score: float,
    safety_factor: float = 1.5,
    max_leverage: int = 20,
    exchange_max: int = 125,
    score_leverage: dict[float, float] | None = None,
) -> int:
    """根据止损距离和评分计算安全杠杆。

    公式: safe_max = floor(1 / (stop_distance × safety_factor))
    实际杠杆 = min(safe_max × score_pct, max_leverage, exchange_max)
    返回 0 表示不应开仓。
    """
    if stop_distance <= 0:
        return 0
    tiers = score_leverage or DEFAULT_SCORE_LEVERAGE
    safe_max = math.floor(1.0 / (stop_distance * safety_factor))
    if safe_max < 1:
        return 0
    score_pct = _lookup_tiered(score, tiers)
    if score_pct <= 0:
        return 0
    leverage = math.floor(safe_max * score_pct)
    if leverage < 1:
        return 0
    return min(leverage, max_leverage, exchange_max)


def get_max_leverage(exchange: ccxt.binanceusdm, symbol: str) -> int:
    """查询交易所该合约允许的最大杠杆。"""
    try:
        exchange.load_markets()
        market = exchange.market(symbol)
        max_lev = market.get("limits", {}).get("leverage", {}).get("max")
        if max_lev:
            return int(max_lev)
        resp = exchange.fapiPrivateGetLeverageBracket({"symbol": market["id"]})
        if resp and isinstance(resp, list):
            brackets = resp[0].get("brackets", [])
            if brackets:
                return int(brackets[0].get("initialLeverage", 20))
    except Exception as e:
        logger.warning("查询 %s 最大杠杆失败: %s，使用默认 20x", symbol, e)
    return 20


def calculate_position(
    balance: float,
    price: float,
    score: float,
    leverage: int,
    score_sizing: dict[float, float],
) -> float:
    """计算下单数量（以标的币为单位）。

    公式: amount = (balance * pct * leverage) / price
    """
    pct = get_position_pct(score, score_sizing)
    if pct <= 0:
        return 0.0
    notional = balance * pct * leverage
    amount = notional / price
    return amount
