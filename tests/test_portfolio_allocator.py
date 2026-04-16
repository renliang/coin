"""Tests for CVaR-based strategy weight allocator."""
import random

import pytest

from portfolio.allocator import optimize_weights
from portfolio.models import StrategyResult


def _make_strategy(
    sid: str,
    sharpe: float = 1.0,
    n_returns: int = 60,
    seed: int = 42,
) -> StrategyResult:
    rng = random.Random(seed)
    daily_returns = [rng.gauss(0.001, 0.01) for _ in range(n_returns)]
    return StrategyResult(
        strategy_id=sid,
        sharpe=sharpe,
        win_rate=0.55,
        max_drawdown=0.1,
        daily_returns=daily_returns,
    )


class TestOptimizeWeightsValid:
    def test_returns_valid_weights(self):
        strategies = [
            _make_strategy("A", seed=1),
            _make_strategy("B", seed=2),
            _make_strategy("C", seed=3),
        ]
        weights = optimize_weights(strategies)
        assert set(weights.keys()) == {"A", "B", "C"}
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        for w in weights.values():
            assert 0.05 - 1e-9 <= w <= 0.5 + 1e-9

    def test_weights_sum_to_one(self):
        strategies = [_make_strategy(f"S{i}", seed=i) for i in range(5)]
        weights = optimize_weights(strategies)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_custom_bounds_respected(self):
        strategies = [_make_strategy(f"S{i}", seed=i + 10) for i in range(4)]
        weights = optimize_weights(strategies, max_weight=0.4, min_weight=0.1)
        for w in weights.values():
            assert 0.1 - 1e-9 <= w <= 0.4 + 1e-9


class TestNegativeSharpeMinWeight:
    def test_negative_sharpe_gets_min_weight(self):
        strategies = [
            _make_strategy("good_A", sharpe=1.5, seed=1),
            _make_strategy("good_B", sharpe=1.2, seed=2),
            _make_strategy("bad_C", sharpe=-0.5, seed=3),
        ]
        weights = optimize_weights(strategies, min_weight=0.05)
        # bad_C must remain at the minimum floor (within bounds) and be <= other strategies
        assert 0.05 - 1e-9 <= weights["bad_C"] <= 0.5 + 1e-9
        assert weights["good_A"] >= weights["bad_C"] or weights["good_B"] >= weights["bad_C"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_all_negative_sharpe_still_sums_to_one(self):
        strategies = [
            _make_strategy("A", sharpe=-1.0, seed=1),
            _make_strategy("B", sharpe=-0.5, seed=2),
        ]
        weights = optimize_weights(strategies, min_weight=0.05)
        assert abs(sum(weights.values()) - 1.0) < 1e-6


class TestFallbackEqualWeight:
    def test_empty_strategies_returns_empty(self):
        result = optimize_weights([])
        assert result == {}

    def test_insufficient_returns_falls_back_to_equal(self):
        strategies = [
            StrategyResult("A", sharpe=1.0, win_rate=0.5, max_drawdown=0.1, daily_returns=[0.01] * 10),
            StrategyResult("B", sharpe=1.2, win_rate=0.6, max_drawdown=0.08, daily_returns=[0.02] * 10),
        ]
        weights = optimize_weights(strategies)
        assert len(weights) == 2
        assert abs(weights["A"] - 0.5) < 1e-9
        assert abs(weights["B"] - 0.5) < 1e-9

    def test_one_strategy_insufficient_returns_equals_full(self):
        strategies = [
            StrategyResult("A", sharpe=1.0, win_rate=0.5, max_drawdown=0.1, daily_returns=[0.01] * 60),
            StrategyResult("B", sharpe=1.2, win_rate=0.6, max_drawdown=0.08, daily_returns=[]),
        ]
        weights = optimize_weights(strategies)
        # B has 0 returns < 30, should fall back to equal
        assert abs(weights["A"] - 0.5) < 1e-9
        assert abs(weights["B"] - 0.5) < 1e-9

    def test_single_strategy_weight_is_one(self):
        strategies = [_make_strategy("solo", seed=99)]
        weights = optimize_weights(strategies)
        assert len(weights) == 1
        assert abs(weights["solo"] - 1.0) < 1e-6
