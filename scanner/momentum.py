"""横截面动量 (Cross-Sectional Momentum) 扫描。

逻辑:
  1. 对每个币计算过去 lookback_days 的收益率 (end_close / start_close - 1)
  2. 过滤当前价低于 trend MA 的币（非趋势状态）
  3. 剩余币按收益率降序排列，取 Top N

与其他扫描模式的本质差异: 这是横截面排序，不是 per-symbol 形态检测。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MomentumResult:
    symbol: str
    lookback_days: int
    start_price: float
    end_price: float
    return_pct: float       # 过去 lookback_days 收益率，正负均可
    above_ma: bool          # 当前 close 是否在 MA 之上
    ma_value: float         # MA 当前值
    score: float = 0.0      # 归一化评分 [0,1]，1 = 排名第一


def _compute_one(
    df: pd.DataFrame,
    lookback_days: int,
    trend_ma_period: int,
) -> tuple[float, float, float, float, float] | None:
    """单币计算: (start_price, end_price, return_pct, ma_value, above_ma_flag)。

    数据不足或除零时返回 None。
    """
    min_required = max(lookback_days, trend_ma_period) + 1
    if len(df) < min_required:
        return None
    closes = df["close"].astype(float)
    end_price = float(closes.iloc[-1])
    start_price = float(closes.iloc[-1 - lookback_days])
    if start_price <= 0:
        return None
    return_pct = end_price / start_price - 1.0
    ma_value = float(closes.iloc[-trend_ma_period:].mean())
    above_ma_flag = 1.0 if end_price > ma_value else 0.0
    return start_price, end_price, return_pct, ma_value, above_ma_flag


def rank_by_momentum(
    klines: dict[str, pd.DataFrame],
    lookback_days: int = 30,
    trend_ma_period: int = 50,
    top_n: int = 10,
) -> list[MomentumResult]:
    """横截面动量排序，返回 Top N。

    Args:
        klines: {symbol: daily_ohlcv_df}, 日线数据, 最后一行为最新收盘。
        lookback_days: 动量窗口 (默认 30 天)。
        trend_ma_period: 趋势过滤用的 MA 周期 (默认 50 日)。
        top_n: 返回前 N 个币。

    Returns:
        按 return_pct 降序排列的 MomentumResult 列表。已过滤掉:
          - 数据长度不足的币
          - 当前价 ≤ MA(trend_ma_period) 的币
    """
    candidates: list[tuple[str, float, float, float, float]] = []
    for symbol, df in klines.items():
        computed = _compute_one(df, lookback_days, trend_ma_period)
        if computed is None:
            continue
        start, end, ret, ma, above = computed
        if above < 0.5:  # 过滤非趋势币
            continue
        candidates.append((symbol, start, end, ret, ma))

    # 按收益率降序
    candidates.sort(key=lambda t: t[3], reverse=True)
    selected = candidates[:top_n]
    total = len(selected)
    if total == 0:
        return []

    # score: 排名归一化 (最强=1.0, 次强=(n-1)/n, ..., 末位=1/n)
    results: list[MomentumResult] = []
    for rank, (symbol, start, end, ret, ma) in enumerate(selected):
        score = (total - rank) / total
        results.append(
            MomentumResult(
                symbol=symbol,
                lookback_days=lookback_days,
                start_price=start,
                end_price=end,
                return_pct=ret,
                above_ma=True,
                ma_value=ma,
                score=score,
            )
        )
    return results
