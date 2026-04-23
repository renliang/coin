"""趋势跟踪 + 金字塔 回测测试。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scanner.backtest_trend_follow import (
    TrendBacktestResult,
    run_trend_backtest,
)


def _klines(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    # high/low 围绕 close 小幅波动以产生合理 ATR
    highs = [c * 1.02 for c in closes]
    lows = [c * 0.98 for c in closes]
    return pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=n, freq="D"),
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1_000_000.0] * n,
    })


def test_empty_input_returns_zero_result():
    out = run_trend_backtest({})
    assert isinstance(out, TrendBacktestResult)
    assert out.n_trades == 0
    assert out.equity_curve == [1.0]


def test_persistent_uptrend_enters_and_profits():
    """持续上涨的币应入场, 吃到大部分涨幅, 正收益。"""
    # 400 天线性上涨, 足够 EMA200 爬升并让 close 保持 MA 之上
    closes = np.linspace(10.0, 100.0, 400).tolist()
    klines = {"X/USDT": _klines(closes)}
    out = run_trend_backtest(
        klines,
        entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3,
        atr_pyramid_mult=1.0,
    )
    assert out.n_trades >= 1
    # 单币全仓一路持有, 至少收益占初始仓位规模的正值
    assert out.total_return_pct > 0


def test_stop_triggers_on_donchian_low_break():
    """入场后突然大跌穿 10 日低点应触发止损平仓。"""
    # 构造: 前 300 天持续上涨 (确保能入场), 最后 20 天急跌
    up = np.linspace(10.0, 100.0, 300).tolist()
    down = np.linspace(100.0, 30.0, 20).tolist()
    closes = up + down
    klines = {"X/USDT": _klines(closes)}
    out = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3,
    )
    # 必须有至少一笔完整平仓的交易
    assert out.n_trades >= 1


def test_ema_filter_blocks_entry_in_bear_market():
    """EMA200 下方不入场 — 熊市反弹不诱惑。"""
    # 前 250 天下跌 200→50, 随后反弹到 80 但仍在 EMA200 下方
    down = np.linspace(200.0, 50.0, 250).tolist()
    rebound = np.linspace(50.0, 80.0, 50).tolist()
    closes = down + rebound
    klines = {"X/USDT": _klines(closes)}
    out = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3,
    )
    # EMA200 一直远高于当前价, 任何突破都应被 EMA 拦截
    assert out.n_trades == 0
    assert out.total_return_pct == 0.0


def test_pyramid_adds_levels_on_continued_new_highs():
    """持续创新高 + 浮盈达 ATR 倍数 → 应加仓到多层。"""
    # 300 天先平 (让 EMA 追上), 然后陡峭上涨创连续新高
    flat = [50.0] * 250
    # 后续强势连涨, 每天 +1
    rising = [50.0 + i for i in range(1, 101)]  # 51..150
    closes = flat + rising
    klines = {"X/USDT": _klines(closes)}
    out = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3,
        atr_pyramid_mult=0.5,  # 低门槛更容易加仓
    )
    # 至少开了一个仓位, 且最大同时持有的 level 数 > 1
    assert out.max_pyramid_levels_reached >= 2


def test_max_positions_capped():
    """超过 max_positions 的信号应被忽略。"""
    closes = np.linspace(10.0, 100.0, 400).tolist()
    # 15 个完全同步上涨的币
    klines = {f"S{i}/USDT": _klines(closes) for i in range(15)}
    out = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=1,
    )
    # 任意时刻持仓不应超过 10
    assert out.max_concurrent_positions <= 10


def test_chandelier_stop_triggers_on_giving_back_gains():
    """入场后大涨到顶部, 回落超过 chandelier_mult × ATR 即触发 trailing stop,
    应在 Donchian 低点止损之前更早退出, 减少回撤。"""
    # 400 天上涨 (确保 EMA200 过滤通过 + 突破入场)
    up = np.linspace(10.0, 120.0, 400).tolist()
    # 接着急跌但不跌破 10 日低点 (Donchian 低点止损不会立即触发,
    # 但 chandelier 应基于 trailing_high 已经退出)
    dip = np.linspace(120.0, 95.0, 5).tolist()
    closes = up + dip
    klines = {"X/USDT": _klines(closes)}

    with_chandelier = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3, atr_pyramid_mult=1.0,
        chandelier_mult=3.0,
    )
    without_chandelier = run_trend_backtest(
        klines, entry_n=20, exit_n=10, trend_ema=200,
        max_positions=10, pyramid_levels=3, atr_pyramid_mult=1.0,
        chandelier_mult=0.0,
    )
    # chandelier 启用时, 最大回撤应不大于禁用时 (即回撤更小)
    assert with_chandelier.max_drawdown_pct >= without_chandelier.max_drawdown_pct


def test_chandelier_mult_zero_preserves_original_behavior():
    """chandelier_mult=0 时止损仅用 Donchian 低点, 行为与旧版等价。"""
    closes = np.linspace(10.0, 100.0, 400).tolist()
    klines = {"X/USDT": _klines(closes)}
    a = run_trend_backtest(klines, chandelier_mult=0.0)
    b = run_trend_backtest(klines)  # 默认 chandelier_mult=0.0
    assert a.total_return_pct == pytest.approx(b.total_return_pct, rel=1e-9)


def test_result_is_frozen():
    out = run_trend_backtest({})
    with pytest.raises(Exception):
        out.total_return_pct = 1.0  # type: ignore[misc]
