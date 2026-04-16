"""QuantStats-backed performance tracker for portfolio strategies."""
from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

_ANNUALIZATION_FACTOR = math.sqrt(252)


def compute_strategy_stats(
    strategy_id: str,
    daily_returns: list[float],
) -> dict[str, Any]:
    """Compute key performance statistics for a single strategy.

    Args:
        strategy_id: Unique identifier of the strategy.
        daily_returns: Sequence of daily return values (e.g. 0.01 = 1%).

    Returns:
        Dict with keys: strategy_id, sharpe, win_rate, max_drawdown, total_return.
        All numeric values are zero when daily_returns is empty.
    """
    if not daily_returns:
        return {
            "strategy_id": strategy_id,
            "sharpe": 0,
            "win_rate": 0,
            "max_drawdown": 0,
            "total_return": 0,
        }

    n = len(daily_returns)
    mean_r = sum(daily_returns) / n
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / n
    std_r = math.sqrt(variance) if variance > 0 else 0.0

    if std_r > 0:
        sharpe = mean_r / std_r * _ANNUALIZATION_FACTOR
    elif mean_r > 0:
        sharpe = float("inf")
    elif mean_r < 0:
        sharpe = float("-inf")
    else:
        sharpe = 0.0
    win_rate = sum(1 for r in daily_returns if r > 0) / n

    # Max drawdown via cumulative equity curve
    max_drawdown = _compute_max_drawdown(daily_returns)

    # Total return from compounded daily returns
    total_return = _compute_total_return(daily_returns)

    return {
        "strategy_id": strategy_id,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "total_return": total_return,
    }


def generate_portfolio_report(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
    output_path: str,
) -> None:
    """Generate an HTML performance report for the weighted portfolio.

    Attempts to use quantstats.reports.html() for a rich report.
    Falls back to _generate_basic_report() on any failure.

    Args:
        strategy_returns: Mapping of strategy_id → list of daily returns.
        weights: Mapping of strategy_id → portfolio weight (should sum to 1).
        output_path: File path where the HTML report will be written.
    """
    portfolio_returns = _build_portfolio_returns(strategy_returns, weights)

    try:
        import pandas as pd
        import quantstats as qs

        returns_series = pd.Series(portfolio_returns)
        qs.reports.html(returns_series, output=output_path, download_filename=output_path)
        logger.info("QuantStats report written to %s", output_path)
    except Exception as exc:
        logger.warning(
            "quantstats report generation failed (%s); falling back to basic report.", exc
        )
        _generate_basic_report(strategy_returns, weights, output_path)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_max_drawdown(daily_returns: list[float]) -> float:
    """Compute maximum drawdown from a sequence of daily returns."""
    peak = 1.0
    equity = 1.0
    max_dd = 0.0
    for r in daily_returns:
        equity *= 1.0 + r
        if equity > peak:
            peak = equity
        drawdown = (peak - equity) / peak if peak > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
    return max_dd


def _compute_total_return(daily_returns: list[float]) -> float:
    """Compute total compounded return from daily returns."""
    equity = 1.0
    for r in daily_returns:
        equity *= 1.0 + r
    return equity - 1.0


def _build_portfolio_returns(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
) -> list[float]:
    """Build a weighted portfolio return series.

    Uses the minimum length across all strategies.
    """
    if not strategy_returns:
        return []

    min_len = min(len(v) for v in strategy_returns.values())
    if min_len == 0:
        return []

    portfolio: list[float] = []
    for i in range(min_len):
        daily = sum(
            weights.get(sid, 0.0) * returns[i]
            for sid, returns in strategy_returns.items()
        )
        portfolio.append(daily)
    return portfolio


def _generate_basic_report(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
    output_path: str,
) -> None:
    """Write a minimal HTML report with per-strategy stats as a fallback."""
    rows_html = ""
    for sid, returns in strategy_returns.items():
        stats = compute_strategy_stats(sid, returns)
        weight = weights.get(sid, 0.0)
        rows_html += (
            f"<tr>"
            f"<td>{sid}</td>"
            f"<td>{weight:.2%}</td>"
            f"<td>{stats['sharpe']:.3f}</td>"
            f"<td>{stats['win_rate']:.2%}</td>"
            f"<td>{stats['max_drawdown']:.2%}</td>"
            f"<td>{stats['total_return']:.2%}</td>"
            f"</tr>\n"
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Portfolio Performance Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ccc; padding: 0.5rem 1rem; text-align: right; }}
    th {{ background: #f0f0f0; }}
    td:first-child {{ text-align: left; }}
  </style>
</head>
<body>
  <h1>Portfolio Performance Report</h1>
  <table>
    <thead>
      <tr>
        <th>Strategy</th>
        <th>Weight</th>
        <th>Sharpe</th>
        <th>Win Rate</th>
        <th>Max Drawdown</th>
        <th>Total Return</th>
      </tr>
    </thead>
    <tbody>
{rows_html}
    </tbody>
  </table>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    logger.info("Basic HTML report written to %s", output_path)
