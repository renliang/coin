"""横截面动量 (Cross-Sectional Momentum) 扫描测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.momentum import MomentumResult, rank_by_momentum


def _make_klines(prices: list[float]) -> pd.DataFrame:
    """用给定收盘价序列构造日 K 线 DataFrame。"""
    n = len(prices)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="D"),
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1_000_000.0] * n,
        }
    )


def _linear_rise(start: float, end: float, n: int) -> list[float]:
    return np.linspace(start, end, n).tolist()


def _linear_fall(start: float, end: float, n: int) -> list[float]:
    return np.linspace(start, end, n).tolist()


def test_ranks_by_return_pct_descending():
    """三个币按过去 30 天收益率排序: +100% > +50% > +10%。"""
    klines = {
        # 60 天够同时算 30d 收益和 50d MA
        "STRONG/USDT": _make_klines(_linear_rise(50.0, 100.0, 60)),   # +100% over 60d
        "MID/USDT": _make_klines(_linear_rise(100.0, 150.0, 60)),     # +50% over 60d
        "WEAK/USDT": _make_klines(_linear_rise(200.0, 220.0, 60)),    # +10% over 60d
    }
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    assert [r.symbol for r in out] == ["STRONG/USDT", "MID/USDT", "WEAK/USDT"]
    assert out[0].return_pct > out[1].return_pct > out[2].return_pct


def test_filters_out_below_ma():
    """下跌到 MA50 以下的币必须被过滤掉，即使过去 30 天依然是正数。"""
    # 前 40 天高位 200，后 20 天急跌到 90：MA50 还在 ~180，当前价 90 → 应排除
    prices = [200.0] * 40 + _linear_fall(200.0, 90.0, 20)
    # 另一个币稳定上涨，价高于 MA50
    rising = _linear_rise(50.0, 120.0, 60)

    klines = {
        "BROKEN/USDT": _make_klines(prices),
        "TRENDING/USDT": _make_klines(rising),
    }
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    symbols = [r.symbol for r in out]
    assert "TRENDING/USDT" in symbols
    assert "BROKEN/USDT" not in symbols


def test_returns_only_top_n():
    """top_n=2 时只返回最强的两个。"""
    klines = {f"S{i}/USDT": _make_klines(_linear_rise(100.0, 100.0 + i * 10, 60))
              for i in range(5)}
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=2)
    assert len(out) == 2


def test_skips_insufficient_data():
    """数据长度不足 max(lookback, ma_period)+1 的币要跳过。"""
    klines = {
        "SHORT/USDT": _make_klines(_linear_rise(100.0, 200.0, 20)),  # 20 天不够 MA50
        "OK/USDT": _make_klines(_linear_rise(100.0, 200.0, 60)),
    }
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    assert [r.symbol for r in out] == ["OK/USDT"]


def test_empty_input_returns_empty():
    assert rank_by_momentum({}, lookback_days=30, trend_ma_period=50, top_n=10) == []


def test_result_contains_expected_fields():
    klines = {"X/USDT": _make_klines(_linear_rise(100.0, 200.0, 60))}
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    r = out[0]
    assert isinstance(r, MomentumResult)
    assert r.symbol == "X/USDT"
    assert r.lookback_days == 30
    assert r.return_pct > 0
    assert r.above_ma is True
    assert r.ma_value > 0
    assert 0.0 <= r.score <= 1.0


def test_result_is_frozen():
    """MomentumResult 应为 frozen dataclass (immutability 原则)。"""
    klines = {"X/USDT": _make_klines(_linear_rise(100.0, 200.0, 60))}
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    with pytest.raises(Exception):
        out[0].symbol = "Y/USDT"  # type: ignore[misc]


def test_score_reflects_rank_percentile():
    """score 是按 rank 归一化的，最强 = 1.0，最弱 = ~0。"""
    klines = {f"S{i}/USDT": _make_klines(_linear_rise(100.0, 100.0 + (i + 1) * 20, 60))
              for i in range(5)}
    out = rank_by_momentum(klines, lookback_days=30, trend_ma_period=50, top_n=10)
    assert out[0].score == pytest.approx(1.0)
    assert out[-1].score < out[0].score
