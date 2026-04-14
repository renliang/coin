"""Tests for scanner/optimize/param_optimizer.py (TDD: written before implementation)."""
import pytest
import numpy as np

from scanner.backtest import BacktestHit
from scanner.optimize.param_optimizer import (
    OptimizedParams,
    score_with_weights,
    objective_from_hits,
    optimize_params,
)


def _make_hit(
    symbol: str = "BTC/USDT",
    detect_date: str = "2024-01-01",
    volume_ratio: float = 0.4,
    drop_pct: float = 0.10,
    r_squared: float = 0.8,
    max_daily_pct: float = 0.03,
    score: float = 0.7,
    return_7d: float | None = 0.05,
) -> BacktestHit:
    return BacktestHit(
        symbol=symbol,
        detect_date=detect_date,
        window_days=14,
        drop_pct=drop_pct,
        volume_ratio=volume_ratio,
        score=score,
        returns={"3d": None, "7d": return_7d, "14d": None, "30d": None},
        r_squared=r_squared,
        max_daily_pct=max_daily_pct,
    )


def _make_hits(n: int, rng: np.random.Generator | None = None) -> list[BacktestHit]:
    """生成合成 BacktestHit 列表，日期递增以确保 split 有效。"""
    if rng is None:
        rng = np.random.default_rng(42)
    hits = []
    for i in range(n):
        year = 2024
        month = (i // 28) % 12 + 1
        day = (i % 28) + 1
        date = f"{year}-{month:02d}-{day:02d}"
        hits.append(_make_hit(
            symbol=f"COIN{i}/USDT",
            detect_date=date,
            volume_ratio=float(rng.uniform(0.2, 0.8)),
            drop_pct=float(rng.uniform(0.04, 0.20)),
            r_squared=float(rng.uniform(0.3, 0.99)),
            max_daily_pct=float(rng.uniform(0.01, 0.07)),
            score=float(rng.uniform(0.5, 0.95)),
            return_7d=float(rng.uniform(-0.05, 0.15)),
        ))
    return hits


class TestScoreWithWeights:
    def test_weights_normalized(self):
        """score_with_weights 应返回 [0, 1] 范围内的值。"""
        score = score_with_weights(
            volume_ratio=0.4,
            drop_pct=0.10,
            r_squared=0.8,
            max_daily_pct=0.03,
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
        )
        assert 0.0 <= score <= 1.0

    def test_weights_normalized_unequal_weights(self):
        """不等权重也应归一化，结果仍在 [0, 1]。"""
        score = score_with_weights(
            volume_ratio=0.3,
            drop_pct=0.12,
            r_squared=0.9,
            max_daily_pct=0.02,
            w_volume=0.6,
            w_drop=0.05,
            w_trend=0.05,
            w_slow=0.05,
        )
        assert 0.0 <= score <= 1.0

    def test_higher_quality_higher_score(self):
        """好信号（低 volume_ratio, 理想 drop, 高 r², 低 daily_pct）应得分更高。"""
        good_score = score_with_weights(
            volume_ratio=0.1,
            drop_pct=0.10,
            r_squared=0.95,
            max_daily_pct=0.01,
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
        )
        bad_score = score_with_weights(
            volume_ratio=0.9,
            drop_pct=0.25,
            r_squared=0.1,
            max_daily_pct=0.08,
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
        )
        assert good_score > bad_score

    def test_extreme_values_clamped(self):
        """极端值应被截断，不出现负分或超过 1。"""
        score = score_with_weights(
            volume_ratio=2.0,   # 远超 1
            drop_pct=0.50,      # 偏离中间值很大
            r_squared=-0.5,     # 负值
            max_daily_pct=1.0,  # 远超 max_daily_change
            w_volume=0.25,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.25,
        )
        assert 0.0 <= score <= 1.0


class TestObjectiveFromHits:
    def test_returns_float(self):
        """objective_from_hits 应返回 float。"""
        hits = _make_hits(30)
        result = objective_from_hits(
            hits=hits,
            min_score=0.6,
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
            drop_min=0.05,
            drop_max=0.15,
            max_daily_change=0.05,
        )
        assert isinstance(result, float)

    def test_penalty_on_few_samples(self):
        """样本不足（< min_samples）时应返回 -1.0。"""
        hits = _make_hits(5)
        result = objective_from_hits(
            hits=hits,
            min_score=0.99,  # 高门槛确保通过的样本极少
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
            drop_min=0.05,
            drop_max=0.15,
            max_daily_change=0.05,
            min_samples=10,
        )
        assert result < -0.5

    def test_none_returns_excluded(self):
        """returns['7d'] 为 None 的 hit 应被排除，不影响统计。"""
        hits = [_make_hit(return_7d=None) for _ in range(5)]
        result = objective_from_hits(
            hits=hits,
            min_score=0.0,
            w_volume=0.3,
            w_drop=0.25,
            w_trend=0.25,
            w_slow=0.2,
            drop_min=0.05,
            drop_max=0.15,
            max_daily_change=0.05,
            min_samples=10,
        )
        assert result == -1.0


class TestOptimizeParams:
    def test_returns_optimized_params(self):
        """optimize_params 应返回 OptimizedParams 实例。"""
        hits = _make_hits(40)
        result = optimize_params(hits, n_trials=5)
        assert isinstance(result, OptimizedParams)

    def test_weights_normalized_in_result(self):
        """返回的权重之和应约等于 1（已归一化）。"""
        hits = _make_hits(40)
        result = optimize_params(hits, n_trials=5)
        total = result.w_volume + result.w_drop + result.w_trend + result.w_slow
        assert abs(total - 1.0) < 1e-6

    def test_params_in_valid_range(self):
        """返回参数应在搜索空间范围内。"""
        hits = _make_hits(40)
        result = optimize_params(hits, n_trials=5)
        assert 0.0 < result.drop_min < result.drop_max <= 0.25
        assert 0.03 <= result.max_daily_change <= 0.08
        assert 0.25 <= result.volume_ratio <= 0.75
        assert 0.5 <= result.min_score <= 0.95
        assert result.confirmation_min_pass in range(1, 6)

    def test_has_validation_metrics(self):
        """结果应包含验证胜率与均值收益字段。"""
        hits = _make_hits(40)
        result = optimize_params(hits, n_trials=5)
        assert isinstance(result.validation_win_rate, float)
        assert isinstance(result.validation_mean_return, float)
