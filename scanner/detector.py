from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DetectionResult:
    """形态检测结果"""
    volume_pass: bool
    trend_pass: bool
    drop_pass: bool
    slow_pass: bool
    matched: bool
    volume_ratio: float
    drop_pct: float
    r_squared: float
    max_daily_pct: float
    window_days: int


def detect_pattern(
    df: pd.DataFrame,
    window_min_days: int = 7,
    window_max_days: int = 14,
    volume_ratio: float = 0.5,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> DetectionResult:
    """对K线数据做底部蓄力形态检测。

    尝试从 window_max_days 到 window_min_days 的不同窗口，
    取第一个四项全部通过的窗口；若都不通过，取 window_max_days 的结果。
    """
    best = None
    for window in range(window_max_days, window_min_days - 1, -1):
        result = _detect_window(df, window, volume_ratio, drop_min, drop_max, max_daily_change)
        if result.matched:
            return result
        if best is None:
            best = result
    return best


def _detect_window(
    df: pd.DataFrame,
    window: int,
    volume_ratio: float,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
) -> DetectionResult:
    """在固定窗口大小下检测形态"""
    tail = df.tail(window).copy()
    closes = tail["close"].values.astype(float)
    volumes = tail["volume"].values.astype(float)

    # 1. 缩量判断：前半段 vs 后半段
    mid = len(volumes) // 2
    early_avg = np.mean(volumes[:mid])
    late_avg = np.mean(volumes[mid:])
    actual_vol_ratio = late_avg / early_avg if early_avg > 0 else 1.0
    vol_pass = actual_vol_ratio < volume_ratio

    # 2. 下跌趋势：线性回归斜率为负
    x = np.arange(len(closes), dtype=float)
    slope, intercept = np.polyfit(x, closes, 1)
    ss_res = np.sum((closes - (slope * x + intercept)) ** 2)
    ss_tot = np.sum((closes - np.mean(closes)) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    trend_pass = slope < 0

    # 3. 跌幅范围
    max_close = np.max(closes)
    min_close = np.min(closes)
    drop_pct = (max_close - min_close) / max_close if max_close > 0 else 0.0
    drop_pass = drop_min <= drop_pct <= drop_max

    # 4. 缓慢确认：单日涨跌幅不超限
    daily_returns = np.abs(np.diff(closes) / closes[:-1])
    max_daily_pct = float(np.max(daily_returns)) if len(daily_returns) > 0 else 0.0
    slow_pass = max_daily_pct <= max_daily_change

    matched = bool(vol_pass) and bool(trend_pass) and bool(drop_pass) and bool(slow_pass)

    return DetectionResult(
        volume_pass=bool(vol_pass),
        trend_pass=bool(trend_pass),
        drop_pass=bool(drop_pass),
        slow_pass=bool(slow_pass),
        matched=matched,
        volume_ratio=float(actual_vol_ratio),
        drop_pct=float(drop_pct),
        r_squared=float(r_squared),
        max_daily_pct=max_daily_pct,
        window_days=window,
    )
