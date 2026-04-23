"""横截面动量 CSM 回测测试。"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from scanner.backtest_momentum import (
    MomentumBacktestResult,
    run_momentum_backtest,
)


def _klines_from_close(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=n, freq="D"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1_000_000.0] * n,
        }
    )


def test_empty_input_returns_zero_result():
    out = run_momentum_backtest(
        {},
        lookback_days=30,
        trend_ma_period=50,
        top_n=10,
        rebalance_every_days=7,
    )
    assert isinstance(out, MomentumBacktestResult)
    assert out.n_rebalances == 0
    assert out.period_returns == []
    assert out.equity_curve == [1.0]


def test_all_rising_produces_positive_return():
    """全市场统一上涨，组合必然正收益。"""
    # 构造 120 天日线，所有币都从 100 线性涨到 200 (+100%)
    closes = np.linspace(100.0, 200.0, 120).tolist()
    klines = {f"S{i}/USDT": _klines_from_close(closes) for i in range(5)}

    out = run_momentum_backtest(
        klines,
        lookback_days=30,
        trend_ma_period=50,
        top_n=3,
        rebalance_every_days=7,
    )
    assert out.n_rebalances > 0
    assert out.total_return_pct > 0
    # 等权持仓且所有币同步涨，总收益应接近单币收益
    # 单币 120 天 +100%, 从第 50 天左右开始持有 ≈ 60-70% 末期收益
    assert out.total_return_pct > 0.3


def test_all_falling_produces_zero_holdings():
    """全市场下跌时，趋势过滤会让所有币都不合格 → 空仓 → 收益 ~0。"""
    closes = np.linspace(200.0, 50.0, 120).tolist()
    klines = {f"S{i}/USDT": _klines_from_close(closes) for i in range(5)}

    out = run_momentum_backtest(
        klines,
        lookback_days=30,
        trend_ma_period=50,
        top_n=3,
        rebalance_every_days=7,
    )
    # 所有币都在 MA 下方 → 每期都空仓 → 资金曲线平
    assert out.total_return_pct == pytest.approx(0.0, abs=1e-9)
    assert all(r == pytest.approx(0.0, abs=1e-9) for r in out.period_returns)


def test_picks_strongest_momentum():
    """STRONG 涨得最猛，应被选入持仓，带动组合跑赢纯基准组合。"""
    base_closes = np.linspace(100.0, 120.0, 120).tolist()
    strong_closes = np.linspace(100.0, 300.0, 120).tolist()
    base_only = {f"BASE{i}/USDT": _klines_from_close(base_closes) for i in range(5)}
    with_strong = dict(base_only)
    with_strong["STRONG/USDT"] = _klines_from_close(strong_closes)

    out_base = run_momentum_backtest(base_only, lookback_days=30, trend_ma_period=50,
                                     top_n=2, rebalance_every_days=7)
    out_strong = run_momentum_backtest(with_strong, lookback_days=30, trend_ma_period=50,
                                       top_n=2, rebalance_every_days=7)

    # 加入 STRONG 后组合收益必须显著高于纯基准
    assert out_strong.total_return_pct > out_base.total_return_pct
    assert out_strong.total_return_pct - out_base.total_return_pct > 0.1


def test_equity_curve_lengths():
    closes = np.linspace(100.0, 200.0, 120).tolist()
    klines = {f"S{i}/USDT": _klines_from_close(closes) for i in range(3)}
    out = run_momentum_backtest(
        klines,
        lookback_days=30,
        trend_ma_period=50,
        top_n=3,
        rebalance_every_days=7,
    )
    assert len(out.equity_curve) == out.n_rebalances + 1
    assert len(out.period_returns) == out.n_rebalances
    assert out.equity_curve[0] == 1.0


def test_max_drawdown_is_nonpositive():
    closes = np.linspace(100.0, 200.0, 120).tolist()
    klines = {f"S{i}/USDT": _klines_from_close(closes) for i in range(3)}
    out = run_momentum_backtest(
        klines,
        lookback_days=30,
        trend_ma_period=50,
        top_n=3,
        rebalance_every_days=7,
    )
    assert out.max_drawdown_pct <= 0.0


def test_annualized_return_matches_short_backtest():
    """短回测（90 天）时年化应放大。"""
    closes = np.linspace(100.0, 200.0, 120).tolist()
    klines = {f"S{i}/USDT": _klines_from_close(closes) for i in range(3)}
    out = run_momentum_backtest(
        klines,
        lookback_days=30,
        trend_ma_period=50,
        top_n=3,
        rebalance_every_days=7,
    )
    # 短期的高收益应年化放大到 > 总收益
    if out.total_return_pct > 0 and out.n_rebalances < 50:
        assert out.annualized_return_pct > out.total_return_pct


def test_result_is_frozen():
    out = run_momentum_backtest({}, lookback_days=30, trend_ma_period=50, top_n=10,
                                rebalance_every_days=7)
    with pytest.raises(Exception):
        out.total_return_pct = 1.0  # type: ignore[misc]
