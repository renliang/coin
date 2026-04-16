"""Tests for portfolio data models."""
import pytest

from portfolio.models import PortfolioState, StrategyResult


class TestStrategyResult:
    def test_creation(self):
        sr = StrategyResult(
            strategy_id="strat_a",
            sharpe=1.5,
            win_rate=0.6,
            max_drawdown=0.1,
            daily_returns=[0.01, 0.02, -0.01],
        )
        assert sr.strategy_id == "strat_a"
        assert sr.sharpe == 1.5
        assert sr.win_rate == 0.6
        assert sr.max_drawdown == 0.1
        assert sr.daily_returns == [0.01, 0.02, -0.01]

    def test_frozen_immutable(self):
        sr = StrategyResult(
            strategy_id="strat_a",
            sharpe=1.5,
            win_rate=0.6,
            max_drawdown=0.1,
        )
        with pytest.raises(Exception):
            sr.sharpe = 2.0  # type: ignore[misc]

    def test_default_empty_daily_returns(self):
        sr = StrategyResult(
            strategy_id="strat_b",
            sharpe=0.5,
            win_rate=0.4,
            max_drawdown=0.2,
        )
        assert sr.daily_returns == []

    def test_frozen_daily_returns_field(self):
        sr = StrategyResult(
            strategy_id="strat_c",
            sharpe=1.0,
            win_rate=0.55,
            max_drawdown=0.05,
        )
        with pytest.raises(Exception):
            sr.daily_returns = [0.01]  # type: ignore[misc]


class TestPortfolioState:
    def test_creation(self):
        ps = PortfolioState(
            weights={"strat_a": 0.6, "strat_b": 0.4},
            nav=1000.0,
            high_water_mark=1100.0,
        )
        assert ps.weights == {"strat_a": 0.6, "strat_b": 0.4}
        assert ps.nav == 1000.0
        assert ps.high_water_mark == 1100.0
        assert ps.halted_strategies == set()
        assert ps.portfolio_halted is False

    def test_mutable(self):
        ps = PortfolioState(
            weights={"strat_a": 1.0},
            nav=500.0,
            high_water_mark=600.0,
        )
        ps.nav = 520.0
        assert ps.nav == 520.0

    def test_halted_strategies_default(self):
        ps = PortfolioState(
            weights={},
            nav=100.0,
            high_water_mark=100.0,
        )
        assert isinstance(ps.halted_strategies, set)
        assert len(ps.halted_strategies) == 0

    def test_set_halted_strategies(self):
        ps = PortfolioState(
            weights={"s1": 1.0},
            nav=100.0,
            high_water_mark=100.0,
            halted_strategies={"s1"},
        )
        assert "s1" in ps.halted_strategies

    def test_portfolio_halted_flag(self):
        ps = PortfolioState(
            weights={},
            nav=900.0,
            high_water_mark=1000.0,
            portfolio_halted=True,
        )
        assert ps.portfolio_halted is True
