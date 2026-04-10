import pandas as pd
import numpy as np
from scanner.breakout import detect_breakout, BreakoutResult, _score_breakout


def _make_klines(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    n = len(prices)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes,
    })


# --- detect_breakout tests ---

def test_no_spike_returns_unmatched():
    """均匀量能无天量 -> 不命中。"""
    prices = [10.0 + i * 0.1 for i in range(30)]
    volumes = [1000.0] * 30
    df = _make_klines(prices, volumes)
    result = detect_breakout(df)
    assert result.matched is False
    assert result.score == 0.0


def _make_ong_like_data() -> pd.DataFrame:
    """模拟 ONG 模式：20日平盘 -> 天量拉升 -> 5日缩量回调 -> 放量二攻。"""
    base_prices = [10.0] * 20
    base_volumes = [100.0] * 20
    spike_prices = [15.0]
    spike_volumes = [1100.0]
    pullback_prices = [14.0, 13.5, 13.0, 12.5, 12.0]
    pullback_volumes = [50.0, 30.0, 20.0, 25.0, 20.0]
    reattack_prices = [13.5]
    reattack_volumes = [80.0]
    prices = base_prices + spike_prices + pullback_prices + reattack_prices
    volumes = base_volumes + spike_volumes + pullback_volumes + reattack_volumes
    return _make_klines(prices, volumes)


def test_ong_like_pattern_matches():
    """ONG 模式应命中。"""
    df = _make_ong_like_data()
    result = detect_breakout(df, freshness_days=5)
    assert result.matched is True
    assert result.spike_volume_ratio >= 10.0
    assert result.pullback_shrink < 0.3
    assert result.reattack_volume_ratio >= 2.0
    assert result.score > 0.5


def test_no_reattack_returns_unmatched():
    """天量后缩量但无二攻 -> 不命中（类似 FIDA）。"""
    base_prices = [10.0] * 20
    base_volumes = [100.0] * 20
    spike_prices = [15.0]
    spike_volumes = [1100.0]
    pullback_prices = [14.0, 13.5, 13.0, 12.5, 12.0, 11.8, 11.5, 11.3]
    pullback_volumes = [50.0, 30.0, 20.0, 15.0, 12.0, 10.0, 10.0, 10.0]
    prices = base_prices + spike_prices + pullback_prices
    volumes = base_volumes + spike_volumes + pullback_volumes
    df = _make_klines(prices, volumes)
    result = detect_breakout(df, freshness_days=5)
    assert result.matched is False


def test_stale_reattack_returns_unmatched():
    """二攻日太旧 -> 不命中。"""
    df = _make_ong_like_data()
    extra_prices = [13.5] * 5
    extra_volumes = [20.0] * 5
    prices = [float(df["close"].iloc[i]) for i in range(len(df))] + extra_prices
    volumes = [float(df["volume"].iloc[i]) for i in range(len(df))] + extra_volumes
    df2 = _make_klines(prices, volumes)
    result = detect_breakout(df2, freshness_days=3)
    assert result.matched is False


def test_insufficient_data():
    """数据不足 -> 不命中。"""
    df = _make_klines([10.0] * 10, [100.0] * 10)
    result = detect_breakout(df)
    assert result.matched is False


# --- _score_breakout tests ---

def test_score_strong_breakout():
    """强势模式应高分。"""
    score = _score_breakout(
        spike_vol_ratio=20.0,
        pullback_shrink=0.05,
        reattack_vol_ratio=8.0,
        reattack_close=14.0,
        spike_high=15.0,
    )
    assert score > 0.7


def test_score_weak_breakout():
    """弱模式应低分。"""
    score = _score_breakout(
        spike_vol_ratio=5.0,
        pullback_shrink=0.45,
        reattack_vol_ratio=2.0,
        reattack_close=10.0,
        spike_high=15.0,
    )
    assert score < 0.4


def test_score_range():
    """评分应在 [0, 1]。"""
    for svr in [5, 10, 50, 100]:
        for ps in [0.01, 0.1, 0.3, 0.5]:
            for rvr in [2, 5, 10]:
                score = _score_breakout(svr, ps, rvr, 12.0, 15.0)
                assert 0.0 <= score <= 1.0
