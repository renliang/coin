import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.execution.engine import ExecutionEngine
from core.risk.manager import ApprovedSignal
from core.strategy.base import Signal
from core.config import ExchangeConfig


def make_approved_signal():
    sig = Signal(
        symbol="BTC-USDT-SWAP",
        direction="long",
        entry_price=50000.0,
        stop_loss=49000.0,
        strategy_id="test_strategy",
    )
    return ApprovedSignal(signal=sig, size=0.1, leverage=2.0)


@pytest.fixture
def engine(tmp_path):
    cfg = ExchangeConfig(id="okx", sandbox=True)
    eng = ExecutionEngine(cfg, db_path=str(tmp_path / "test.db"))
    eng.exchange = AsyncMock()
    eng.exchange.create_order.return_value = {
        "id": "order123",
        "average": 50000.0,
    }
    eng.exchange.set_leverage = AsyncMock()
    return eng


@pytest.mark.asyncio
async def test_open_position_creates_order(engine):
    approved = make_approved_signal()
    order = await engine.execute(approved)
    assert order is not None
    assert order.status == "OPEN"
    assert order.okx_order_id == "order123"


@pytest.mark.asyncio
async def test_close_position_requires_open_position(engine):
    from core.strategy.base import Signal
    close_sig = Signal(
        symbol="BTC-USDT-SWAP",
        direction="close",
        entry_price=51000.0,
        stop_loss=0.0,
        strategy_id="nonexistent",
    )
    approved = ApprovedSignal(signal=close_sig, size=0.1, leverage=1.0)
    result = await engine.execute(approved)
    assert result is None  # 没有持仓，返回 None
