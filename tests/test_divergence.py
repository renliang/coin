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

        第一个波谷在 ~index 30，第二个在 ~index 55。
        价格在第二个波谷更低，但由于整体跌幅放缓，DIF第二次更高。
        """
        n = 70
        closes = []
        for i in range(n):
            if i < 30:
                # 急跌到波谷1
                closes.append(100 - i * 1.5)
            elif i < 40:
                # 反弹
                closes.append(55 + (i - 30) * 2.0)
            elif i < 55:
                # 缓跌到波谷2（价格更低，但跌速更慢 → DIF更高）
                closes.append(75 - (i - 40) * 1.8)
            else:
                # 小幅回升
                closes.append(48 + (i - 55) * 0.5)
        return _make_klines(closes, n)

    def test_bullish_divergence_detected(self):
        df = self._make_bullish_divergence_data()
        result = detect_divergence(df)
        assert result.divergence_type == "bullish"
        assert result.score > 0

    def _make_bearish_divergence_data(self) -> pd.DataFrame:
        """构造顶背离数据：价格创新高，但DIF未创新高。"""
        n = 70
        closes = []
        for i in range(n):
            if i < 30:
                # 急涨到波峰1
                closes.append(50 + i * 1.5)
            elif i < 40:
                # 回落
                closes.append(95 - (i - 30) * 2.0)
            elif i < 55:
                # 缓涨到波峰2（价格更高，但涨速更慢 → DIF更低）
                closes.append(75 + (i - 40) * 1.8)
            else:
                # 小幅回落
                closes.append(102 - (i - 55) * 0.5)
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
