import time

import ccxt
import pandas as pd


# 模块级共享exchange实例，避免每次创建新连接
_exchange = None


def _get_exchange(proxy: str = "") -> ccxt.binance:
    global _exchange
    if _exchange is None:
        config = {"enableRateLimit": True, "timeout": 30000}
        if proxy:
            config["proxies"] = {"https": proxy, "http": proxy}
        _exchange = ccxt.binance(config)
    return _exchange


def set_proxy(proxy: str):
    """设置代理，需在fetch_klines前调用"""
    global _exchange
    _exchange = None
    _get_exchange(proxy)


def fetch_klines(symbol: str, days: int = 30) -> pd.DataFrame | None:
    """从Binance拉取日K线数据。

    Args:
        symbol: 交易对，如 "BTC/USDT"
        days: 拉取天数

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        如果交易对不存在返回None
    """
    exchange = _get_exchange()
    try:
        since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=days)
    except (ccxt.BadSymbol, ccxt.ExchangeError):
        return None
    except (ccxt.NetworkError, ccxt.RequestTimeout):
        return None

    if not ohlcv:
        return None

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_klines_batch(symbols: list[str], days: int = 30, delay: float = 0.5) -> dict[str, pd.DataFrame]:
    """批量拉取多个交易对的K线。

    Args:
        symbols: 交易对列表
        days: 拉取天数
        delay: 每次请求间隔秒数

    Returns:
        dict mapping symbol -> DataFrame (跳过失败的)
    """
    results = {}
    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        if i % 50 == 1 or i == total:
            print(f"       K线拉取进度: {i}/{total}，已获取{len(results)}个")
        df = fetch_klines(symbol, days)
        if df is not None and len(df) >= 7:
            results[symbol] = df
        time.sleep(delay)
    return results
