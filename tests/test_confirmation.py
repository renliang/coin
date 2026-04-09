import pandas as pd
import numpy as np
from scanner.confirmation import (
    compute_rsi,
    compute_obv_trend,
    compute_up_down_volume_ratio,
    compute_mfi,
    confirm_signal,
    ConfirmationResult,
)


# --- RSI tests ---

def test_compute_rsi_overbought():
    """连续上涨应产生高 RSI (>70)。"""
    prices = [10 + i * 0.5 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert rsi > 70


def test_compute_rsi_oversold():
    """连续下跌应产生低 RSI (<30)。"""
    prices = [30 - i * 0.5 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert rsi < 30


def test_compute_rsi_neutral():
    """震荡行情 RSI 应在 30-70 之间。"""
    prices = [10 + (i % 3 - 1) * 0.2 for i in range(30)]
    closes = pd.Series(prices)
    rsi = compute_rsi(closes, period=14)
    assert 30 <= rsi <= 70


# --- OBV tests ---

def test_obv_trend_positive():
    """上涨日多于下跌日时，近7日 OBV 变化应为正。"""
    closes = pd.Series([10.0, 11, 12, 11.5, 12.5, 13, 14, 13.5, 14.5, 15])
    volumes = pd.Series([100.0] * 10)
    trend = compute_obv_trend(closes, volumes, days=7)
    assert trend > 0


def test_obv_trend_negative():
    """下跌日多于上涨日时，近7日 OBV 变化应为负。"""
    closes = pd.Series([15.0, 14, 13, 13.5, 12.5, 12, 11, 11.5, 10.5, 10])
    volumes = pd.Series([100.0] * 10)
    trend = compute_obv_trend(closes, volumes, days=7)
    assert trend < 0


# --- Volume ratio tests ---

def test_volume_ratio_bull_dominant():
    """上涨日放量、下跌日缩量，量比应 > 1.5。"""
    closes = pd.Series([10.0, 11, 10.5, 12, 11.8, 13, 12.5, 14])
    volumes = pd.Series([100.0, 500, 100, 500, 100, 500, 100, 500])
    ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    assert ratio > 1.5


def test_volume_ratio_bear_dominant():
    """下跌日放量、上涨日缩量，量比应 < 0.7。"""
    closes = pd.Series([14.0, 13, 13.5, 12, 12.2, 11, 11.5, 10])
    volumes = pd.Series([100.0, 500, 100, 500, 100, 500, 100, 500])
    ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    assert ratio < 0.7


def test_volume_ratio_no_down_days():
    """全部上涨日，量比应为 inf。"""
    closes = pd.Series([10.0, 11, 12, 13, 14])
    volumes = pd.Series([100.0] * 5)
    ratio = compute_up_down_volume_ratio(closes, volumes, days=4)
    assert ratio == float("inf")


# --- MFI tests ---

def test_mfi_range():
    """MFI 应在 0-100 之间。"""
    n = 30
    highs = pd.Series([10 + i * 0.3 + 0.5 for i in range(n)])
    lows = pd.Series([10 + i * 0.3 - 0.5 for i in range(n)])
    closes = pd.Series([10 + i * 0.3 for i in range(n)])
    volumes = pd.Series([1000.0] * n)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    assert 0 <= mfi <= 100


def test_mfi_high_on_rally():
    """持续上涨+放量时 MFI 应偏高 (>50)。"""
    n = 30
    highs = pd.Series([10 + i * 0.5 + 0.2 for i in range(n)])
    lows = pd.Series([10 + i * 0.5 - 0.1 for i in range(n)])
    closes = pd.Series([10 + i * 0.5 for i in range(n)])
    volumes = pd.Series([1000.0 + i * 100 for i in range(n)])
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    assert mfi > 50


# --- confirm_signal tests ---


def _make_df(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造含 OHLCV 的 DataFrame。"""
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


def test_confirm_long_all_pass():
    """健康的底部反弹：RSI 适中、OBV 流入、多头量比、MFI 正常 -> 通过。"""
    # 先跌后涨，但幅度温和，确保 RSI 落在 30-70、MFI 在 20-80
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=3)
    assert result.passed is True
    assert result.passed_count >= 3


def test_confirm_long_fail_obv_and_volume():
    """持续下跌放量 -> OBV 净流出、量比偏空 -> 做多确认不通过。"""
    # 持续下跌：近7日全部阴线，OBV 必然为负，量比 < 1
    prices = [20 - i * 0.3 for i in range(20)] + [14 - i * 0.2 for i in range(10)]
    vols = [200.0] * 20 + [500.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=3)
    assert result.passed is False
    assert result.obv_ok is False


def test_confirm_short_pass():
    """顶部反转：OBV 流出、空头量比 -> 做空确认通过。"""
    # 先涨后跌，但幅度温和，确保 RSI 落在 30-70、MFI 在 20-80
    prices = [10 + i * 0.2 for i in range(20)] + [14 - i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "short", min_pass=3)
    assert result.passed is True
