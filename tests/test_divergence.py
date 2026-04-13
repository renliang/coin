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


class TestDetectDivergence:
    def _make_bullish_divergence_data(self) -> pd.DataFrame:
        """构造底背离数据：价格创新低，但DIF未创新低。

        波谷1在~index 40，波谷2在~index 80。pivot_len=7需要前后各7根。
        warmup=26，波谷1相对索引=14，满足≥7。
        两个波谷间距40，价格差>5%。
        """
        n = 100
        closes = []
        for i in range(n):
            if i < 40:
                # 急跌到波谷1 (100→40)
                closes.append(100 - i * 1.5)
            elif i < 60:
                # 充分反弹
                closes.append(40 + (i - 40) * 1.5)
            elif i < 80:
                # 缓跌到波谷2 (价格更低到35，但跌速更慢 → DIF更高)
                closes.append(70 - (i - 60) * 1.75)
            else:
                # 充分回升
                closes.append(35 + (i - 80) * 1.5)
        return _make_klines(closes, n)

    def test_bullish_divergence_detected(self):
        df = self._make_bullish_divergence_data()
        result = detect_divergence(df)
        assert result.divergence_type == "bullish"
        assert result.score > 0

    def _make_bearish_divergence_data(self) -> pd.DataFrame:
        """构造顶背离数据：价格创新高，但DIF未创新高。"""
        n = 100
        closes = []
        for i in range(n):
            if i < 40:
                # 急涨到波峰1 (50→110)
                closes.append(50 + i * 1.5)
            elif i < 60:
                # 充分回落
                closes.append(110 - (i - 40) * 1.5)
            elif i < 80:
                # 缓涨到波峰2 (价格更高到118，涨速慢 → DIF更低)
                closes.append(80 + (i - 60) * 1.9)
            else:
                # 充分回落
                closes.append(118 - (i - 80) * 1.5)
        return _make_klines(closes, n)

    def test_bearish_divergence_detected(self):
        df = self._make_bearish_divergence_data()
        result = detect_divergence(df)
        assert result.divergence_type == "bearish"
        assert result.score > 0

    def test_no_divergence_in_steady_uptrend(self):
        closes = [float(50 + i * 0.8) for i in range(70)]
        df = _make_klines(closes, 70)
        result = detect_divergence(df)
        assert result.divergence_type == "none"
        assert result.score == 0.0

    def test_insufficient_data_returns_none(self):
        closes = [100.0] * 20
        df = _make_klines(closes, 20)
        result = detect_divergence(df)
        assert result.divergence_type == "none"
