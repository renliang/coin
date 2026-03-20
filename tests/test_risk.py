import pytest
from core.risk.manager import RiskManager
from core.strategy.base import Signal
from core.config import RiskConfig


def make_risk_manager(balance=10000.0):
    cfg = RiskConfig(max_risk_per_trade=0.01, max_open_positions=3, daily_loss_limit=0.05, max_leverage=5.0)
    rm = RiskManager(cfg)
    rm.update_account(balance=balance, daily_pnl=0.0, open_positions=0)
    return rm


def make_signal(direction="long", entry=50000.0, sl=49000.0):
    return Signal(symbol="BTC-USDT-SWAP", direction=direction, entry_price=entry, stop_loss=sl, strategy_id="test")


def test_normal_signal_approved():
    rm = make_risk_manager()
    result = rm.evaluate(make_signal())
    assert result is not None
    assert result.size > 0


def test_size_calculation():
    rm = make_risk_manager(balance=10000.0)
    # risk = 10000 * 0.01 = 100 USDT
    # price_risk = 50000 - 49000 = 1000
    # size = 100 / 1000 = 0.1
    result = rm.evaluate(make_signal(entry=50000.0, sl=49000.0))
    assert result is not None
    assert abs(result.size - 0.1) < 0.001


def test_daily_loss_limit_blocks_signal():
    rm = make_risk_manager(balance=10000.0)
    rm.update_account(balance=10000.0, daily_pnl=-600.0, open_positions=0)  # -6% 超过 5% 上限
    result = rm.evaluate(make_signal())
    assert result is None


def test_max_positions_blocks_signal():
    rm = make_risk_manager()
    rm.update_account(balance=10000.0, daily_pnl=0.0, open_positions=3)
    result = rm.evaluate(make_signal())
    assert result is None


def test_zero_balance_blocks_signal():
    rm = make_risk_manager(balance=0.0)
    result = rm.evaluate(make_signal())
    assert result is None


def test_leverage_cap_reduces_size():
    rm = make_risk_manager(balance=1000.0)  # 小余额，容易超杠杆
    result = rm.evaluate(make_signal(entry=50000.0, sl=49990.0))  # 很小的止损距离
    assert result is not None
    assert result.leverage <= 5.0
