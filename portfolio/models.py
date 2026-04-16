"""Data models for portfolio management."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyResult:
    """Immutable snapshot of a strategy's performance metrics."""

    strategy_id: str
    sharpe: float
    win_rate: float
    max_drawdown: float
    daily_returns: list[float] = field(default_factory=list)


@dataclass
class PortfolioState:
    """Mutable runtime state of the portfolio."""

    weights: dict[str, float]
    nav: float
    high_water_mark: float
    halted_strategies: set[str] = field(default_factory=set)
    portfolio_halted: bool = False
