import time

import ccxt
import pandas as pd


_exchange = None
_okx = None


def _get_exchange(proxy: str = "") -> ccxt.binance:
    global _exchange
    if _exchange is None:
        config = {"enableRateLimit": True, "timeout": 30000}
        if proxy:
            config["proxies"] = {"https": proxy, "http": proxy}
        _exchange = ccxt.binance(config)
    return _exchange


def _get_okx(proxy: str = "") -> ccxt.okx:
    global _okx
    if _okx is None:
        config = {"enableRateLimit": True, "timeout": 30000}
        if proxy:
            config["proxies"] = {"https": proxy, "http": proxy}
        _okx = ccxt.okx(config)
    return _okx


def set_proxy(proxy: str):
    global _exchange, _okx
    _exchange = None
    _okx = None
    _get_exchange(proxy)
    _get_okx(proxy)


def fetch_futures_symbols() -> list[str]:
    """获取OKX支持USDT永续合约、且Binance有现货的交易对列表"""
    okx = _get_okx()
    okx.load_markets()
    # OKX 合约符号
    okx_bases = set()
    for symbol, market in okx.markets.items():
        if market.get("swap") and market.get("active") and market.get("quote") == "USDT":
            okx_bases.add(market.get("base", ""))

    # Binance 现货确认（K线从Binance拉）
    exchange = _get_exchange()
    exchange.load_markets()
    result = []
    for base in sorted(okx_bases):
        spot = f"{base}/USDT"
        if spot in exchange.markets:
            result.append(spot)
    return result


def fetch_klines(symbol: str, days: int = 30) -> pd.DataFrame | None:
    """从Binance拉取日K线数据。"""
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
    # 丢弃当天未收盘的K线，避免实时数据波动影响检测结果
    today = pd.Timestamp.utcnow().normalize().tz_localize(None)
    df = df[df["timestamp"] < today].reset_index(drop=True)
    return df if len(df) > 0 else None


def fetch_klines_batch(symbols: list[str], days: int = 30, delay: float = 0.5) -> dict[str, pd.DataFrame]:
    """批量拉取多个交易对的K线。"""
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
