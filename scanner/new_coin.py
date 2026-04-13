"""新币观察清单：Binance U 本位永续 universe ∩ Binance 现货，按上架时间与流动性筛选。

数据源边界（与全市场 CoinGecko 翻页流分离）：
- **上架时间**：以 Binance 现货首根日 K 时间戳为准（`fetch_ohlcv` 自 2017 起取最早一根）。
- **24h 成交额**：Binance `fetch_ticker` 的 `quoteVolume`（USDT）。
- **7 日均额**：仅在做门槛或输出列时需要时，对少量结果用日 K 计算 sum(close*volume)。
- **L1 市值**：可选 `fetch_market_caps`（与 `scanner/coingecko.py` 同源），不调用 `fetch_small_cap_coins`。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import ccxt
import pandas as pd

from scanner.coingecko import fetch_market_caps
from scanner.kline import _get_exchange, fetch_futures_symbols, fetch_klines


STABLE_BASES_DEFAULT = frozenset({
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD", "USDP", "GUSD", "USDD",
})

_LEVERAGE_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
_LEVERAGE_MARKERS = ("3L", "3S", "2L", "2S", "4L", "4S", "5L", "5S")

NEW_LISTINGS_SCHEMA_VERSION = 1


def build_new_listings_payload(
    rows: list[dict],
    *,
    collected_at: datetime | None = None,
) -> dict:
    """与 `results/new_listings_*.json` 根结构一致，便于测试与下游解析。"""
    ts = collected_at if collected_at is not None else datetime.now(timezone.utc)
    return {
        "meta": {
            "collected_at": ts.isoformat(),
            "schema_version": NEW_LISTINGS_SCHEMA_VERSION,
            "mode": "new_listings",
            "result_count": len(rows),
        },
        "rows": rows,
    }


@dataclass
class NewCoinConfig:
    max_listing_days: int = 30
    min_quote_volume_24h: float = 500_000.0
    min_avg_volume_7d_quote: float = 0.0  # 0 = 不做该门槛
    exclude_leverage_tokens: bool = True
    exclude_stable_bases: bool = True
    stable_bases: frozenset[str] = field(default_factory=lambda: STABLE_BASES_DEFAULT)
    max_market_cap_usd: float = 0.0  # 0 = 不做市值上限
    sort_by: str = "listing_age_asc"  # listing_age_asc | volume_24h_desc
    top_n: int = 50
    enrich_market_cap: bool = True
    enrich_avg_volume_7d: bool = True
    coingecko_page_delay: float = 8.0
    request_delay: float = 0.08

    @classmethod
    def from_mapping(cls, d: dict | None) -> NewCoinConfig:
        if not d:
            return cls()
        stable = d.get("stable_bases")
        st = frozenset(s.upper() for s in stable) if stable else STABLE_BASES_DEFAULT
        return cls(
            max_listing_days=int(d.get("max_listing_days", 30)),
            min_quote_volume_24h=float(d.get("min_quote_volume_24h", 500_000)),
            min_avg_volume_7d_quote=float(
                d.get("min_avg_volume_7d", d.get("min_avg_volume_7d_quote", 0)),
            ),
            exclude_leverage_tokens=bool(d.get("exclude_leverage_tokens", True)),
            exclude_stable_bases=bool(d.get("exclude_stable_bases", True)),
            stable_bases=st,
            max_market_cap_usd=float(d.get("max_market_cap_usd", 0)),
            sort_by=str(d.get("sort_by", "listing_age_asc")),
            top_n=int(d.get("top_n", 50)),
            enrich_market_cap=bool(d.get("enrich_market_cap", True)),
            enrich_avg_volume_7d=bool(d.get("enrich_avg_volume_7d", True)),
            coingecko_page_delay=float(d.get("coingecko_page_delay", 8.0)),
            request_delay=float(d.get("request_delay", d.get("ticker_delay", 0.08))),
        )


def is_leverage_like_base(base: str) -> bool:
    u = base.upper()
    for suf in _LEVERAGE_SUFFIXES:
        if u.endswith(suf) and len(u) > len(suf):
            return True
    for m in _LEVERAGE_MARKERS:
        if m in u:
            return True
    return False


def should_exclude_base(base: str, cfg: NewCoinConfig) -> bool:
    if cfg.exclude_stable_bases and base.upper() in cfg.stable_bases:
        return True
    if cfg.exclude_leverage_tokens and is_leverage_like_base(base):
        return True
    return False


def fetch_first_listing_ms(exchange: ccxt.Exchange, symbol: str) -> int | None:
    """取 Binance 现货该交易对首根日 K 的时间戳 (ms)。"""
    try:
        since = exchange.parse8601("2017-01-01T00:00:00Z")
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=1)
        if ohlcv:
            return int(ohlcv[0][0])
    except (ccxt.BadSymbol, ccxt.ExchangeError, ccxt.NetworkError, ccxt.RequestTimeout):
        return None
    return None


def listing_age_days(first_listing_ms: int, now_ms: int | None = None) -> int:
    if now_ms is None:
        now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
    return max(0, (now_ms - first_listing_ms) // (24 * 60 * 60 * 1000))


def compute_avg_quote_volume_7d(symbol: str) -> float | None:
    df = fetch_klines(symbol, days=14)
    if df is None or len(df) < 7:
        return None
    tail = df.tail(7)
    return float((tail["close"].astype(float) * tail["volume"].astype(float)).sum())


def screen_new_listings(cfg: NewCoinConfig) -> list[dict]:
    """构建新币观察清单（不跑蓄力/背离）。"""
    exchange = _get_exchange()
    exchange.load_markets()
    symbols = fetch_futures_symbols()
    now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)
    dly = cfg.request_delay

    rows: list[dict] = []
    total = len(symbols)
    for i, symbol in enumerate(symbols, 1):
        if i % 100 == 1 or i == total:
            print(f"       新币筛选进度: {i}/{total}，已累计候选 {len(rows)}")

        base = symbol.split("/")[0]
        if should_exclude_base(base, cfg):
            continue

        first_ms = fetch_first_listing_ms(exchange, symbol)
        time.sleep(dly)
        if first_ms is None:
            continue

        age = listing_age_days(first_ms, now_ms)
        if age > cfg.max_listing_days:
            continue

        try:
            ticker = exchange.fetch_ticker(symbol)
        except (ccxt.ExchangeError, ccxt.NetworkError, ccxt.RequestTimeout):
            continue
        finally:
            time.sleep(dly)

        qv = float(ticker.get("quoteVolume") or 0.0)
        if qv < cfg.min_quote_volume_24h:
            continue

        avg7: float | None = None
        if cfg.min_avg_volume_7d_quote > 0:
            avg7 = compute_avg_quote_volume_7d(symbol)
            time.sleep(dly)
            if avg7 is None or avg7 < cfg.min_avg_volume_7d_quote:
                continue

        last = float(ticker.get("last") or ticker.get("close") or 0.0)
        pct = ticker.get("percentage")
        change_pct = float(pct) / 100.0 if pct is not None else None

        rows.append({
            "symbol": symbol,
            "base": base,
            "listing_first_ts_ms": first_ms,
            "listing_days": age,
            "price": last,
            "quote_volume_24h": qv,
            "avg_quote_volume_7d": avg7,
            "change_24h_pct": change_pct,
            "coingecko_search_url": f"https://www.coingecko.com/en/search?query={base}",
            "binance_spot_url": f"https://www.binance.com/en/trade/{base}_USDT",
            "market_cap_usd": 0.0,
        })

    if cfg.sort_by == "volume_24h_desc":
        rows.sort(key=lambda r: r["quote_volume_24h"], reverse=True)
    else:
        rows.sort(key=lambda r: (r["listing_days"], -r["quote_volume_24h"]))

    if cfg.max_market_cap_usd > 0 and rows:
        mc_limit = cfg.max_market_cap_usd
        caps_all = fetch_market_caps(
            [r["base"] for r in rows],
            page_delay=cfg.coingecko_page_delay,
        )
        rows = [
            r for r in rows
            if 0 < caps_all.get(r["base"].upper(), 0.0) <= mc_limit
        ]

    trimmed = rows[: cfg.top_n]

    if cfg.enrich_market_cap and trimmed:
        caps = fetch_market_caps(
            [r["base"] for r in trimmed],
            page_delay=cfg.coingecko_page_delay,
        )
        for r in trimmed:
            r["market_cap_usd"] = float(caps.get(r["base"].upper(), 0.0))

    if cfg.enrich_avg_volume_7d and trimmed:
        for r in trimmed:
            if r.get("avg_quote_volume_7d") is None:
                r["avg_quote_volume_7d"] = compute_avg_quote_volume_7d(r["symbol"])
                time.sleep(dly)

    return trimmed
