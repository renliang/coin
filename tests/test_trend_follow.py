"""趋势跟踪基础工具测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.trend_follow import atr, donchian_high, donchian_low, is_above_ema


def _klines(closes: list[float], highs: list[float] | None = None,
            lows: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    highs = highs if highs is not None else [c * 1.01 for c in closes]
    lows = lows if lows is not None else [c * 0.99 for c in closes]
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=n, freq="D"),
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_donchian_high_returns_max_close_in_window():
    closes = [1, 2, 3, 4, 5, 4, 3]
    df = _klines(closes)
    # 过去 5 天 (含当前) 最高 = max(1,2,3,4,5)=5
    assert donchian_high(df["close"], 5, up_to=4) == 5
    # 过去 3 天收盘 max(3,4,5)=5
    assert donchian_high(df["close"], 3, up_to=4) == 5


def test_donchian_low_returns_min_close_in_window():
    closes = [10, 8, 6, 4, 2, 4, 6]
    df = _klines(closes)
    assert donchian_low(df["close"], 5, up_to=4) == 2
    assert donchian_low(df["close"], 3, up_to=4) == 2


def test_donchian_excludes_current_bar_when_requested():
    """判断突破时需要用 "过去 N 日" 不含今日, 所以 exclude_current=True。"""
    closes = [1, 2, 3, 4, 100]  # 今天 100 是新高
    df = _klines(closes)
    # 不含今日, 过去 4 日 max=4
    assert donchian_high(df["close"], 4, up_to=4, exclude_current=True) == 4


def test_atr_is_positive():
    closes = np.linspace(100, 200, 30).tolist()
    df = _klines(closes)
    a = atr(df, period=14)
    assert a > 0


def test_atr_zero_for_flat_prices():
    df = _klines([100.0] * 30, highs=[100.0] * 30, lows=[100.0] * 30)
    a = atr(df, period=14)
    assert a == pytest.approx(0.0, abs=1e-9)


def test_is_above_ema_true_when_close_exceeds_ma():
    closes = np.linspace(50, 200, 250).tolist()  # 持续上涨
    df = _klines(closes)
    # 末尾 close 远大于 200EMA
    assert is_above_ema(df["close"], 200) is True


def test_is_above_ema_false_when_below():
    closes = np.linspace(200, 50, 250).tolist()  # 持续下跌
    df = _klines(closes)
    assert is_above_ema(df["close"], 200) is False


def test_is_above_ema_handles_insufficient_data():
    df = _klines([100.0] * 30)
    # 数据不足 200 根 → 返回 False (保守, 不入场)
    assert is_above_ema(df["close"], 200) is False
