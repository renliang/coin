"""趋势跟踪策略的基础工具函数。

核心概念:
  - Donchian 通道: 过去 N 日最高/最低收盘价
  - ATR: 日波幅度量, 用于金字塔加仓触发阈值
  - EMA 长周期 (200): 大盘趋势过滤
"""
from __future__ import annotations

import pandas as pd


def donchian_high(
    closes: pd.Series,
    n: int,
    up_to: int | None = None,
    exclude_current: bool = False,
) -> float:
    """过去 n 日收盘价最高。

    Args:
        closes: 收盘价序列。
        n: 窗口长度。
        up_to: 截至下标 (含), None 表示到末尾。
        exclude_current: True 时不含当前 bar (用于突破判断)。
    """
    end = up_to + 1 if up_to is not None else len(closes)
    start = max(0, end - n)
    if exclude_current:
        end = max(start, end - 1)
    window = closes.iloc[start:end]
    if len(window) == 0:
        return float("nan")
    return float(window.max())


def donchian_low(
    closes: pd.Series,
    n: int,
    up_to: int | None = None,
    exclude_current: bool = False,
) -> float:
    """过去 n 日收盘价最低。参数语义同 donchian_high。"""
    end = up_to + 1 if up_to is not None else len(closes)
    start = max(0, end - n)
    if exclude_current:
        end = max(start, end - 1)
    window = closes.iloc[start:end]
    if len(window) == 0:
        return float("nan")
    return float(window.min())


def atr(df: pd.DataFrame, period: int = 14, up_to: int | None = None) -> float:
    """Wilder's ATR: 真实波幅的 period 日指数移动平均。

    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    """
    end = up_to + 1 if up_to is not None else len(df)
    sub = df.iloc[:end]
    if len(sub) < 2:
        return 0.0
    high = sub["high"].astype(float)
    low = sub["low"].astype(float)
    prev_close = sub["close"].astype(float).shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder's smoothing: alpha = 1/period
    atr_series = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    return float(atr_series.iloc[-1])


def is_above_ema(closes: pd.Series, period: int, up_to: int | None = None) -> bool:
    """close 是否高于 period 日 EMA。

    数据不足 period 根时返回 False (保守, 不入场)。
    """
    end = up_to + 1 if up_to is not None else len(closes)
    sub = closes.iloc[:end].astype(float)
    if len(sub) < period:
        return False
    ema = sub.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(sub.iloc[-1]) > float(ema)
