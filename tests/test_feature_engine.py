"""Tests for scanner/optimize/feature_engine.py — 16-dim feature extraction."""
import math

import numpy as np
import pandas as pd
import pytest

from scanner.optimize.feature_engine import FEATURE_NAMES, extract_features


def _make_df(n: int = 60, seed: int = 42) -> pd.DataFrame:
    """生成合成 K 线 DataFrame（60 根）。"""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    close = np.abs(close)
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    volume = rng.uniform(1e6, 5e6, n)
    return pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume})


def _make_match() -> dict:
    return {
        "volume_ratio": 0.8,
        "drop_pct": 0.15,
        "r_squared": 0.75,
        "max_daily_pct": 0.05,
        "window_days": 30,
        "score": 0.72,
    }


class TestExtractFeatures:
    def test_returns_correct_length(self):
        """返回恰好 16 个特征。"""
        df = _make_df()
        features = extract_features(_make_match(), df)
        assert len(features) == 16

    def test_no_nan_in_output(self):
        """输出中无 NaN 或 inf。"""
        df = _make_df()
        features = extract_features(_make_match(), df)
        for i, v in enumerate(features):
            assert math.isfinite(v), f"feature[{i}] ({FEATURE_NAMES[i]}) is not finite: {v}"

    def test_feature_names_match(self):
        """FEATURE_NAMES 包含预期的关键特征名。"""
        assert "btc_return_7d" in FEATURE_NAMES
        assert "volume_ratio" in FEATURE_NAMES
        assert "confirmation_score" in FEATURE_NAMES
        assert len(FEATURE_NAMES) == 16

    def test_btc_none_fills_zero(self):
        """btc_df=None 时 btc 相关特征为 0，整体无 NaN。"""
        df = _make_df()
        features = extract_features(_make_match(), df, btc_df=None)
        assert len(features) == 16
        for i, v in enumerate(features):
            assert math.isfinite(v), f"feature[{i}] ({FEATURE_NAMES[i]}) is not finite: {v}"
        # btc_return_7d 应为 0
        btc_idx = FEATURE_NAMES.index("btc_return_7d")
        assert features[btc_idx] == 0.0
        # btc_volatility_14d 应为 0
        vol_idx = FEATURE_NAMES.index("btc_volatility_14d")
        assert features[vol_idx] == 0.0
