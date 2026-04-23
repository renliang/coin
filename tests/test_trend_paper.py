"""Paper trading 执行器测试 — 把 ScanTrendResult 应用到 DB (不下真单)。"""
from __future__ import annotations

import pandas as pd
import pytest

import scanner.trend_position_store as store
from scanner.trend_paper import paper_execute, update_all_trailing_highs
from scanner.trend_scanner import ScanTrendResult, TrendAction


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "paper.db")
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_schema()
    yield db_path


def _entry(symbol, price=100.0, atr=2.0):
    return TrendAction(action_type="entry", symbol=symbol, price=price,
                       reason="breakout", atr=atr, trailing_high=price,
                       new_level=1, donchian_high=price * 0.95,
                       donchian_low=price * 0.85,
                       chandelier_stop=price - 3 * atr,
                       stop_price=price - 3 * atr)


def _pyramid(symbol, price=110.0, atr=2.0, new_level=2):
    return TrendAction(action_type="pyramid", symbol=symbol, price=price,
                       reason="atr_pyramid", atr=atr, trailing_high=price,
                       new_level=new_level)


def _exit(symbol, price=95.0, reason="chandelier_stop", atr=2.0, trailing_high=120.0):
    return TrendAction(action_type="exit", symbol=symbol, price=price,
                       reason=reason, atr=atr, trailing_high=trailing_high,
                       stop_price=trailing_high - 3 * atr,
                       chandelier_stop=trailing_high - 3 * atr)


def test_paper_execute_opens_new_positions():
    result = ScanTrendResult(
        entries=[_entry("X/USDT", 100.0, 2.0)],
        pyramid_adds=[], exits=[],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert len(applied["opened"]) == 1
    assert applied["opened"][0]["symbol"] == "X/USDT"
    # 验证入库
    p = store.get_position("X/USDT")
    assert p is not None and p.status == "open"
    # units = level_capital / price = 0.1 / 100 = 0.001
    assert p.entries[0].units == pytest.approx(0.001)


def test_paper_execute_adds_pyramid():
    store.open_position("X/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    result = ScanTrendResult(
        entries=[],
        pyramid_adds=[_pyramid("X/USDT", 110.0, 2.0, new_level=2)],
        exits=[],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert len(applied["added"]) == 1
    p = store.get_position("X/USDT")
    assert p.levels == 2


def test_paper_execute_closes_on_exit_signal():
    store.open_position("X/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    result = ScanTrendResult(
        entries=[], pyramid_adds=[],
        exits=[_exit("X/USDT", 95.0, "chandelier_stop")],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert len(applied["closed"]) == 1
    assert applied["closed"][0]["reason"] == "chandelier_stop"
    p = store.get_position("X/USDT")
    assert p.status == "closed"
    assert p.realized_pnl_pct == pytest.approx(-0.05)


def test_paper_execute_handles_exit_before_entry():
    """平仓先处理, 入场后处理 — 即使 signal 列表顺序不同也不乱。"""
    store.open_position("X/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    result = ScanTrendResult(
        entries=[_entry("Y/USDT", 50.0)],
        pyramid_adds=[],
        exits=[_exit("X/USDT", 95.0)],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert len(applied["closed"]) == 1
    assert len(applied["opened"]) == 1
    # X 已平, Y 已开
    assert store.get_position("X/USDT").status == "closed"
    assert store.get_position("Y/USDT").status == "open"


def test_paper_execute_idempotent_same_day_pyramid():
    """同一天连跑两次, 加仓不应重复写入。"""
    store.open_position("X/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    result = ScanTrendResult(
        entries=[], pyramid_adds=[_pyramid("X/USDT", 110.0, 2.0, 2)], exits=[],
    )
    paper_execute(result, today="2026-04-23", level_capital=0.1)
    paper_execute(result, today="2026-04-23", level_capital=0.1)  # 再跑一次
    p = store.get_position("X/USDT")
    assert p.levels == 2, f"同日重复加仓应被防御, 结果是 {p.levels}"


def test_paper_execute_skip_exit_when_no_open_position():
    """信号说 exit 但实际没有该币的 open 仓 (可能已被之前平掉) → 安静跳过。"""
    result = ScanTrendResult(
        entries=[], pyramid_adds=[],
        exits=[_exit("GHOST/USDT", 95.0)],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert applied["closed"] == []


def test_paper_execute_skip_duplicate_open():
    """同币已 open, entries 信号应被跳过。"""
    store.open_position("X/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    result = ScanTrendResult(
        entries=[_entry("X/USDT", 105.0)], pyramid_adds=[], exits=[],
    )
    applied = paper_execute(result, today="2026-04-23", level_capital=0.1)
    assert applied["opened"] == []
    # 原仓不变
    p = store.get_position("X/USDT")
    assert p.levels == 1


def test_update_trailing_highs_raises_high_only():
    """update_all_trailing_highs 用今日 close 更新所有 open 持仓。"""
    store.open_position("A/USDT", 100.0, 0.001, 2.0, "2026-04-20")
    store.open_position("B/USDT", 50.0, 0.001, 1.0, "2026-04-20")

    klines = {
        "A/USDT": pd.DataFrame({
            "timestamp": pd.date_range("2026-04-23", periods=1, freq="D"),
            "open": [1], "high": [1], "low": [1],
            "close": [115.0], "volume": [1],
        }),
        "B/USDT": pd.DataFrame({
            "timestamp": pd.date_range("2026-04-23", periods=1, freq="D"),
            "open": [1], "high": [1], "low": [1],
            "close": [40.0], "volume": [1],
        }),
    }
    update_all_trailing_highs(klines)
    # A 的 trailing_high 应被上调到 115
    # B 的今日价 40 < 原 50, 不应下调
    assert store.get_position("A/USDT").trailing_high == 115.0
    assert store.get_position("B/USDT").trailing_high == 50.0
