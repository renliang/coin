from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from scanner.detector import detect_pattern
from scanner.scorer import score_result


RETURN_PERIODS = [3, 7, 14, 30]


@dataclass
class BacktestHit:
    symbol: str
    detect_date: str
    window_days: int
    drop_pct: float
    volume_ratio: float
    score: float
    returns: dict[str, float | None] = field(default_factory=dict)


def run_backtest(
    klines: dict[str, pd.DataFrame],
    config: dict,
) -> list[BacktestHit]:
    """对所有币种做滑动窗口回扫，返回命中列表。"""
    window_min = config.get("window_min_days", 7)
    window_max = config.get("window_max_days", 14)
    vol_ratio = config.get("volume_ratio", 0.5)
    drop_min = config.get("drop_min", 0.05)
    drop_max = config.get("drop_max", 0.15)
    max_daily = config.get("max_daily_change", 0.05)

    all_hits: list[BacktestHit] = []

    for symbol, df in klines.items():
        closes = df["close"].values.astype(float)
        dates = df["timestamp"].values
        n = len(df)
        last_hit_idx = -window_max  # 去重：上次命中的索引

        # 从 window_max 开始逐日滑动
        for i in range(window_max, n + 1):
            # 去重：距上次命中不足 window_max 天则跳过
            if i - last_hit_idx < window_max:
                continue

            slice_df = df.iloc[:i].copy()
            result = detect_pattern(
                slice_df,
                window_min_days=window_min,
                window_max_days=window_max,
                volume_ratio=vol_ratio,
                drop_min=drop_min,
                drop_max=drop_max,
                max_daily_change=max_daily,
            )

            if not result.matched:
                continue

            last_hit_idx = i
            score = score_result(result, drop_min=drop_min, drop_max=drop_max, max_daily_change=max_daily)
            base_price = closes[i - 1]
            detect_date = str(pd.Timestamp(dates[i - 1]).date())

            # 计算各周期收益
            returns = {}
            for period in RETURN_PERIODS:
                future_idx = i - 1 + period
                if future_idx < n:
                    returns[f"{period}d"] = (closes[future_idx] - base_price) / base_price
                else:
                    returns[f"{period}d"] = None

            all_hits.append(BacktestHit(
                symbol=symbol,
                detect_date=detect_date,
                window_days=result.window_days,
                drop_pct=result.drop_pct,
                volume_ratio=result.volume_ratio,
                score=score,
                returns=returns,
            ))

    return all_hits


def _calc_period_stats(hits: list[BacktestHit], period: str) -> dict:
    """计算单个周期的统计指标。"""
    values = [h.returns[period] for h in hits if h.returns.get(period) is not None]
    if not values:
        return {"count": 0, "win_rate": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0, "min": 0.0}
    arr = np.array(values)
    return {
        "count": len(arr),
        "win_rate": float(np.mean(arr > 0)),
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "max": float(np.max(arr)),
        "min": float(np.min(arr)),
    }


def compute_stats(hits: list[BacktestHit]) -> dict:
    """计算整体统计和分档统计。"""
    periods = [f"{p}d" for p in RETURN_PERIODS]

    overall = {}
    for period in periods:
        overall[period] = _calc_period_stats(hits, period)

    tiers = {
        "high": [h for h in hits if h.score >= 0.6],
        "mid": [h for h in hits if 0.4 <= h.score < 0.6],
        "low": [h for h in hits if h.score < 0.4],
    }
    by_tier = {}
    for tier_name, tier_hits in tiers.items():
        by_tier[tier_name] = {}
        for period in periods:
            by_tier[tier_name][period] = _calc_period_stats(tier_hits, period)

    return {
        "total_hits": len(hits),
        "overall": overall,
        "by_tier": by_tier,
    }
