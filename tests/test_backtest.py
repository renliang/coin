import pandas as pd
import numpy as np
from scanner.backtest import run_backtest, BacktestHit, compute_stats


def _make_klines(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造合成K线DataFrame。"""
    n = len(prices)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": volumes,
    })


def test_run_backtest_detects_pattern():
    """构造一段明确的底部蓄力形态 + 后续上涨，验证能检测到并计算收益。"""
    n_pattern = 14
    n_future = 30
    pattern_prices = [100 - i * 0.7 for i in range(n_pattern)]
    pattern_volumes = [1000] * 7 + [300] * 7
    future_prices = [pattern_prices[-1] + i * 0.33 for i in range(1, n_future + 1)]
    future_volumes = [500] * n_future

    prices = pattern_prices + future_prices
    volumes = pattern_volumes + future_volumes
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"TEST/USDT": df}, config)

    assert len(hits) >= 1
    hit = hits[0]
    assert isinstance(hit, BacktestHit)
    assert hit.symbol == "TEST/USDT"
    assert hit.score > 0
    assert hit.returns["3d"] is not None
    assert hit.returns["3d"] > 0


def test_run_backtest_dedup_adjacent_hits():
    """连续命中的形态只保留第一次，间隔不足 window_max_days 的跳过。"""
    seg1_prices = [100 - i * 0.7 for i in range(14)]
    seg1_volumes = [1000] * 7 + [300] * 7
    gap_prices = [seg1_prices[-1]] * 5
    gap_volumes = [300] * 5
    seg2_start = gap_prices[-1]
    seg2_prices = [seg2_start - i * 0.7 for i in range(14)]
    seg2_volumes = [1000] * 7 + [300] * 7
    future_prices = [seg2_prices[-1] + i * 0.5 for i in range(1, 31)]
    future_volumes = [500] * 30

    prices = seg1_prices + gap_prices + seg2_prices + future_prices
    volumes = seg1_volumes + gap_volumes + seg2_volumes + future_volumes
    df = _make_klines(prices, volumes)

    config = {
        "window_min_days": 7,
        "window_max_days": 14,
        "volume_ratio": 0.5,
        "drop_min": 0.05,
        "drop_max": 0.15,
        "max_daily_change": 0.05,
    }
    hits = run_backtest({"TEST/USDT": df}, config)

    for i in range(1, len(hits)):
        date_a = pd.Timestamp(hits[i - 1].detect_date)
        date_b = pd.Timestamp(hits[i].detect_date)
        assert (date_b - date_a).days >= 14


def test_compute_stats_overall():
    """验证整体统计计算。"""
    hits = [
        BacktestHit("A/USDT", "2026-01-15", 14, 0.10, 0.3, 0.65,
                     {"3d": 0.05, "7d": 0.10, "14d": 0.15, "30d": 0.20}),
        BacktestHit("B/USDT", "2026-01-20", 10, 0.08, 0.4, 0.50,
                     {"3d": -0.03, "7d": 0.02, "14d": -0.05, "30d": 0.08}),
        BacktestHit("C/USDT", "2026-02-01", 12, 0.12, 0.2, 0.35,
                     {"3d": 0.02, "7d": -0.01, "14d": None, "30d": None}),
    ]
    stats = compute_stats(hits)

    assert stats["total_hits"] == 3
    overall = stats["overall"]
    assert "3d" in overall
    assert overall["3d"]["count"] == 3
    assert abs(overall["3d"]["win_rate"] - 2 / 3) < 0.01
    assert abs(overall["3d"]["mean"] - (0.05 - 0.03 + 0.02) / 3) < 0.001


def test_compute_stats_by_score_tier():
    """验证按评分分档统计。"""
    hits = [
        BacktestHit("A/USDT", "2026-01-15", 14, 0.10, 0.3, 0.65,
                     {"3d": 0.05, "7d": 0.10, "14d": 0.15, "30d": 0.20}),
        BacktestHit("B/USDT", "2026-01-20", 10, 0.08, 0.4, 0.50,
                     {"3d": -0.03, "7d": 0.02, "14d": -0.05, "30d": 0.08}),
        BacktestHit("C/USDT", "2026-02-01", 12, 0.12, 0.2, 0.35,
                     {"3d": 0.02, "7d": -0.01, "14d": None, "30d": None}),
    ]
    stats = compute_stats(hits)

    tiers = stats["by_tier"]
    assert tiers["high"]["3d"]["count"] == 1
    assert tiers["mid"]["3d"]["count"] == 1
    assert tiers["low"]["3d"]["count"] == 1
    assert tiers["high"]["3d"]["win_rate"] == 1.0
    assert tiers["low"]["3d"]["win_rate"] == 1.0
