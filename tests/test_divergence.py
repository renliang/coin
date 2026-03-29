import numpy as np
import pandas as pd
from scanner.divergence import compute_macd, find_pivots, detect_divergence, DivergenceResult


def _make_klines(closes: list[float], n: int | None = None) -> pd.DataFrame:
    if n is None:
        n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1000.0] * n,
    })


class TestComputeMACD:
    def test_returns_three_series(self):
        closes = pd.Series([float(100 + i) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        assert len(dif) == len(closes)
        assert len(dea) == len(closes)
        assert len(hist) == len(closes)

    def test_dif_positive_in_uptrend(self):
        closes = pd.Series([float(100 + i * 2) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        assert dif.iloc[-1] > 0

    def test_dif_negative_in_downtrend(self):
        closes = pd.Series([float(200 - i * 2) for i in range(60)])
        dif, dea, hist = compute_macd(closes)
        assert dif.iloc[-1] < 0


class TestFindPivots:
    def test_finds_valley(self):
        closes = [100, 98, 96, 94, 92, 90, 92, 94, 96, 98, 100,
                  98, 96, 94, 92, 90, 92, 94, 96, 98, 100]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert 5 in lows
        assert 15 in lows

    def test_finds_peak(self):
        closes = [90, 92, 94, 96, 98, 100, 98, 96, 94, 92, 90,
                  92, 94, 96, 98, 100, 98, 96, 94, 92, 90]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert 5 in highs
        assert 15 in highs

    def test_no_pivots_in_monotonic(self):
        closes = [float(100 + i) for i in range(20)]
        lows, highs = find_pivots(pd.Series(closes), pivot_len=3)
        assert len(lows) == 0
        assert len(highs) == 0
