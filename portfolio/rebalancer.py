"""Auto-rebalancer: drift detection and capital adjustment computation."""
from __future__ import annotations


def check_drift(
    target: dict[str, float],
    actual: dict[str, float],
    threshold: float = 0.2,
) -> bool:
    """Return True if any strategy's weight drifted beyond the threshold.

    Drift for each strategy is computed as:
        drift = |actual_w - target_w| / target_w

    Args:
        target: Mapping of strategy_id → target weight.
        actual: Mapping of strategy_id → current actual weight.
        threshold: Relative drift threshold (default 0.2 = 20%).

    Returns:
        True if any strategy exceeds the threshold, False otherwise.
    """
    for strategy_id, target_w in target.items():
        if target_w == 0:
            continue
        actual_w = actual.get(strategy_id, 0.0)
        drift = abs(actual_w - target_w) / target_w
        if drift > threshold:
            return True
    return False


def compute_adjustments(
    target: dict[str, float],
    actual: dict[str, float],
    total_capital: float,
) -> dict[str, float]:
    """Compute capital adjustments needed to restore target weights.

    For each strategy:
        adjustment = (target_w - actual_w) * total_capital

    Positive value means add funds; negative means reduce exposure.
    Adjustments sum to approximately zero (capital is redistributed, not added).

    Args:
        target: Mapping of strategy_id → target weight.
        actual: Mapping of strategy_id → current actual weight.
        total_capital: Total portfolio capital in base currency.

    Returns:
        Dict mapping strategy_id → signed capital adjustment.
    """
    return {
        strategy_id: (target_w - actual.get(strategy_id, 0.0)) * total_capital
        for strategy_id, target_w in target.items()
    }
