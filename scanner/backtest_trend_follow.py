"""趋势跟踪 + 金字塔 事件驱动回测引擎。

策略规则 (Turtle/Donchian 风格):
  - 入场: 突破过去 entry_n 日最高收盘 + close > EMA(trend_ema)
  - 金字塔: 创新高 + 浮盈 ≥ levels × atr_pyramid_mult × ATR → 加一层
  - 止损: 跌破过去 exit_n 日最低收盘 → 全平
  - 仓位上限: max_positions 个不同币, 每层资金 = 1/max_positions 初始权益
  - 只做多

资金模型:
  starting_equity = 1.0
  per_level_capital = 1.0 / max_positions  (最多 pyramid_levels 层 → 最多 3x 隐含杠杆)
  entry units = per_level_capital / entry_price
  daily NAV = 1 + realized_pnl + Σ unrealized_pnl
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

import pandas as pd

from scanner.trend_follow import atr, donchian_high, donchian_low, is_above_ema


@dataclass
class EntryLot:
    idx: int
    price: float
    units: float


@dataclass
class Position:
    symbol: str
    entries: list[EntryLot] = field(default_factory=list)
    trailing_high: float = 0.0

    @property
    def total_units(self) -> float:
        return sum(e.units for e in self.entries)

    @property
    def total_cost(self) -> float:
        return sum(e.price * e.units for e in self.entries)

    @property
    def avg_price(self) -> float:
        tu = self.total_units
        return self.total_cost / tu if tu > 0 else 0.0

    @property
    def levels(self) -> int:
        return len(self.entries)

    def unrealized_pnl(self, price: float) -> float:
        return sum(e.units * (price - e.price) for e in self.entries)


@dataclass(frozen=True)
class TrendBacktestResult:
    n_trades: int
    n_winning: int
    n_losing: int
    period_returns: list[float] = field(default_factory=list)     # 每笔交易收益率
    equity_curve: list[float] = field(default_factory=lambda: [1.0])
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    avg_holding_days: float = 0.0
    max_concurrent_positions: int = 0
    max_pyramid_levels_reached: int = 0
    entry_n: int = 20
    exit_n: int = 10
    trend_ema: int = 200
    max_positions: int = 10
    pyramid_levels: int = 3
    atr_pyramid_mult: float = 1.0
    atr_period: int = 14


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (e / peak) - 1.0 if peak > 0 else 0.0
        if dd < mdd:
            mdd = dd
    return mdd


def _sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns) < 2:
        return 0.0
    try:
        stdev = statistics.stdev(daily_returns)
    except statistics.StatisticsError:
        return 0.0
    if stdev == 0:
        return 0.0
    mean = statistics.fmean(daily_returns)
    return (mean / stdev) * math.sqrt(365.0)


def run_trend_backtest(
    klines: dict[str, pd.DataFrame],
    entry_n: int = 20,
    exit_n: int = 10,
    trend_ema: int = 200,
    max_positions: int = 10,
    pyramid_levels: int = 3,
    atr_pyramid_mult: float = 1.0,
    atr_period: int = 14,
) -> TrendBacktestResult:
    """趋势跟踪 + 金字塔日级事件驱动回测。

    Returns:
        TrendBacktestResult 含 equity 曲线、交易统计、最大同时持仓数。
    """
    if not klines:
        return TrendBacktestResult(
            n_trades=0, n_winning=0, n_losing=0,
            entry_n=entry_n, exit_n=exit_n, trend_ema=trend_ema,
            max_positions=max_positions, pyramid_levels=pyramid_levels,
            atr_pyramid_mult=atr_pyramid_mult, atr_period=atr_period,
        )

    timeline = max(len(df) for df in klines.values())
    warmup = max(entry_n, exit_n, trend_ema, atr_period) + 1
    if timeline <= warmup:
        return TrendBacktestResult(
            n_trades=0, n_winning=0, n_losing=0,
            entry_n=entry_n, exit_n=exit_n, trend_ema=trend_ema,
            max_positions=max_positions, pyramid_levels=pyramid_levels,
            atr_pyramid_mult=atr_pyramid_mult, atr_period=atr_period,
        )

    level_capital = 1.0 / max_positions
    positions: dict[str, Position] = {}
    realized_pnl = 0.0
    equity: list[float] = []
    trade_returns: list[float] = []
    holding_days: list[int] = []
    n_winning = 0
    n_losing = 0
    max_concurrent = 0
    max_pyramid_reached = 0

    # 初始 equity (warmup 之前)
    equity.append(1.0)

    for idx in range(warmup, timeline):
        # ── Step 1: 对每个持仓检查止损 ──
        to_close: list[str] = []
        for symbol, pos in positions.items():
            df = klines.get(symbol)
            if df is None or len(df) <= idx:
                continue
            close = float(df["close"].iloc[idx])
            # 跌破过去 exit_n 日低点
            ex_low = donchian_low(df["close"], exit_n, up_to=idx - 1, exclude_current=True)
            if not math.isnan(ex_low) and close < ex_low:
                # 全平
                pnl = sum(e.units * (close - e.price) for e in pos.entries)
                realized_pnl += pnl
                # 交易收益率 = pnl / 总成本
                cost = pos.total_cost
                trade_ret = pnl / cost if cost > 0 else 0.0
                trade_returns.append(trade_ret)
                # 持仓天数 = 最后平仓 idx - 第一次入场 idx
                first_entry_idx = min(e.idx for e in pos.entries)
                holding_days.append(idx - first_entry_idx)
                if pnl > 0:
                    n_winning += 1
                else:
                    n_losing += 1
                to_close.append(symbol)
        for s in to_close:
            del positions[s]

        # ── Step 2: 金字塔加仓 (对未被平仓的持仓) ──
        for symbol, pos in positions.items():
            df = klines.get(symbol)
            if df is None or len(df) <= idx:
                continue
            close = float(df["close"].iloc[idx])
            # 更新 trailing_high
            if close > pos.trailing_high:
                pos.trailing_high = close
            if pos.levels >= pyramid_levels:
                continue
            # 条件: 今日创持仓期间新高 + 浮盈 ≥ levels * k * ATR
            if close < pos.trailing_high:
                continue
            a = atr(df, period=atr_period, up_to=idx)
            threshold = pos.avg_price + pos.levels * atr_pyramid_mult * a
            if close >= threshold:
                units = level_capital / close
                pos.entries.append(EntryLot(idx=idx, price=close, units=units))

        # ── Step 3: 未持仓的币尝试入场 ──
        if len(positions) < max_positions:
            for symbol, df in klines.items():
                if symbol in positions:
                    continue
                if len(positions) >= max_positions:
                    break
                if df is None or len(df) <= idx:
                    continue
                if len(df) < warmup:
                    continue
                close = float(df["close"].iloc[idx])
                # 入场条件 1: 突破过去 entry_n 日最高
                entry_hi = donchian_high(
                    df["close"], entry_n, up_to=idx - 1, exclude_current=True
                )
                if math.isnan(entry_hi) or close <= entry_hi:
                    continue
                # 入场条件 2: 大盘过滤
                if not is_above_ema(df["close"], trend_ema, up_to=idx):
                    continue
                units = level_capital / close
                pos = Position(
                    symbol=symbol,
                    entries=[EntryLot(idx=idx, price=close, units=units)],
                    trailing_high=close,
                )
                positions[symbol] = pos

        # ── Step 4: 每日 mark-to-market ──
        unrealized = 0.0
        for symbol, pos in positions.items():
            df = klines.get(symbol)
            if df is None or len(df) <= idx:
                continue
            close = float(df["close"].iloc[idx])
            unrealized += pos.unrealized_pnl(close)
        nav = 1.0 + realized_pnl + unrealized
        equity.append(nav)

        if len(positions) > max_concurrent:
            max_concurrent = len(positions)
        for pos in positions.values():
            if pos.levels > max_pyramid_reached:
                max_pyramid_reached = pos.levels

    # 末期强平剩余持仓 (防止账面盈亏未落地)
    final_idx = timeline - 1
    for symbol, pos in list(positions.items()):
        df = klines.get(symbol)
        if df is None or len(df) <= final_idx:
            continue
        close = float(df["close"].iloc[final_idx])
        pnl = sum(e.units * (close - e.price) for e in pos.entries)
        realized_pnl += pnl
        cost = pos.total_cost
        trade_ret = pnl / cost if cost > 0 else 0.0
        trade_returns.append(trade_ret)
        first_entry_idx = min(e.idx for e in pos.entries)
        holding_days.append(final_idx - first_entry_idx)
        if pnl > 0:
            n_winning += 1
        else:
            n_losing += 1

    n_trades = n_winning + n_losing
    total_return = equity[-1] - 1.0 if equity else 0.0
    days_covered = timeline - warmup
    if days_covered > 0 and equity[-1] > 0:
        annualized = (equity[-1] ** (365.0 / days_covered)) - 1.0
    else:
        annualized = 0.0

    # 日收益序列 (用于夏普)
    daily_rets: list[float] = []
    for i in range(1, len(equity)):
        if equity[i - 1] > 0:
            daily_rets.append(equity[i] / equity[i - 1] - 1.0)

    win_rate = n_winning / n_trades if n_trades > 0 else 0.0
    avg_hold = statistics.fmean(holding_days) if holding_days else 0.0

    return TrendBacktestResult(
        n_trades=n_trades,
        n_winning=n_winning,
        n_losing=n_losing,
        period_returns=trade_returns,
        equity_curve=equity,
        total_return_pct=total_return,
        annualized_return_pct=annualized,
        sharpe_ratio=_sharpe(daily_rets),
        max_drawdown_pct=_max_drawdown(equity),
        win_rate=win_rate,
        avg_holding_days=avg_hold,
        max_concurrent_positions=max_concurrent,
        max_pyramid_levels_reached=max_pyramid_reached,
        entry_n=entry_n,
        exit_n=exit_n,
        trend_ema=trend_ema,
        max_positions=max_positions,
        pyramid_levels=pyramid_levels,
        atr_pyramid_mult=atr_pyramid_mult,
        atr_period=atr_period,
    )
