"""Tests for QuantStats-backed performance tracker."""
import os

import pytest

from portfolio.tracker import compute_strategy_stats, generate_portfolio_report


class TestComputeStrategyStats:
    def test_compute_strategy_stats_positive_returns(self):
        """Consistent positive daily returns → sharpe > 0, win_rate > 0."""
        daily_returns = [0.005] * 100  # 0.5% every day
        stats = compute_strategy_stats("strat_a", daily_returns)
        assert stats["strategy_id"] == "strat_a"
        assert stats["sharpe"] > 0
        assert stats["win_rate"] > 0
        assert "max_drawdown" in stats
        assert "total_return" in stats

    def test_compute_empty_returns(self):
        """Empty returns list → all numeric fields are zero."""
        stats = compute_strategy_stats("strat_empty", [])
        assert stats["strategy_id"] == "strat_empty"
        assert stats["sharpe"] == 0
        assert stats["win_rate"] == 0
        assert stats["max_drawdown"] == 0
        assert stats["total_return"] == 0

    def test_compute_stats_keys_present(self):
        """Result dict must contain all required keys."""
        stats = compute_strategy_stats("s1", [0.01, -0.005, 0.003])
        required_keys = {"strategy_id", "sharpe", "win_rate", "max_drawdown", "total_return"}
        assert required_keys.issubset(stats.keys())

    def test_win_rate_in_range(self):
        """win_rate must be in [0, 1]."""
        daily_returns = [0.01, -0.005, 0.003, -0.002, 0.007]
        stats = compute_strategy_stats("s2", daily_returns)
        assert 0.0 <= stats["win_rate"] <= 1.0

    def test_negative_returns_sharpe_not_positive(self):
        """Consistent negative returns → sharpe <= 0."""
        daily_returns = [-0.005] * 60
        stats = compute_strategy_stats("bear", daily_returns)
        assert stats["sharpe"] <= 0


class TestGeneratePortfolioReport:
    def test_generate_report_creates_file(self, tmp_path):
        """generate_portfolio_report should create a non-empty HTML file."""
        strategy_returns = {
            "strat_a": [0.005] * 60,
            "strat_b": [0.003, -0.002] * 30,
        }
        weights = {"strat_a": 0.6, "strat_b": 0.4}
        output_path = str(tmp_path / "report.html")

        generate_portfolio_report(strategy_returns, weights, output_path)

        assert os.path.exists(output_path), "HTML report file was not created"
        assert os.path.getsize(output_path) > 0, "HTML report file is empty"

    def test_generate_report_is_html(self, tmp_path):
        """Generated file should contain basic HTML markup."""
        strategy_returns = {"s1": [0.01] * 30}
        weights = {"s1": 1.0}
        output_path = str(tmp_path / "out.html")

        generate_portfolio_report(strategy_returns, weights, output_path)

        with open(output_path) as f:
            content = f.read()
        assert "<html" in content.lower() or "<!doctype" in content.lower()

    def test_generate_report_single_strategy(self, tmp_path):
        """Single strategy with full weight should still produce a report."""
        strategy_returns = {"solo": [0.002] * 50}
        weights = {"solo": 1.0}
        output_path = str(tmp_path / "solo_report.html")

        generate_portfolio_report(strategy_returns, weights, output_path)

        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
