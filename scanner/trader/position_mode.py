"""账号持仓模式自适应：查询币安合约账号是 Hedge (双向) 还是 One-way (单向)。

- Hedge 模式：下单必须传 positionSide=LONG/SHORT
- One-way 模式：下单不能传 positionSide（或只能传 BOTH）
传参不对会报 -4061 Order's position side does not match user's setting。
"""

import logging

logger = logging.getLogger("trader.position_mode")

_cache: dict[int, bool] = {}


def is_hedge_mode(exchange) -> bool:
    """True = 双向持仓 (Hedge)；False = 单向持仓 (One-way)。结果按 exchange 实例缓存。"""
    key = id(exchange)
    if key in _cache:
        return _cache[key]
    try:
        resp = exchange.fapiPrivateGetPositionSideDual()
        hedge = bool(resp.get("dualSidePosition"))
    except Exception as exc:
        logger.warning("查询持仓模式失败，默认单向持仓 (One-way): %s", exc)
        hedge = False
    _cache[key] = hedge
    logger.info("账号持仓模式: %s", "Hedge (双向)" if hedge else "One-way (单向)")
    return hedge


def position_side_params(is_short: bool, exchange) -> dict:
    """按账号模式返回 params 补丁：Hedge 返回 {'positionSide': ...}，One-way 返回 {}。"""
    if is_hedge_mode(exchange):
        return {"positionSide": "SHORT" if is_short else "LONG"}
    return {}


def clear_cache() -> None:
    """测试用：清除缓存。"""
    _cache.clear()
