import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class BreakoutResult:
    matched: bool
    spike_date: str = ""
    spike_volume_ratio: float = 0.0
    spike_high: float = 0.0
    pullback_low: float = 0.0
    pullback_shrink: float = 0.0
    reattack_date: str = ""
    reattack_volume_ratio: float = 0.0
    reattack_close: float = 0.0
    days_since_spike: int = 0
    score: float = 0.0


def detect_breakout(
    df: pd.DataFrame,
    spike_multiplier: float = 5.0,
    shrink_threshold: float = 0.3,
    reattack_multiplier: float = 2.0,
    max_pullback_days: int = 10,
    freshness_days: int = 3,
) -> BreakoutResult:
    """检测天量→缩量回调→放量二攻模式。"""
    if len(df) < 25:
        return BreakoutResult(matched=False)

    closes = df["close"].astype(float).values
    volumes = df["volume"].astype(float).values
    highs = df["high"].astype(float).values
    lows = df["low"].astype(float).values
    dates = df["timestamp"].values
    n = len(df)

    # Step 1: 找天量日（从最近往前找，取最近一个）
    spike_idx = -1
    for i in range(n - 2, 19, -1):
        baseline = np.mean(volumes[max(0, i - 20):i])
        if baseline > 0 and volumes[i] >= baseline * spike_multiplier:
            spike_idx = i
            break

    if spike_idx < 0:
        return BreakoutResult(matched=False)

    # Step 2: 天量日后检查缩量回调
    spike_vol = volumes[spike_idx]
    search_end = min(n, spike_idx + max_pullback_days + 1)

    # 找缩量阶段：至少连续2天量 < 天量 * shrink_threshold
    shrink_start = -1
    shrink_found = False
    for i in range(spike_idx + 1, search_end):
        if volumes[i] < spike_vol * shrink_threshold:
            if shrink_start < 0:
                shrink_start = i
            if i - shrink_start >= 1:  # 至少连续2天
                shrink_found = True
        else:
            if shrink_found:
                break
            shrink_start = -1

    if not shrink_found:
        return BreakoutResult(matched=False)

    # 回调阶段最低价和最小量
    pullback_end = min(n, spike_idx + max_pullback_days + 1)
    pullback_low = float(np.min(lows[shrink_start:pullback_end]))
    pullback_min_vol = float(np.min(volumes[shrink_start:pullback_end]))
    pullback_shrink = pullback_min_vol / spike_vol

    # Step 3: 缩量后找放量二攻
    reattack_idx = -1
    for i in range(shrink_start + 2, n):
        recent_start = max(shrink_start, i - 3)
        recent_3d_avg = np.mean(volumes[recent_start:i])
        if recent_3d_avg > 0 and volumes[i] >= recent_3d_avg * reattack_multiplier:
            reattack_idx = i
            break

    if reattack_idx < 0:
        return BreakoutResult(matched=False)

    # Step 4: 新鲜度检查
    if (n - 1 - reattack_idx) >= freshness_days:
        return BreakoutResult(matched=False)

    # 构造结果
    spike_date = str(pd.Timestamp(dates[spike_idx]).date())
    reattack_date = str(pd.Timestamp(dates[reattack_idx]).date())
    baseline_avg = float(np.mean(volumes[max(0, spike_idx - 20):spike_idx]))
    spike_vol_ratio = float(volumes[spike_idx] / baseline_avg) if baseline_avg > 0 else 0.0
    reattack_recent_avg = float(np.mean(volumes[max(shrink_start, reattack_idx - 3):reattack_idx]))
    reattack_vol_ratio = float(volumes[reattack_idx] / reattack_recent_avg) if reattack_recent_avg > 0 else 0.0
    reattack_close = float(closes[reattack_idx])
    spike_high = float(highs[spike_idx])

    score = _score_breakout(spike_vol_ratio, pullback_shrink, reattack_vol_ratio, reattack_close, spike_high)

    return BreakoutResult(
        matched=True,
        spike_date=spike_date,
        spike_volume_ratio=round(spike_vol_ratio, 1),
        spike_high=round(spike_high, 6),
        pullback_low=round(pullback_low, 6),
        pullback_shrink=round(pullback_shrink, 4),
        reattack_date=reattack_date,
        reattack_volume_ratio=round(reattack_vol_ratio, 1),
        reattack_close=round(reattack_close, 6),
        days_since_spike=int(reattack_idx - spike_idx),
        score=round(score, 4),
    )


def _score_breakout(
    spike_vol_ratio: float,
    pullback_shrink: float,
    reattack_vol_ratio: float,
    reattack_close: float,
    spike_high: float,
) -> float:
    """计算天量回踩二攻评分 [0, 1]。"""
    spike_score = min(1.0, math.log(spike_vol_ratio / 5.0 + 1) / math.log(11))
    shrink_score = max(0.0, 1.0 - pullback_shrink / 0.5)
    reattack_score = min(1.0, math.log(reattack_vol_ratio / 2.0 + 1) / math.log(6))
    position_score = min(1.0, reattack_close / spike_high) if spike_high > 0 else 0.0
    return spike_score * 0.3 + shrink_score * 0.2 + reattack_score * 0.3 + position_score * 0.2
