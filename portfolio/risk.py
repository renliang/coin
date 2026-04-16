"""Three-layer risk control for portfolio management."""
from dataclasses import dataclass

from portfolio.models import PortfolioState


@dataclass(frozen=True)
class StrategyRiskResult:
    """Result of a per-strategy risk check."""

    strategy_id: str
    halted: bool
    reason: str  # "" or "daily_limit"


@dataclass(frozen=True)
class PortfolioRiskResult:
    """Result of a portfolio-level risk check."""

    portfolio_halted: bool
    drawdown_pct: float
    reason: str  # "" or "drawdown_halt"


def check_strategy_risk(
    strategy_id: str,
    daily_pnl_pct: float,
    limit: float = 0.03,
) -> StrategyRiskResult:
    """Halt a strategy if its daily loss exceeds the limit.

    Args:
        strategy_id: Identifier of the strategy.
        daily_pnl_pct: Daily PnL as a fraction (negative = loss).
        limit: Maximum allowed daily loss fraction (default 3%).

    Returns:
        StrategyRiskResult with halted=True when loss exceeds limit.
    """
    if daily_pnl_pct < -limit:
        return StrategyRiskResult(
            strategy_id=strategy_id,
            halted=True,
            reason="daily_limit",
        )
    return StrategyRiskResult(
        strategy_id=strategy_id,
        halted=False,
        reason="",
    )


def check_portfolio_risk(
    state: PortfolioState,
    drawdown_limit: float = 0.05,
) -> PortfolioRiskResult:
    """Halt the portfolio if drawdown from high-water mark exceeds limit.

    Args:
        state: Current portfolio state.
        drawdown_limit: Maximum allowed drawdown fraction (default 5%).

    Returns:
        PortfolioRiskResult with portfolio_halted=True when drawdown exceeds limit.
    """
    if state.high_water_mark <= 0:
        return PortfolioRiskResult(
            portfolio_halted=False,
            drawdown_pct=0.0,
            reason="",
        )
    drawdown = (state.high_water_mark - state.nav) / state.high_water_mark
    if drawdown > drawdown_limit:
        return PortfolioRiskResult(
            portfolio_halted=True,
            drawdown_pct=drawdown,
            reason="drawdown_halt",
        )
    return PortfolioRiskResult(
        portfolio_halted=False,
        drawdown_pct=drawdown,
        reason="",
    )


def update_hwm(state: PortfolioState) -> PortfolioState:
    """Return a new PortfolioState with high_water_mark updated if nav exceeds it.

    Follows immutable update pattern: always returns a new object.
    """
    new_hwm = max(state.high_water_mark, state.nav)
    return PortfolioState(
        weights=dict(state.weights),
        nav=state.nav,
        high_water_mark=new_hwm,
        halted_strategies=set(state.halted_strategies),
        portfolio_halted=state.portfolio_halted,
    )
