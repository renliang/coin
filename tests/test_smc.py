import pandas as pd
import numpy as np
import pytest
from scanner.smc import detect_smc, SmcResult, _score_smc, _prepare_ohlc


def _make_klines(prices: list[float], volumes: list[float]) -> pd.DataFrame:
    n = len(prices)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": volumes,
    })


def _make_trending_data(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """构造先跌后涨的趋势数据，足以触发 BOS/CHoCH。"""
    rng = np.random.RandomState(seed)
    t = np.arange(n)
    # 前 40 根下跌，后 60 根上涨（带噪声）
    trend = np.where(t < 40, -0.5 * t, -20 + 0.6 * (t - 40))
    noise = np.cumsum(rng.randn(n) * 1.5)
    close = 100 + trend + noise
    high = close + np.abs(rng.randn(n)) * 3
    low = close - np.abs(rng.randn(n)) * 3
    open_ = close + rng.randn(n) * 1
    volume = rng.randint(1000, 10000, n).astype(float)
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="D"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


# --- detect_smc tests ---

def test_insufficient_data():
    """数据不足 -> 不命中。"""
    df = _make_klines([10.0] * 10, [100.0] * 10)
    result = detect_smc(df, swing_length=5)
    assert result.matched is False


def test_flat_data_no_structure():
    """平盘数据无结构突破 -> 不命中。"""
    prices = [100.0] * 50
    volumes = [1000.0] * 50
    df = _make_klines(prices, volumes)
    result = detect_smc(df, swing_length=5)
    assert result.matched is False


def test_trending_data_detects_structure():
    """先跌后涨的数据应检测到 BOS 或 CHoCH。"""
    df = _make_trending_data(n=100, seed=42)
    result = detect_smc(df, swing_length=5, freshness_candles=30)
    assert result.matched is True
    assert result.structure_type in ("BOS", "CHoCH")
    assert result.direction in ("bullish", "bearish")
    assert result.signal_type in ("看多结构", "看空结构")
    assert 0.0 < result.score <= 1.0


def test_result_has_score_breakdown():
    """命中结果应包含评分分项。"""
    df = _make_trending_data(n=100, seed=42)
    result = detect_smc(df, swing_length=5, freshness_candles=30)
    if result.matched:
        breakdown = result.score_breakdown_dict()
        assert breakdown["mode"] == "smc"
        assert len(breakdown["components"]) == 4
        total = sum(c["score"] * c["weight"] for c in breakdown["components"])
        assert abs(total - breakdown["total"]) < 0.01


def test_bullish_structure_signal_type():
    """看多方向对应正确的 signal_type。"""
    df = _make_trending_data(n=100, seed=42)
    result = detect_smc(df, swing_length=5, freshness_candles=30)
    if result.matched:
        if result.direction == "bullish":
            assert result.signal_type == "看多结构"
        else:
            assert result.signal_type == "看空结构"


def test_strict_freshness_filters_old_signals():
    """非常短的 freshness_candles 应过滤掉不新鲜的结构。"""
    df = _make_trending_data(n=100, seed=42)
    # freshness_candles=1 表示只看最后 1 根 K 线
    result = detect_smc(df, swing_length=5, freshness_candles=1)
    # 可能命中也可能不命中，但如果命中，structure_index 应该是最后几根
    if result.matched:
        n = len(df)
        assert result.structure_index >= n - 2


def test_larger_swing_length_fewer_signals():
    """更大的 swing_length 应产生更少的 swing points，可能不命中。"""
    df = _make_trending_data(n=100, seed=42)
    r_small = detect_smc(df, swing_length=5, freshness_candles=30)
    r_large = detect_smc(df, swing_length=20, freshness_candles=30)
    # 大 swing_length 更严格，至少不会比小的更容易命中
    if r_large.matched:
        assert r_small.matched is True


# --- _score_smc tests ---

def test_score_choch_higher_than_bos():
    """CHoCH（反转）分数应高于 BOS（延续）。"""
    total_choch, *_ = _score_smc("CHoCH", 1.0, True, 0.8, True, 0.8)
    total_bos, *_ = _score_smc("BOS", 1.0, True, 0.8, True, 0.8)
    assert total_choch > total_bos


def test_score_with_fvg_and_ob_higher():
    """有 FVG + OB 的评分应高于仅有结构突破。"""
    total_all, *_ = _score_smc("CHoCH", 1.0, True, 0.8, True, 0.8)
    total_struct_only, *_ = _score_smc("CHoCH", 1.0, False, 0.0, False, 0.0)
    assert total_all > total_struct_only


def test_score_range():
    """评分应在 [0, 1]。"""
    for stype in ["BOS", "CHoCH"]:
        for freshness in [0.0, 0.5, 1.0]:
            for has_fvg in [True, False]:
                for has_ob in [True, False]:
                    total, s, f, o, c = _score_smc(
                        stype, freshness,
                        has_fvg, 0.8 if has_fvg else 0.0,
                        has_ob, 0.8 if has_ob else 0.0,
                    )
                    assert 0.0 <= total <= 1.0
                    assert all(0.0 <= v <= 1.0 for v in (s, f, o, c))


def test_score_confluence_increases_with_signals():
    """更多信号共振 -> confluence 分数更高。"""
    _, _, _, _, c_none = _score_smc("BOS", 1.0, False, 0.0, False, 0.0)
    _, _, _, _, c_fvg = _score_smc("BOS", 1.0, True, 0.5, False, 0.0)
    _, _, _, _, c_both = _score_smc("BOS", 1.0, True, 0.5, True, 0.5)
    assert c_none < c_fvg < c_both


def test_score_freshness_matters():
    """新鲜度越高，结构分数越高。"""
    total_fresh, *_ = _score_smc("CHoCH", 1.0, False, 0.0, False, 0.0)
    total_stale, *_ = _score_smc("CHoCH", 0.1, False, 0.0, False, 0.0)
    assert total_fresh > total_stale


# --- _prepare_ohlc tests ---

def test_prepare_ohlc_resets_index():
    """_prepare_ohlc 应重置索引为 0-based。"""
    df = _make_klines([10.0] * 5, [100.0] * 5)
    df.index = [10, 20, 30, 40, 50]
    ohlc = _prepare_ohlc(df)
    assert list(ohlc.index) == [0, 1, 2, 3, 4]
    assert "open" in ohlc.columns
    assert "volume" in ohlc.columns


# --- 多种随机种子鲁棒性测试 ---

@pytest.mark.parametrize("seed", [1, 7, 13, 21, 99])
def test_various_seeds_no_crash(seed):
    """不同随机种子数据不应崩溃。"""
    df = _make_trending_data(n=100, seed=seed)
    result = detect_smc(df, swing_length=5, freshness_candles=20)
    assert isinstance(result, SmcResult)
    assert isinstance(result.matched, bool)
    if result.matched:
        assert 0.0 < result.score <= 1.0
