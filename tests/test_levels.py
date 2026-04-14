import pandas as pd
import pytest
from scanner.levels import find_pivot_lows, find_pivot_highs, nearest_support, nearest_resistance


def _make_df(lows: list[float], highs: list[float] | None = None) -> pd.DataFrame:
    if highs is None:
        highs = [l + 5.0 for l in lows]
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": lows,
        "close": closes, "volume": [1000.0] * len(lows),
    })


def test_pivot_lows_insufficient_data():
    """数据不足 left+right+1=11 行时返回空列表，不抛异常。"""
    df = _make_df([100.0] * 10)
    assert find_pivot_lows(df, left=5, right=5) == []


def test_pivot_highs_insufficient_data():
    df = _make_df([100.0] * 10)
    assert find_pivot_highs(df, left=5, right=5) == []


def test_find_pivot_lows_v_shape():
    """V 形 df：底部 index=10 应被识别为支撑位。"""
    # lows[i] = 80 + abs(i - 10) * 2，lows[10]=80 是最小值
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    result = find_pivot_lows(df, left=5, right=5)
    assert 80.0 in result


def test_find_pivot_highs_inverted_v():
    """倒 V 形 df：顶部 index=12 应被识别为阻力位。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    result = find_pivot_highs(df, left=5, right=5)
    assert 105.0 in result


def test_nearest_support_within_max_dist():
    """支撑在 max_dist 以内时能找到。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    # 82 * (1-0.05) = 77.9，支撑 80 在范围内 (82-80)/82 ≈ 2.4%
    result = nearest_support(df, price=82.0, max_dist=0.05)
    assert result == 80.0


def test_nearest_support_outside_max_dist_returns_none():
    """支撑超出 max_dist 时返回 None。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    # price=100, support=80, dist=20% > 5%
    result = nearest_support(df, price=100.0, max_dist=0.05)
    assert result is None


def test_nearest_resistance_found():
    """阻力位在 price 上方时能找到。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    result = nearest_resistance(df, price=96.0)
    assert result == 105.0


def test_nearest_resistance_with_max_dist_filters():
    """阻力位超出 max_dist 时返回 None。"""
    n = 25
    highs = [100.0 + 5.0 - abs(i - 12) * 2.0 for i in range(n)]
    lows = [h - 3.0 for h in highs]
    df = _make_df(lows, highs)
    # price=100, resistance=105, dist=5% == max_dist=0.05 → 应找到（≤）
    result = nearest_resistance(df, price=100.0, max_dist=0.05)
    assert result == 105.0
    # price=101, dist=(105-101)/101 ≈ 3.96% > 3% → None
    result2 = nearest_resistance(df, price=101.0, max_dist=0.03)
    assert result2 is None


def test_no_support_below_price():
    """价格低于所有 Pivot 低点时返回 None。"""
    n = 25
    lows = [80.0 + abs(i - 10) * 2.0 for i in range(n)]
    df = _make_df(lows)
    result = nearest_support(df, price=70.0, max_dist=0.05)
    assert result is None
