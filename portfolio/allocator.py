"""CVaR-based strategy weight allocator using Riskfolio-Lib."""
from __future__ import annotations

import logging

import pandas as pd

from portfolio.models import StrategyResult

logger = logging.getLogger(__name__)

_MIN_RETURNS_REQUIRED = 30


def optimize_weights(
    strategies: list[StrategyResult],
    max_weight: float = 0.5,
    min_weight: float = 0.05,
) -> dict[str, float]:
    """Compute optimal CVaR-based weights for a list of strategies.

    Algorithm:
    1. Return {} if no strategies.
    2. Fall back to equal weight if any strategy has < 30 daily_returns.
    3. Build a returns DataFrame and run Riskfolio CVaR/Sharpe optimisation.
    4. Force strategies with sharpe < 0 to min_weight.
    5. Clamp all weights to [min_weight, max_weight].
    6. Normalize so weights sum to 1.0.
    7. Fall back to equal weight on any optimization failure.

    Args:
        strategies: List of StrategyResult objects with performance data.
        max_weight: Upper bound per strategy (default 0.50).
        min_weight: Lower bound per strategy (default 0.05).

    Returns:
        Dict mapping strategy_id → weight. Empty dict if no strategies.
    """
    if not strategies:
        return {}

    # Check whether all strategies have sufficient return history
    if any(len(s.daily_returns) < _MIN_RETURNS_REQUIRED for s in strategies):
        logger.warning(
            "One or more strategies have < %d daily returns; "
            "falling back to equal weight.",
            _MIN_RETURNS_REQUIRED,
        )
        return _equal_weights(strategies)

    try:
        import riskfolio as rp

        returns_df = pd.DataFrame(
            {s.strategy_id: s.daily_returns for s in strategies}
        )

        port = rp.Portfolio(returns=returns_df)
        port.assets_stats(method_mu="hist", method_cov="hist")

        w_df = port.optimization(model="Classic", rm="CVaR", obj="Sharpe", rf=0)

        if w_df is None or w_df.empty:
            logger.warning("Riskfolio returned empty weights; falling back to equal weight.")
            return _equal_weights(strategies)

        weights: dict[str, float] = {
            sid: float(w_df.loc[sid, "weights"])
            for sid in w_df.index
        }

    except Exception as exc:
        logger.warning("CVaR optimization failed (%s); falling back to equal weight.", exc)
        return _equal_weights(strategies)

    # Force negative-sharpe strategies to min_weight
    forced_min: set[str] = set()
    for s in strategies:
        if s.sharpe < 0:
            weights[s.strategy_id] = min_weight
            forced_min.add(s.strategy_id)

    # Iterative clamping: clamp → normalize → repeat until stable
    # This ensures bounds are respected after normalization.
    return _clamp_and_normalize(weights, min_weight, max_weight, forced_min)


def _clamp_and_normalize(
    weights: dict[str, float],
    min_weight: float,
    max_weight: float,
    forced_min: set[str] | None = None,
    max_iter: int = 100,
) -> dict[str, float]:
    """Iteratively clamp weights to [min_weight, max_weight] and normalize.

    Repeats until all weights are within bounds (or max_iter is reached).
    Strategies in ``forced_min`` are always held at exactly min_weight.
    """
    forced_min = forced_min or set()
    w = dict(weights)
    for _ in range(max_iter):
        # Apply forced floor first
        for sid in forced_min:
            w[sid] = min_weight
        # Clamp everything
        for sid in w:
            w[sid] = max(min_weight, min(max_weight, w[sid]))
        # Normalize
        total = sum(w.values())
        if total > 0:
            w = {sid: v / total for sid, v in w.items()}
        # Check convergence: are all bounds respected after normalization?
        if all(min_weight - 1e-9 <= v <= max_weight + 1e-9 for v in w.values()):
            break
    return w


def _equal_weights(strategies: list[StrategyResult]) -> dict[str, float]:
    """Return equal weights for all strategies, normalized to 1.0."""
    n = len(strategies)
    return {s.strategy_id: 1.0 / n for s in strategies}


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    """Normalize weights so they sum to exactly 1.0."""
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {sid: w / total for sid, w in weights.items()}
