"""Tests for three-layer risk control."""
import pytest

from portfolio.models import PortfolioState
from portfolio.risk import (
    PortfolioRiskResult,
    StrategyRiskResult,
    check_portfolio_risk,
    check_strategy_risk,
    update_hwm,
)


class TestCheckStrategyRisk:
    def test_daily_limit_exceeded_halted(self):
        result = check_strategy_risk("strat_a", daily_pnl_pct=-0.04, limit=0.03)
        assert isinstance(result, StrategyRiskResult)
        assert result.halted is True
        assert result.reason == "daily_limit"
        assert result.strategy_id == "strat_a"

    def test_within_limit_not_halted(self):
        result = check_strategy_risk("strat_b", daily_pnl_pct=-0.02, limit=0.03)
        assert result.halted is False
        assert result.reason == ""

    def test_exactly_at_limit_not_halted(self):
        result = check_strategy_risk("strat_c", daily_pnl_pct=-0.03, limit=0.03)
        assert result.halted is False

    def test_positive_pnl_not_halted(self):
        result = check_strategy_risk("strat_d", daily_pnl_pct=0.05, limit=0.03)
        assert result.halted is False
        assert result.reason == ""

    def test_zero_pnl_not_halted(self):
        result = check_strategy_risk("strat_e", daily_pnl_pct=0.0, limit=0.03)
        assert result.halted is False

    def test_frozen_result(self):
        result = check_strategy_risk("strat_f", daily_pnl_pct=-0.05)
        with pytest.raises(Exception):
            result.halted = False  # type: ignore[misc]


class TestCheckPortfolioRisk:
    def _make_state(self, nav: float, hwm: float) -> PortfolioState:
        return PortfolioState(weights={}, nav=nav, high_water_mark=hwm)

    def test_drawdown_6pct_with_5pct_limit_halted(self):
        state = self._make_state(nav=940.0, hwm=1000.0)  # 6% drawdown
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert isinstance(result, PortfolioRiskResult)
        assert result.portfolio_halted is True
        assert result.reason == "drawdown_halt"
        assert abs(result.drawdown_pct - 0.06) < 1e-9

    def test_drawdown_4pct_with_5pct_limit_not_halted(self):
        state = self._make_state(nav=960.0, hwm=1000.0)  # 4% drawdown
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is False
        assert result.reason == ""
        assert abs(result.drawdown_pct - 0.04) < 1e-9

    def test_exactly_at_limit_not_halted(self):
        state = self._make_state(nav=950.0, hwm=1000.0)  # exactly 5%
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is False

    def test_no_drawdown_not_halted(self):
        state = self._make_state(nav=1000.0, hwm=1000.0)
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is False
        assert result.drawdown_pct == 0.0

    def test_nav_above_hwm_not_halted(self):
        state = self._make_state(nav=1100.0, hwm=1000.0)
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is False

    def test_frozen_result(self):
        state = self._make_state(nav=900.0, hwm=1000.0)
        result = check_portfolio_risk(state)
        with pytest.raises(Exception):
            result.portfolio_halted = False  # type: ignore[misc]


class TestUpdateHwm:
    def test_hwm_updates_on_new_high(self):
        state = PortfolioState(weights={}, nav=1100.0, high_water_mark=1000.0)
        new_state = update_hwm(state)
        assert new_state.high_water_mark == 1100.0
        assert new_state.nav == 1100.0

    def test_hwm_stays_on_decline(self):
        state = PortfolioState(weights={}, nav=900.0, high_water_mark=1000.0)
        new_state = update_hwm(state)
        assert new_state.high_water_mark == 1000.0
        assert new_state.nav == 900.0

    def test_hwm_equal_nav_unchanged(self):
        state = PortfolioState(weights={}, nav=1000.0, high_water_mark=1000.0)
        new_state = update_hwm(state)
        assert new_state.high_water_mark == 1000.0

    def test_returns_new_object(self):
        state = PortfolioState(weights={}, nav=1100.0, high_water_mark=1000.0)
        new_state = update_hwm(state)
        assert new_state is not state

    def test_preserves_other_fields(self):
        state = PortfolioState(
            weights={"strat_a": 1.0},
            nav=1100.0,
            high_water_mark=1000.0,
            halted_strategies={"strat_b"},
            portfolio_halted=False,
        )
        new_state = update_hwm(state)
        assert new_state.weights == {"strat_a": 1.0}
        assert new_state.halted_strategies == {"strat_b"}
        assert new_state.portfolio_halted is False
