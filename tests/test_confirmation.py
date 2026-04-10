import pandas as pd
import numpy as np
from scanner.confirmation import (
    compute_rsi,
    compute_obv_trend,
    compute_up_down_volume_ratio,
    compute_mfi,
    confirm_signal,
    ConfirmationResult,
    compute_price_momentum,
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
    result = confirm_signal(df, "long", min_pass=4)
    assert result.passed is True
    assert result.passed_count >= 3


def test_confirm_long_fail_obv_and_volume():
    """持续下跌放量 -> OBV 净流出、量比偏空 -> 做多确认不通过。"""
    # 持续下跌：近7日全部阴线，OBV 必然为负，量比 < 1
    prices = [20 - i * 0.3 for i in range(20)] + [14 - i * 0.2 for i in range(10)]
    vols = [200.0] * 20 + [500.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.passed is False
    assert result.obv_ok is False


def test_confirm_short_pass():
    """顶部反转：OBV 流出、空头量比 -> 做空确认通过。"""
    # 先涨后跌，但幅度温和，确保 RSI 落在 30-70、MFI 在 20-80
    prices = [10 + i * 0.2 for i in range(20)] + [14 - i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "short", min_pass=4)
    assert result.passed is True


from scanner.confirmation import compute_volume_surge


def test_volume_surge_detects_increase():
    """近3日均量是前7日的2倍 -> surge = 2.0。"""
    volumes = pd.Series([100.0] * 7 + [200.0] * 3)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert abs(surge - 2.0) < 0.01


def test_volume_surge_no_change():
    """均匀量能 -> surge ≈ 1.0。"""
    volumes = pd.Series([100.0] * 10)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert abs(surge - 1.0) < 0.01


def test_volume_surge_insufficient_data():
    """数据不足 -> 返回 1.0。"""
    volumes = pd.Series([100.0] * 5)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    assert surge == 1.0


from scanner.confirmation import compute_atr_accel


def test_atr_accel_expanding_volatility():
    """近期波幅扩大 -> accel > 1.0。"""
    n = 22  # 7 recent + 14 baseline + 1 for shift
    # 前14日：窄幅波动
    highs = [10.5] * 15 + [12.0] * 7
    lows = [9.5] * 15 + [8.0] * 7
    closes = [10.0] * 15 + [10.0] * 7
    accel = compute_atr_accel(
        pd.Series(highs), pd.Series(lows), pd.Series(closes),
        recent_days=7, baseline_days=14,
    )
    assert accel > 1.0


def test_atr_accel_stable():
    """波幅不变 -> accel ≈ 1.0。"""
    n = 22
    highs = pd.Series([10.5] * n)
    lows = pd.Series([9.5] * n)
    closes = pd.Series([10.0] * n)
    accel = compute_atr_accel(highs, lows, closes, recent_days=7, baseline_days=14)
    assert abs(accel - 1.0) < 0.1


def test_atr_accel_insufficient_data():
    """数据不足 -> 返回 1.0。"""
    accel = compute_atr_accel(
        pd.Series([10.5] * 5), pd.Series([9.5] * 5), pd.Series([10.0] * 5),
        recent_days=7, baseline_days=14,
    )
    assert accel == 1.0


def test_confirm_signal_returns_score_and_bonus():
    """confirm_signal 应返回 score 和 bonus 字段。"""
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert hasattr(result, "score")
    assert hasattr(result, "bonus")
    assert 0.0 <= result.score <= 1.0
    assert -0.10 <= result.bonus <= 0.10


def test_confirm_signal_high_score_positive_bonus():
    """强确认信号（放量反弹）应给正加分。"""
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [100.0] * 20 + [500.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.score > 0.5
    assert result.bonus > 0


def test_confirm_signal_weak_gives_negative_bonus():
    """弱确认（持续下跌缩量）应给负加分。"""
    prices = [20 - i * 0.3 for i in range(20)] + [14 - i * 0.2 for i in range(10)]
    vols = [500.0] * 20 + [50.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.bonus < 0


def test_confirm_signal_has_surge_and_atr_fields():
    """结果应包含 volume_surge_ok 和 atr_accel_ok 字段。"""
    prices = [20 - i * 0.2 for i in range(20)] + [16 + i * 0.15 for i in range(10)]
    vols = [200.0] * 20 + [400.0] * 10
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert hasattr(result, "volume_surge_ok")
    assert hasattr(result, "atr_accel_ok")
    assert "volume_surge" in result.details
    assert "atr_accel" in result.details


def test_price_momentum_uptrend():
    """近5日上涨 -> 正收益率。"""
    closes = pd.Series([10.0, 10.5, 11.0, 11.5, 12.0, 12.5])
    mom = compute_price_momentum(closes, days=5)
    assert mom > 0.2


def test_price_momentum_downtrend():
    """近5日下跌 -> 负收益率。"""
    closes = pd.Series([12.0, 11.5, 11.0, 10.5, 10.0, 9.5])
    mom = compute_price_momentum(closes, days=5)
    assert mom < -0.1


def test_price_momentum_insufficient_data():
    """数据不足 -> 返回 0.0。"""
    closes = pd.Series([10.0, 11.0])
    mom = compute_price_momentum(closes, days=5)
    assert mom == 0.0


def test_confirm_signal_filters_declining_coin():
    """持续下跌的币（类似FIDA冲高回落）应被动量指标惩罚。"""
    # 先拉升后连续7天下跌
    prices = [10.0 + i * 0.5 for i in range(15)] + [17.5 - i * 0.3 for i in range(15)]
    vols = [500.0] * 15 + [100.0] * 15
    df = _make_df(prices, vols)
    result = confirm_signal(df, "long", min_pass=4)
    assert result.momentum_ok is False
    assert result.details["momentum_5d"] < -0.05
