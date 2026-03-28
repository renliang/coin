import pandas as pd
import numpy as np
from scanner.detector import detect_pattern, DetectionResult


def _make_klines(closes: list[float], volumes: list[float]) -> pd.DataFrame:
    """构造测试用K线DataFrame"""
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-03-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes],
        "close": closes,
        "volume": volumes,
    })


class TestVolumeDecline:
    def test_volume_declining_passes(self):
        volumes = [1000] * 7 + [300] * 7
        closes = [100 - i * 0.5 for i in range(14)]
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.volume_pass is True

    def test_volume_not_declining_fails(self):
        volumes = [1000] * 14
        closes = [100 - i * 0.5 for i in range(14)]
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.volume_pass is False


class TestDowntrend:
    def test_downtrend_passes(self):
        closes = [100 - i * 0.8 for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.trend_pass is True

    def test_uptrend_fails(self):
        closes = [100 + i * 0.8 for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.trend_pass is False


class TestDropRange:
    def test_drop_in_range_passes(self):
        closes = [100 - i * (10 / 13) for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.drop_pass is True

    def test_drop_too_large_fails(self):
        closes = [100 - i * (30 / 13) for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.drop_pass is False


class TestSlowDecline:
    def test_slow_decline_passes(self):
        closes = [100 - i * 0.7 for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.slow_pass is True

    def test_spike_day_fails(self):
        closes = [100 - i * 0.3 for i in range(14)]
        closes[7] = closes[6] * 0.90
        for i in range(8, 14):
            closes[i] = closes[7] - (i - 7) * 0.3
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.slow_pass is False


class TestFullPattern:
    def test_perfect_pattern_matches(self):
        closes = [100 - i * 0.7 for i in range(14)]
        volumes = [1000] * 7 + [300] * 7
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.matched is True

    def test_no_match_when_volume_flat(self):
        closes = [100 - i * 0.7 for i in range(14)]
        volumes = [1000] * 14
        df = _make_klines(closes, volumes)
        result = detect_pattern(df, window_min_days=7, window_max_days=14,
                                volume_ratio=0.5, drop_min=0.05, drop_max=0.15,
                                max_daily_change=0.05)
        assert result.matched is False
