import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import ccxt
import pandas as pd

logger = logging.getLogger(__name__)

_exchange = None
_usdm = None
_authed_usdm = None


def _get_exchange(proxy: str = "") -> ccxt.binance:
    global _exchange
    if _exchange is None:
        config = {"enableRateLimit": True, "timeout": 30000}
        if proxy:
            config["httpsProxy"] = proxy
        _exchange = ccxt.binance(config)
    return _exchange


def _get_binance_usdm(proxy: str = "") -> ccxt.binanceusdm:
    global _usdm
    if _usdm is None:
        config = {"enableRateLimit": True, "timeout": 30000}
        if proxy:
            config["httpsProxy"] = proxy
        _usdm = ccxt.binanceusdm(config)
    return _usdm


def get_authed_usdm(api_key: str, api_secret: str, proxy: str = "") -> ccxt.binanceusdm:
    """创建带 API Key 认证的币安 USDM 永续合约实例，用于下单。"""
    global _authed_usdm
    if _authed_usdm is None:
        config = {
            "apiKey": api_key,
            "secret": api_secret,
            "enableRateLimit": True,
            "timeout": 30000,
            "options": {"defaultType": "swap"},
        }
        if proxy:
            config["httpsProxy"] = proxy
        _authed_usdm = ccxt.binanceusdm(config)
    return _authed_usdm


def set_proxy(proxy: str):
    global _exchange, _usdm, _authed_usdm
    _exchange = None
    _usdm = None
    _authed_usdm = None
    _get_exchange(proxy)
    _get_binance_usdm(proxy)


def fetch_futures_symbols() -> list[str]:
    """获取 Binance U 本位 USDT 永续的 base，且存在 Binance 现货 BASE/USDT 的交易对列表。

    K 线/现货行情仍走 Binance 现货（与蓄力/背离/回测一致）。
    """
    usdm = _get_binance_usdm()
    usdm.load_markets()
    bases: set[str] = set()
    for market in usdm.markets.values():
        if market.get("swap") and market.get("active") and market.get("quote") == "USDT":
            b = market.get("base") or ""
            if b:
                bases.add(b)

    exchange = _get_exchange()
    exchange.load_markets()
    result = []
    for base in sorted(bases):
        spot = f"{base}/USDT"
        if spot in exchange.markets:
            result.append(spot)
    return result


def fetch_klines(symbol: str, days: int = 30, use_futures: bool = True) -> pd.DataFrame | None:
    """从Binance拉取日K线数据。默认用合约K线（与交易标的一致）。"""
    exchange = _get_binance_usdm() if use_futures else _get_exchange()
    fetch_symbol = symbol
    if use_futures and not symbol.endswith(":USDT"):
        fetch_symbol = f"{symbol}:USDT"
    try:
        since = exchange.milliseconds() - days * 24 * 60 * 60 * 1000
        ohlcv = exchange.fetch_ohlcv(fetch_symbol, timeframe="1d", since=since, limit=days)
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


def fetch_klines_batch(
    symbols: list[str],
    days: int = 30,
    delay: float = 0.0,
    workers: int = 10,
) -> dict[str, pd.DataFrame]:
    """批量拉取多个交易对的K线。

    - workers > 1: 使用 ThreadPoolExecutor 并发（推荐，ccxt 的 enableRateLimit 会自动限速）。
    - workers <= 1: 串行降级，按 delay 秒间隔。

    Binance USDM fetch_ohlcv weight=5，限额 2400 weight/min ≈ 480 req/min，
    默认 10 并发远在安全线以内。
    """
    total = len(symbols)
    if total == 0:
        return {}

    results: dict[str, pd.DataFrame] = {}

    if workers <= 1:
        for i, symbol in enumerate(symbols, 1):
            if i % 50 == 1 or i == total:
                logger.info("K线拉取进度: %d/%d，已获取%d个", i, total, len(results))
            df = fetch_klines(symbol, days)
            if df is not None and len(df) >= 7:
                results[symbol] = df
            if delay > 0:
                time.sleep(delay)
        return results

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_klines, s, days): s for s in symbols}
        for fut in as_completed(futures):
            done += 1
            symbol = futures[fut]
            try:
                df = fut.result()
            except Exception as exc:
                logger.warning("fetch_klines %s failed: %s", symbol, exc)
                df = None
            if df is not None and len(df) >= 7:
                results[symbol] = df
            if done % 50 == 1 or done == total:
                logger.info("K线拉取进度: %d/%d，已获取%d个", done, total, len(results))
    return results


def fetch_ticker_price(symbol: str) -> float | None:
    """获取单个交易对的最新价格。失败返回 None。"""
    try:
        exchange = _get_exchange()
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"]) if ticker and ticker.get("last") else None
    except Exception as exc:
        logger.warning("fetch_ticker_price %s failed: %s", symbol, exc)
        return None
