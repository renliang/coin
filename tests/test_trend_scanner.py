"""趋势跟踪实时扫描测试 — 基于最后一根 K 线判定今日入场信号。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.trend_scanner import TrendEntrySignal, scan_trend_entries


def _klines(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def _btc_bullish_df(n: int = 300) -> pd.DataFrame:
    return _klines(np.linspace(20000.0, 60000.0, n).tolist())


def _btc_bearish_df(n: int = 300) -> pd.DataFrame:
    return _klines(np.linspace(60000.0, 20000.0, n).tolist())


def test_detects_breakout_signal_when_all_conditions_met():
    """单币 close 破 30 日新高 + 自身 EMA200 上方 + BTC 强势 → 出 entry 信号。"""
    # 前 300 天低位徘徊 50-60, 最后一天冲到 80（破 30 日新高）
    closes = [50.0 + np.sin(i / 10) * 5 for i in range(300)]
    closes.append(80.0)  # 突破
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(
        klines, btc_df=_btc_bullish_df(),
        entry_n=30, trend_ema=200, btc_trend_ema=100,
    )
    # 注意: 自身 EMA200 可能还在 55 附近, close=80 必然高于
    assert len(out) == 1
    sig = out[0]
    assert sig.symbol == "X/USDT"
    assert sig.entry_price == pytest.approx(80.0)
    assert sig.atr > 0
    assert sig.initial_stop_chandelier < sig.entry_price


def test_no_signal_when_btc_weak():
    """BTC EMA100 下方时, 就算单币破位也不出信号。"""
    closes = [50.0] * 300 + [80.0]
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(
        klines, btc_df=_btc_bearish_df(),
        entry_n=30, trend_ema=200, btc_trend_ema=100,
    )
    assert out == []


def test_no_signal_when_below_own_ema200():
    """单币自身 EMA200 下方 (熊市反弹) → 不出信号。"""
    # 前 250 天高位 200, 最后 50 天急跌到 30, 然后反弹到 55 (破 30 日新高但仍在 EMA200 下)
    down = np.linspace(200.0, 30.0, 280).tolist()
    rebound = [30.0 + i for i in range(25)]  # 30..54
    closes = down + rebound
    # 确认最后一天是 30 日新高
    last = closes[-1]
    prev_30_max = max(closes[-31:-1])
    assert last > prev_30_max
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(
        klines, btc_df=_btc_bullish_df(),
        entry_n=30, trend_ema=200, btc_trend_ema=100,
    )
    assert out == []


def test_no_signal_when_not_a_new_high():
    """close 未突破过去 30 日高点 → 不出信号。"""
    closes = np.linspace(10.0, 100.0, 300).tolist()
    # 最后一天收 99 (昨天已经 100 了, 不是新高)
    closes.append(99.0)
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(
        klines, btc_df=_btc_bullish_df(),
        entry_n=30, trend_ema=200, btc_trend_ema=100,
    )
    assert out == []


def test_signal_has_all_stop_fields():
    closes = [50.0] * 300 + [80.0]
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(klines, btc_df=_btc_bullish_df(),
                             entry_n=30, trend_ema=200, btc_trend_ema=100,
                             exit_n=15, chandelier_mult=3.0)
    sig = out[0]
    # chandelier = entry - 3 * atr
    assert sig.initial_stop_chandelier == pytest.approx(sig.entry_price - 3.0 * sig.atr, rel=1e-6)
    # donchian = 过去 15 天最低 close (不含今天)
    assert 0 < sig.initial_stop_donchian < sig.entry_price


def test_sorts_by_breakout_strength():
    """多个信号按"突破强度" (close / donchian_high - 1) 降序排列。"""
    # S1: 从 50 平盘到 80 (突破 60%)
    # S2: 从 50 平盘到 55 (突破 10%)
    s1 = [50.0] * 300 + [80.0]
    s2 = [50.0] * 300 + [55.0]
    klines = {"STRONG/USDT": _klines(s1), "WEAK/USDT": _klines(s2)}
    out = scan_trend_entries(klines, btc_df=_btc_bullish_df(),
                             entry_n=30, trend_ema=200, btc_trend_ema=100)
    assert [s.symbol for s in out] == ["STRONG/USDT", "WEAK/USDT"]


def test_skips_symbols_with_insufficient_data():
    short = [50.0] * 50 + [80.0]  # 51 天, 小于 EMA200 warmup
    long = [50.0] * 300 + [80.0]
    klines = {"SHORT/USDT": _klines(short), "LONG/USDT": _klines(long)}
    out = scan_trend_entries(klines, btc_df=_btc_bullish_df(),
                             entry_n=30, trend_ema=200, btc_trend_ema=100)
    symbols = [s.symbol for s in out]
    assert "SHORT/USDT" not in symbols
    assert "LONG/USDT" in symbols


def test_empty_input():
    assert scan_trend_entries({}, btc_df=_btc_bullish_df()) == []


def test_signal_is_frozen():
    closes = [50.0] * 300 + [80.0]
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_entries(klines, btc_df=_btc_bullish_df(),
                             entry_n=30, trend_ema=200, btc_trend_ema=100)
    with pytest.raises(Exception):
        out[0].symbol = "Y/USDT"  # type: ignore[misc]
