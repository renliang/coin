import numpy as np
import pandas as pd
import pytest
from core.backtest.engine import BacktestEngine, BacktestResult
from core.strategy.templates.breakout import BreakoutStrategy
from core.config import RiskConfig


def make_sinusoidal_df(n=300):
    """生成带趋势的正弦波价格数据"""
    t = np.linspace(0, 6 * np.pi, n)
    prices = 100 + 20 * np.sin(t) + t * 0.5
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": [1000.0] * n,
    }, index=pd.date_range("2024-01-01", periods=n, freq="1h"))


def test_backtest_runs_without_error():
    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 10})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(make_sinusoidal_df())
    assert isinstance(result, BacktestResult)


def test_backtest_result_properties():
    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 10})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(make_sinusoidal_df(300))
    assert 0.0 <= result.win_rate <= 1.0
    assert result.max_drawdown >= 0.0
    assert isinstance(result.total_return, float)


def test_backtest_sharpe_and_annualized():
    strategy = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 10})
    risk = RiskConfig(max_risk_per_trade=0.01, max_open_positions=1, daily_loss_limit=0.2, max_leverage=5.0)
    engine = BacktestEngine(strategy, risk, initial_balance=10000.0)
    result = engine.run(make_sinusoidal_df(300))
    assert isinstance(result.sharpe_ratio, float)
    assert isinstance(result.annualized_return, float)


def test_backtest_with_no_signals():
    """数据太少时不应崩溃"""
    from core.strategy.templates.momentum import MomentumStrategy
    strategy = MomentumStrategy("m1", "BTC-USDT-SWAP", "1h")
    risk = RiskConfig()
    engine = BacktestEngine(strategy, risk)
    short_df = make_sinusoidal_df(10)
    result = engine.run(short_df)
    assert len(result.trades) == 0
