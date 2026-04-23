"""状态感知趋势扫描: 产出 entry/pyramid/exit 三类信号。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.trend_position_store import Entry, TrendPosition
from scanner.trend_scanner import ScanTrendResult, scan_trend_actions


def _klines(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes,
        "high": [c * 1.02 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def _btc_bull(n: int = 300) -> pd.DataFrame:
    return _klines(np.linspace(20000.0, 60000.0, n).tolist())


def _btc_bear(n: int = 300) -> pd.DataFrame:
    return _klines(np.linspace(60000.0, 20000.0, n).tolist())


def _fake_position(
    symbol: str,
    entries: list[tuple[str, float, float]],  # (date, price, units)
    trailing_high: float,
    atr_at_open: float = 2.0,
    status: str = "open",
) -> TrendPosition:
    """构造用于测试的 TrendPosition (不入库)。"""
    return TrendPosition(
        id=1,
        symbol=symbol,
        entries=[Entry(date=d, price=p, units=u) for d, p, u in entries],
        trailing_high=trailing_high,
        atr_at_open=atr_at_open,
        opened_at=entries[0][0],
        status=status,
    )


def test_no_positions_entries_only():
    closes = [50.0] * 300 + [80.0]
    klines = {"X/USDT": _klines(closes)}
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=[],
        entry_n=30, trend_ema=200, btc_trend_ema=100,
    )
    assert len(out.entries) == 1
    assert out.entries[0].symbol == "X/USDT"
    assert out.entries[0].action_type == "entry"
    assert out.pyramid_adds == []
    assert out.exits == []


def test_pyramid_trigger_when_new_high_and_atr_threshold():
    """已持仓, 今日创新高且浮盈 ≥ levels × 1 × ATR → 触发加仓信号。"""
    # 构造: 前 300 天平, 最后一天涨到 108
    closes = [100.0] * 300 + [108.0]
    klines = {"X/USDT": _klines(closes)}
    pos = _fake_position(
        "X/USDT",
        entries=[("2026-04-01", 100.0, 1.0)],
        trailing_high=100.0,
        atr_at_open=2.0,
    )
    # ATR14 在该场景下应 ~ 2 (high/low 各 2% × 100)
    # levels=1, threshold = avg_price + 1 × ATR ≈ 100 + 2 = 102
    # 今日 close 108 > 102 ✓, 且 108 > trailing_high 100 ✓
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=[pos],
        entry_n=30, trend_ema=200, btc_trend_ema=100,
        pyramid_levels=3, atr_pyramid_mult=1.0,
    )
    assert len(out.pyramid_adds) == 1
    add = out.pyramid_adds[0]
    assert add.symbol == "X/USDT"
    assert add.action_type == "pyramid"
    assert add.price == pytest.approx(108.0)
    assert add.new_level == 2  # 加完变 2 层


def test_pyramid_not_triggered_if_max_levels():
    closes = [100.0] * 300 + [108.0]
    klines = {"X/USDT": _klines(closes)}
    # 已经 3 层
    pos = _fake_position(
        "X/USDT",
        entries=[("2026-04-01", 100.0, 1.0),
                 ("2026-04-05", 102.0, 1.0),
                 ("2026-04-10", 105.0, 1.0)],
        trailing_high=108.0,
    )
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=[pos],
        pyramid_levels=3, atr_pyramid_mult=1.0,
    )
    assert out.pyramid_adds == []


def test_exit_triggered_by_chandelier_stop():
    """持仓期最高 120, 今日大跌破 chandelier (120 - 3×ATR) → 触发平仓信号。"""
    # 前 300 天 100, 最近几天冲到 120, 今天跌到 100
    closes = [100.0] * 300 + [100.0]  # 今天 100
    klines = {"X/USDT": _klines(closes)}
    pos = _fake_position(
        "X/USDT",
        entries=[("2026-04-01", 100.0, 1.0)],
        trailing_high=120.0,  # 持仓期曾达 120
        atr_at_open=5.0,
    )
    # chandelier_stop = 120 - 3 × ATR ≈ 120 - 6 = 114 (如果 ATR=2)
    # close 100 < 114 → 触发
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=[pos],
        chandelier_mult=3.0,
    )
    assert len(out.exits) == 1
    ex = out.exits[0]
    assert ex.symbol == "X/USDT"
    assert ex.action_type == "exit"
    assert ex.reason in ("chandelier_stop", "donchian_stop")


def test_exit_triggered_by_donchian_low_break():
    """跌破过去 15 日最低收盘 → Donchian 止损。"""
    closes = list(range(100, 100 + 300))  # 100..399 上涨
    closes.append(350.0)  # 今天大跌破过去 15 日最低 (约 384 + 15 = 399-15=384)
    klines = {"X/USDT": _klines(closes)}
    pos = _fake_position(
        "X/USDT",
        entries=[("2026-04-01", 300.0, 0.5)],
        trailing_high=399.0,
    )
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=[pos],
        exit_n=15, chandelier_mult=0.0,  # 禁用 chand, 只看 Donch
    )
    assert len(out.exits) == 1
    assert out.exits[0].reason == "donchian_stop"


def test_btc_weak_blocks_entries_and_pyramid_not_exits():
    """BTC 弱势: 不出入场信号、不出加仓信号, 但止损仍会触发。"""
    closes = [100.0] * 300 + [80.0]  # 今天跌
    klines = {"X/USDT": _klines(closes), "Y/USDT": _klines([30.0] * 300 + [50.0])}
    pos = _fake_position(
        "X/USDT",
        entries=[("2026-04-01", 100.0, 1.0)],
        trailing_high=110.0,   # 曾达 110, 现在 80 → chand=110-6=104, 80<104 触发
        atr_at_open=2.0,
    )
    out = scan_trend_actions(
        klines, btc_df=_btc_bear(), positions=[pos],
        chandelier_mult=3.0,
    )
    assert out.entries == []         # BTC 熊不入场
    assert out.pyramid_adds == []    # BTC 熊不加仓
    assert len(out.exits) == 1       # 但止损仍触发


def test_max_positions_cap_limits_entries():
    """已有 10 个 open 持仓, 不出新入场信号。"""
    closes = [50.0] * 300 + [80.0]
    klines = {f"S{i}/USDT": _klines(closes) for i in range(5)}
    existing = [
        _fake_position(f"HELD{i}/USDT", [("2026-04-01", 100.0, 1.0)], 100.0)
        for i in range(10)
    ]
    out = scan_trend_actions(
        klines, btc_df=_btc_bull(), positions=existing,
        max_positions=10,
    )
    assert out.entries == []


def test_no_entry_for_already_held_symbol():
    """持仓币即使再触发入场条件, 也不重复开仓 (应走金字塔路径)。"""
    closes = [50.0] * 300 + [80.0]
    klines = {"X/USDT": _klines(closes)}
    pos = _fake_position("X/USDT", [("2026-04-01", 50.0, 1.0)], 50.0, atr_at_open=2.0)
    out = scan_trend_actions(klines, btc_df=_btc_bull(), positions=[pos])
    assert out.entries == []


def test_returns_scan_result_type():
    out = scan_trend_actions({}, btc_df=_btc_bull(), positions=[])
    assert isinstance(out, ScanTrendResult)
    assert out.entries == []
    assert out.pyramid_adds == []
    assert out.exits == []
