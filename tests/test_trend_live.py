"""Live execute 测试 — 用 mock exchange 验证下单顺序、错误回滚、DB 一致性。"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import scanner.trend_position_store as store
from scanner.trend_live import live_execute
from scanner.trend_scanner import ScanTrendResult, TrendAction


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "live.db")
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_schema()
    yield db_path


@pytest.fixture
def mock_exchange():
    ex = MagicMock()
    # 基础 fetch_ticker 返回一个 ticker
    ex.fetch_ticker.return_value = {"last": 100.0, "close": 100.0}
    # amount_to_precision 直接 round 一下
    ex.amount_to_precision.side_effect = lambda sym, amt: f"{amt:.6f}"
    # 市价单返回成交信息
    ex.create_order.side_effect = lambda **kw: _simulate_order(ex, kw)
    ex.cancel_order.return_value = {}
    ex.set_leverage.return_value = {}
    ex.fetch_positions.return_value = []
    return ex


def _simulate_order(ex, kw):
    """根据订单类型返回伪造的订单结构。"""
    order_type = kw.get("type", "")
    if order_type == "STOP_MARKET":
        return {"id": f"sl-{kw['symbol']}-{kw['amount']}"}
    # market buy/sell
    price = 100.0  # 假设成交价
    return {
        "id": f"ord-{kw['symbol']}-{kw['side']}",
        "average": price,
        "filled": float(kw["amount"]),
        "price": price,
    }


def _entry(symbol, price=100.0, atr=2.0):
    return TrendAction(action_type="entry", symbol=symbol, price=price,
                       reason="breakout", atr=atr, trailing_high=price, new_level=1,
                       donchian_high=price * 0.95, donchian_low=price * 0.85,
                       chandelier_stop=price - 3 * atr, stop_price=price - 3 * atr)


def _pyramid(symbol, price=110.0, atr=2.0, new_level=2, trailing_high=110.0):
    return TrendAction(action_type="pyramid", symbol=symbol, price=price,
                       reason="atr_pyramid", atr=atr, trailing_high=trailing_high,
                       new_level=new_level)


def _exit(symbol, price=95.0, reason="chandelier_stop", trailing_high=120.0):
    return TrendAction(action_type="exit", symbol=symbol, price=price, reason=reason,
                       atr=2.0, trailing_high=trailing_high,
                       stop_price=trailing_high - 6.0, chandelier_stop=trailing_high - 6.0)


def test_live_execute_opens_position_with_safety_sl(mock_exchange):
    result = ScanTrendResult(entries=[_entry("X/USDT", 100.0, 2.0)],
                             pyramid_adds=[], exits=[])
    applied = live_execute(result, mock_exchange, notional_per_level=20.0,
                           leverage=10, sl_multiplier=5.0, today="2026-04-23")
    assert len(applied["opened"]) == 1
    # 验证: set_leverage + market buy + STOP_MARKET 三次 create_order
    assert mock_exchange.set_leverage.called
    calls = mock_exchange.create_order.call_args_list
    types = [c.kwargs.get("type") for c in calls]
    assert "market" in types
    assert "STOP_MARKET" in types
    # DB 存了 SL 订单 ID
    p = store.get_position("X/USDT")
    assert p is not None
    assert p.safety_sl_order_id is not None and p.safety_sl_order_id != ""


def test_live_execute_closes_cancels_safety_sl(mock_exchange):
    store.open_position("X/USDT", 100.0, 0.2, 2.0, "2026-04-20",
                         safety_sl_order_id="old-sl-123")
    result = ScanTrendResult(entries=[], pyramid_adds=[],
                             exits=[_exit("X/USDT", 95.0)])
    live_execute(result, mock_exchange, notional_per_level=20.0, leverage=10,
                 sl_multiplier=5.0, today="2026-04-23")
    # 取消旧 SL
    mock_exchange.cancel_order.assert_any_call("old-sl-123", "X/USDT")
    # 市价平多 reduceOnly
    sell_calls = [c for c in mock_exchange.create_order.call_args_list
                  if c.kwargs.get("side") == "sell" and c.kwargs.get("type") == "market"]
    assert len(sell_calls) == 1
    assert sell_calls[0].kwargs["params"].get("reduceOnly") is True
    # DB: 平仓入账
    p = store.get_position("X/USDT")
    assert p.status == "closed"


def test_live_execute_pyramid_reissues_sl(mock_exchange):
    store.open_position("X/USDT", 100.0, 0.2, 2.0, "2026-04-20",
                         safety_sl_order_id="old-sl-xxx")
    # 模拟加仓后交易所返回总持仓量 (0.4 币 = 原 0.2 + 新 0.2)
    mock_exchange.fetch_positions.return_value = [{"contracts": 0.4, "symbol": "X/USDT"}]
    result = ScanTrendResult(entries=[], exits=[],
                             pyramid_adds=[_pyramid("X/USDT", 110.0, 2.0, 2, 110.0)])
    applied = live_execute(result, mock_exchange, notional_per_level=20.0,
                           leverage=10, sl_multiplier=5.0, today="2026-04-23")
    assert len(applied["added"]) == 1
    # 旧 SL 被取消
    mock_exchange.cancel_order.assert_any_call("old-sl-xxx", "X/USDT")
    # 新 SL 被挂 (出现 STOP_MARKET 调用)
    sl_calls = [c for c in mock_exchange.create_order.call_args_list
                if c.kwargs.get("type") == "STOP_MARKET"]
    assert len(sl_calls) >= 1
    # DB: 层数变 2, SL order_id 已更新
    p = store.get_position("X/USDT")
    assert p.levels == 2
    assert p.safety_sl_order_id is not None


def test_live_execute_idempotent_same_day_pyramid(mock_exchange):
    store.open_position("X/USDT", 100.0, 0.2, 2.0, "2026-04-20")
    result = ScanTrendResult(entries=[], exits=[],
                             pyramid_adds=[_pyramid("X/USDT", 110.0, 2.0, 2)])
    live_execute(result, mock_exchange, notional_per_level=20.0, leverage=10,
                 sl_multiplier=5.0, today="2026-04-23")
    call_count_1 = mock_exchange.create_order.call_count
    # 同日再跑一次
    live_execute(result, mock_exchange, notional_per_level=20.0, leverage=10,
                 sl_multiplier=5.0, today="2026-04-23")
    # 不应再次下单
    assert mock_exchange.create_order.call_count == call_count_1
    assert store.get_position("X/USDT").levels == 2


def test_live_execute_handles_open_failure(mock_exchange):
    """开仓失败时不应写 DB, 错误被记录到 errors。"""
    import ccxt
    # 让第一次市价开单抛异常
    def failing_order(**kw):
        if kw.get("type") == "market" and kw.get("side") == "buy":
            raise ccxt.InsufficientFunds("NO MONEY")
        return _simulate_order(mock_exchange, kw)
    mock_exchange.create_order.side_effect = failing_order

    result = ScanTrendResult(entries=[_entry("X/USDT")], pyramid_adds=[], exits=[])
    applied = live_execute(result, mock_exchange, notional_per_level=20.0,
                           leverage=10, sl_multiplier=5.0, today="2026-04-23")
    assert applied["opened"] == []
    assert len(applied["errors"]) == 1
    assert applied["errors"][0]["action"] == "open"
    # DB 里不该有 X/USDT 的 open 仓
    assert store.get_position("X/USDT") is None


def test_live_execute_skip_exit_when_position_missing(mock_exchange):
    result = ScanTrendResult(entries=[], pyramid_adds=[],
                             exits=[_exit("GHOST/USDT")])
    applied = live_execute(result, mock_exchange, notional_per_level=20.0,
                           leverage=10, sl_multiplier=5.0, today="2026-04-23")
    assert applied["closed"] == []
    assert applied["errors"] == []  # 不算错误, 只是跳过


def test_live_execute_ordering_exit_before_entry(mock_exchange):
    """平仓先于开仓执行 (避免达到仓位上限时新仓被卡)。"""
    store.open_position("X/USDT", 100.0, 0.2, 2.0, "2026-04-20",
                         safety_sl_order_id="sl-old")
    result = ScanTrendResult(
        entries=[_entry("Y/USDT")],
        pyramid_adds=[],
        exits=[_exit("X/USDT", 95.0)],
    )
    applied = live_execute(result, mock_exchange, notional_per_level=20.0,
                           leverage=10, sl_multiplier=5.0, today="2026-04-23")
    assert len(applied["closed"]) == 1
    assert len(applied["opened"]) == 1
    assert store.get_position("X/USDT").status == "closed"
    assert store.get_position("Y/USDT").status == "open"
