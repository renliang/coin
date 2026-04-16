"""Tests for portfolio drift detection and rebalancing logic."""
import pytest

from portfolio.rebalancer import check_drift, compute_adjustments


class TestCheckDrift:
    def test_drift_detected(self):
        """Strategy 'a' drifted 50% from target → True."""
        target = {"a": 0.4, "b": 0.3, "c": 0.3}
        actual = {"a": 0.6, "b": 0.25, "c": 0.15}
        assert check_drift(target, actual) is True

    def test_no_drift(self):
        """Small deviations below threshold → False."""
        target = {"a": 0.4, "b": 0.3, "c": 0.3}
        # each strategy drifts < 5% relative
        actual = {"a": 0.41, "b": 0.295, "c": 0.295}
        assert check_drift(target, actual) is False

    def test_drift_exactly_at_threshold_not_exceeded(self):
        """Drift equal to threshold is not exceeded → False."""
        target = {"a": 0.5, "b": 0.5}
        # drift = |0.6 - 0.5| / 0.5 = 0.2 exactly, not > threshold
        actual = {"a": 0.6, "b": 0.4}
        assert check_drift(target, actual, threshold=0.2) is False

    def test_drift_just_above_threshold(self):
        """Drift just above threshold → True."""
        target = {"a": 0.5, "b": 0.5}
        # drift = |0.601 - 0.5| / 0.5 = 0.202 > 0.2
        actual = {"a": 0.601, "b": 0.399}
        assert check_drift(target, actual, threshold=0.2) is True

    def test_custom_threshold(self):
        """Custom threshold=0.05: 10% drift triggers True."""
        target = {"x": 1.0}
        actual = {"x": 0.89}  # drift = |0.89 - 1.0| / 1.0 = 0.11 > 0.05
        assert check_drift(target, actual, threshold=0.05) is True

    def test_empty_strategies(self):
        """Empty dicts → no drift → False."""
        assert check_drift({}, {}) is False


class TestComputeAdjustments:
    def test_compute_adjustments_signs_correct(self):
        """Underweight strategy gets positive adjustment, overweight gets negative."""
        target = {"a": 0.5, "b": 0.5}
        actual = {"a": 0.3, "b": 0.7}
        total_capital = 10_000.0
        adj = compute_adjustments(target, actual, total_capital)
        # 'a' is underweight: needs +2000
        assert adj["a"] > 0
        # 'b' is overweight: needs -2000
        assert adj["b"] < 0

    def test_compute_adjustments_sum_to_zero(self):
        """Adjustments should sum to approximately zero."""
        target = {"a": 0.4, "b": 0.3, "c": 0.3}
        actual = {"a": 0.6, "b": 0.25, "c": 0.15}
        total_capital = 100_000.0
        adj = compute_adjustments(target, actual, total_capital)
        assert abs(sum(adj.values())) < 1e-6

    def test_compute_adjustments_values(self):
        """Verify exact adjustment amounts."""
        target = {"a": 0.5, "b": 0.5}
        actual = {"a": 0.3, "b": 0.7}
        total_capital = 10_000.0
        adj = compute_adjustments(target, actual, total_capital)
        # (0.5 - 0.3) * 10000 = 2000
        assert abs(adj["a"] - 2000.0) < 1e-6
        # (0.5 - 0.7) * 10000 = -2000
        assert abs(adj["b"] - (-2000.0)) < 1e-6

    def test_compute_adjustments_three_strategies(self):
        """Three-strategy scenario: sum ≈ 0 and signs make sense."""
        target = {"a": 0.4, "b": 0.4, "c": 0.2}
        actual = {"a": 0.5, "b": 0.3, "c": 0.2}
        total_capital = 50_000.0
        adj = compute_adjustments(target, actual, total_capital)
        assert abs(sum(adj.values())) < 1e-6
        assert adj["a"] < 0   # overweight
        assert adj["b"] > 0   # underweight
        assert abs(adj["c"]) < 1e-6  # exactly on target
