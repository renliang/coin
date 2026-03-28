import time

import ccxt
import pandas as pd


def fetch_klines(symbol: str, days: int = 30) -> pd.DataFrame | None:
    """从Binance拉取日K线数据。

    Args:
        symbol: 交易对，如 "BTC/USDT"
        days: 拉取天数

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        如果交易对不存在返回None
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    try:
        since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=days)
    except ccxt.BadSymbol:
        return None
    except ccxt.ExchangeError:
        return None
    finally:
        exchange.close()

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
    for symbol in symbols:
        df = fetch_klines(symbol, days)
        if df is not None and len(df) >= 7:
            results[symbol] = df
        time.sleep(delay)
    return results
