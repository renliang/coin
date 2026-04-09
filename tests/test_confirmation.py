import pandas as pd
import numpy as np
from scanner.confirmation import (
    compute_rsi,
    compute_obv_trend,
    compute_up_down_volume_ratio,
    compute_mfi,
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
