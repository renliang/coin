"""横截面动量 (CSM) 周度再平衡回测引擎。

与 scanner/backtest.py 的形态回测不同，这是**组合级**时序回测:
  - 每 rebalance_every_days 天重扫全市场, 按动量排序取 Top N
  - 等权持仓, 下一期按持仓币种的实际收益加权求和
  - 未选中币或当期空仓时, 对应期收益为 0 (现金仓)

不含手续费/滑点/杠杆 - 先纯信号评估, 后续可叠加。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import math

import pandas as pd

from scanner.momentum import rank_by_momentum


@dataclass(frozen=True)
class MomentumBacktestResult:
    n_rebalances: int
    period_returns: list[float] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=lambda: [1.0])
    total_return_pct: float = 0.0
    annualized_return_pct: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    lookback_days: int = 30
    trend_ma_period: int = 50
    top_n: int = 10
    rebalance_every_days: int = 7
    btc_trend_ema: int = 0      # 0 表示未启用大盘过滤
    n_btc_blocked: int = 0       # 因 BTC 熊市被过滤掉的期数


def _btc_is_bullish(btc_df: pd.DataFrame, idx: int, ema_period: int) -> bool:
    """BTC 在 idx 时是否处于牛市 (close > EMA_period)。数据不足返回 False。"""
    if len(btc_df) <= idx or idx < ema_period:
        return False
    closes = btc_df["close"].iloc[: idx + 1].astype(float)
    ema = closes.ewm(span=ema_period, adjust=False).mean().iloc[-1]
    return float(closes.iloc[-1]) > float(ema)


def _timeline_length(klines: dict[str, pd.DataFrame]) -> int:
    """以最长的 DataFrame 长度作为时间轴。

    真实市场里各币上市时间不同，短 DataFrame 的币会在 _compute_one
    里因数据不足被过滤。用 min 会让任何一个新币拖死整个回测。
    """
    if not klines:
        return 0
    return max(len(df) for df in klines.values())


def _slice_klines(klines: dict[str, pd.DataFrame], end_idx: int) -> dict[str, pd.DataFrame]:
    """截取每个 symbol 前 end_idx 行 (不含 end_idx), 用于生成当期的 rank 输入。"""
    return {s: df.iloc[:end_idx] for s, df in klines.items()}


def _period_return(
    klines: dict[str, pd.DataFrame],
    picks: list[str],
    entry_idx: int,
    exit_idx: int,
) -> float:
    """等权持仓 picks, 从 entry_idx 到 exit_idx 的组合期间收益率。

    entry 价格为 picks[i] 在 entry_idx 的收盘价 (当日 ranking 后下一根入场)。
    """
    if not picks:
        return 0.0
    total = 0.0
    n = 0
    for symbol in picks:
        df = klines.get(symbol)
        if df is None or len(df) <= exit_idx:
            continue
        entry = float(df["close"].iloc[entry_idx])
        exit_ = float(df["close"].iloc[exit_idx])
        if entry <= 0:
            continue
        total += (exit_ / entry) - 1.0
        n += 1
    if n == 0:
        return 0.0
    return total / n


def _max_drawdown(equity: list[float]) -> float:
    """返回 equity 曲线的最大回撤 (负数或 0)。"""
    if not equity:
        return 0.0
    peak = equity[0]
    mdd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (e / peak) - 1.0
        if dd < mdd:
            mdd = dd
    return mdd


def _sharpe(period_returns: list[float], rebalance_every_days: int) -> float:
    """年化夏普 (假设 rf=0)。"""
    if len(period_returns) < 2:
        return 0.0
    import statistics
    mean = statistics.fmean(period_returns)
    try:
        stdev = statistics.stdev(period_returns)
    except statistics.StatisticsError:
        return 0.0
    if stdev == 0:
        return 0.0
    periods_per_year = 365.0 / max(rebalance_every_days, 1)
    return (mean / stdev) * math.sqrt(periods_per_year)


def run_momentum_backtest(
    klines: dict[str, pd.DataFrame],
    lookback_days: int = 30,
    trend_ma_period: int = 50,
    top_n: int = 10,
    rebalance_every_days: int = 7,
    btc_df: pd.DataFrame | None = None,
    btc_trend_ema: int = 200,
) -> MomentumBacktestResult:
    """运行周度再平衡 CSM 回测。

    每期流程:
      1. 用截至 entry_idx 的数据做 momentum ranking, 选 Top N
      2. 在 entry_idx 收盘入场 (等权)
      3. 持有 rebalance_every_days 根 K 线
      4. exit_idx = entry_idx + rebalance_every_days 收盘平仓
      5. 下一期 entry_idx = 当期 exit_idx

    Returns:
        MomentumBacktestResult - 含周期收益列表、equity 曲线和汇总指标。
    """
    n = _timeline_length(klines)
    warmup = max(lookback_days, trend_ma_period) + 1
    # 至少要有一期可回测: warmup + rebalance_every_days
    if n < warmup + rebalance_every_days or not klines:
        return MomentumBacktestResult(
            n_rebalances=0,
            period_returns=[],
            equity_curve=[1.0],
            lookback_days=lookback_days,
            trend_ma_period=trend_ma_period,
            top_n=top_n,
            rebalance_every_days=rebalance_every_days,
        )

    period_returns: list[float] = []
    equity: list[float] = [1.0]
    btc_filter_on = btc_df is not None and btc_trend_ema > 0
    n_btc_blocked = 0

    entry_idx = warmup
    while entry_idx + rebalance_every_days <= n:
        exit_idx = entry_idx + rebalance_every_days
        if btc_filter_on and not _btc_is_bullish(btc_df, entry_idx, btc_trend_ema):
            # 大盘熊市 → 空仓, 当期收益 0
            ret = 0.0
            n_btc_blocked += 1
        else:
            rank_input = _slice_klines(klines, entry_idx + 1)
            top = rank_by_momentum(
                rank_input,
                lookback_days=lookback_days,
                trend_ma_period=trend_ma_period,
                top_n=top_n,
            )
            picks = [r.symbol for r in top]
            ret = _period_return(klines, picks, entry_idx, exit_idx)
        period_returns.append(ret)
        equity.append(equity[-1] * (1.0 + ret))
        entry_idx = exit_idx

    n_rebalances = len(period_returns)
    total_return = equity[-1] - 1.0
    days_covered = n_rebalances * rebalance_every_days
    if days_covered > 0 and equity[-1] > 0:
        annualized = (equity[-1] ** (365.0 / days_covered)) - 1.0
    else:
        annualized = 0.0
    wins = sum(1 for r in period_returns if r > 0)
    win_rate = wins / n_rebalances if n_rebalances else 0.0

    return MomentumBacktestResult(
        n_rebalances=n_rebalances,
        period_returns=period_returns,
        equity_curve=equity,
        total_return_pct=total_return,
        annualized_return_pct=annualized,
        sharpe_ratio=_sharpe(period_returns, rebalance_every_days),
        max_drawdown_pct=_max_drawdown(equity),
        win_rate=win_rate,
        lookback_days=lookback_days,
        trend_ma_period=trend_ma_period,
        top_n=top_n,
        rebalance_every_days=rebalance_every_days,
        btc_trend_ema=btc_trend_ema if btc_filter_on else 0,
        n_btc_blocked=n_btc_blocked,
    )
