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


def _leverage_map(exchange) -> dict[str, int]:
    """通过 fapiPrivateV2GetPositionRisk 拿每个 symbol 的当前杠杆（ccxt fetch_positions
    在新版币安 API 上不返回 leverage）。key 是无分隔符形式，如 "ONGUSDT"。"""
    try:
        risks = exchange.fapiPrivateV2GetPositionRisk()
        return {r["symbol"]: int(float(r.get("leverage") or 1)) for r in risks}
    except Exception as exc:
        logger.warning("fetch positionRisk 失败: %s", exc)
        return {}


def _attach_leverage(positions: list[dict], lev_map: dict[str, int]) -> None:
    """把 leverage 合并到 fetch_positions 的原始条目里（原地修改）。"""
    for p in positions:
        sym = (p.get("symbol") or "").replace("/", "").replace(":USDT", "")
        if sym in lev_map:
            p["leverage"] = lev_map[sym]


def fetch_exchange_positions() -> list[dict]:
    """查交易所实时持仓，返回原始 ccxt dict 列表（已过滤 contracts>0，合并了正确 leverage）。"""
    ts, data = _cache["positions"]
    if time.time() - ts < _CACHE_TTL:
        return data
    ex = _get_exchange()
    if ex is None:
        return []
    try:
        raw = ex.fetch_positions()
        data = [p for p in raw if float(p.get("contracts", 0) or 0) > 0]
        _attach_leverage(data, _leverage_map(ex))
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
