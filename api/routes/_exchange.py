"""API 层的交易所访问助手：带 5 秒缓存，避免每次请求都打币安。"""

import logging
import os
import time

logger = logging.getLogger("api.exchange")

_CACHE_TTL = 5.0
_cache: dict[str, tuple[float, list]] = {
    "positions": (0.0, []),
    "orders": (0.0, []),
}


def _get_exchange():
    """获取带认证的币安合约实例，没配 key 返回 None。"""
    api_key = os.environ.get("BINANCE_API_KEY")
    api_secret = os.environ.get("BINANCE_API_SECRET")
    if not api_key or not api_secret:
        return None
    from scanner.kline import get_authed_usdm, _usdm
    proxy = ""
    if _usdm is not None and hasattr(_usdm, "httpsProxy"):
        proxy = _usdm.httpsProxy or ""
    return get_authed_usdm(api_key, api_secret, proxy)


def fetch_exchange_positions() -> list[dict]:
    """查交易所实时持仓，返回原始 ccxt dict 列表（已过滤 contracts>0）。"""
    ts, data = _cache["positions"]
    if time.time() - ts < _CACHE_TTL:
        return data
    ex = _get_exchange()
    if ex is None:
        return []
    try:
        raw = ex.fetch_positions()
        data = [p for p in raw if float(p.get("contracts", 0) or 0) > 0]
        _cache["positions"] = (time.time(), data)
        return data
    except Exception as exc:
        logger.warning("fetch_positions 失败: %s", exc)
        return _cache["positions"][1]


def fetch_exchange_open_orders() -> list[dict]:
    """查交易所实时未完成订单，返回原始 ccxt dict 列表。"""
    ts, data = _cache["orders"]
    if time.time() - ts < _CACHE_TTL:
        return data
    ex = _get_exchange()
    if ex is None:
        return []
    try:
        ex.options["warnOnFetchOpenOrdersWithoutSymbol"] = False
        data = ex.fetch_open_orders()
        _cache["orders"] = (time.time(), data)
        return data
    except Exception as exc:
        logger.warning("fetch_open_orders 失败: %s", exc)
        return _cache["orders"][1]
