"""Optuna 贝叶斯参数搜索，用于优化积累型信号检测的超参数。

导出：
    OptimizedParams  — 优化结果 dataclass
    score_with_weights — 带自定义权重的信号评分函数
    objective_from_hits — Optuna 目标函数构造器
    optimize_params — 主入口：运行优化并返回最优参数
"""
from __future__ import annotations

from dataclasses import dataclass

import optuna

from scanner.backtest import BacktestHit, split_hits_by_median_date


@dataclass
class OptimizedParams:
    w_volume: float
    w_drop: float
    w_trend: float
    w_slow: float
    drop_min: float
    drop_max: float
    max_daily_change: float
    volume_ratio: float
    min_score: float
    confirmation_min_pass: int
    objective_value: float
    validation_win_rate: float
    validation_mean_return: float


def score_with_weights(
    volume_ratio: float,
    drop_pct: float,
    r_squared: float,
    max_daily_pct: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> float:
    """按自定义权重计算信号评分（归一化后加权求和）。

    先归一化四个权重之和为 1，再分别计算各分项后加权。
    返回值保证在 [0, 1] 之间。
    """
    # 归一化权重
    total = w_volume + w_drop + w_trend + w_slow
    if total <= 0:
        total = 1.0
    nw_v = w_volume / total
    nw_d = w_drop / total
    nw_t = w_trend / total
    nw_s = w_slow / total

    # 各分项评分
    vol_score = max(0.0, min(1.0, 1.0 - volume_ratio))

    mid = (drop_min + drop_max) / 2.0
    half_range = (drop_max - drop_min) / 2.0
    if half_range <= 0:
        drop_score = 1.0 if drop_pct == mid else 0.0
    else:
        drop_score = max(0.0, 1.0 - abs(drop_pct - mid) / half_range)

    trend_score = max(0.0, min(1.0, r_squared))

    if max_daily_change <= 0:
        slow_score = 0.0
    else:
        slow_score = max(0.0, min(1.0, 1.0 - max_daily_pct / max_daily_change))

    return nw_v * vol_score + nw_d * drop_score + nw_t * trend_score + nw_s * slow_score


def objective_from_hits(
    hits: list[BacktestHit],
    min_score: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
    min_samples: int = 10,
) -> float:
    """用给定参数对一组 BacktestHit 重新打分，返回 win_rate_7d × mean_return_7d。

    若通过门槛的样本数 < min_samples，返回 -1.0（惩罚）。
    """
    qualified: list[float] = []
    for hit in hits:
        new_score = score_with_weights(
            volume_ratio=hit.volume_ratio,
            drop_pct=hit.drop_pct,
            r_squared=hit.r_squared,
            max_daily_pct=hit.max_daily_pct,
            w_volume=w_volume,
            w_drop=w_drop,
            w_trend=w_trend,
            w_slow=w_slow,
            drop_min=drop_min,
            drop_max=drop_max,
            max_daily_change=max_daily_change,
        )
        if new_score >= min_score and hit.returns.get("7d") is not None:
            qualified.append(hit.returns["7d"])

    if len(qualified) < min_samples:
        return -1.0

    win_rate = sum(1 for r in qualified if r > 0) / len(qualified)
    mean_return = sum(qualified) / len(qualified)
    return win_rate * mean_return


def optimize_params(
    hits: list[BacktestHit],
    n_trials: int = 200,
    overfit_penalty: float = 0.15,
) -> OptimizedParams:
    """用 Optuna 贝叶斯搜索最优参数，含样本外过拟合惩罚。

    将 hits 按中位日期分为前后两半：前半段用于优化，后半段用于验证。
    若训练/验证胜率之差超过 overfit_penalty，则对目标函数施加惩罚。
    """
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    train_hits, val_hits = split_hits_by_median_date(hits)

    def _objective(trial: optuna.Trial) -> float:
        w_volume = trial.suggest_float("w_volume", 0.05, 0.6)
        w_drop = trial.suggest_float("w_drop", 0.05, 0.6)
        w_trend = trial.suggest_float("w_trend", 0.05, 0.6)
        w_slow = trial.suggest_float("w_slow", 0.05, 0.6)
        drop_min = trial.suggest_float("drop_min", 0.02, 0.08)
        drop_max = trial.suggest_float("drop_max", 0.10, 0.25)
        max_daily_change = trial.suggest_float("max_daily_change", 0.03, 0.08)
        min_score = trial.suggest_float("min_score", 0.5, 0.95)

        kwargs = dict(
            w_volume=w_volume,
            w_drop=w_drop,
            w_trend=w_trend,
            w_slow=w_slow,
            drop_min=drop_min,
            drop_max=drop_max,
            max_daily_change=max_daily_change,
            min_score=min_score,
        )

        train_obj = objective_from_hits(train_hits, **kwargs)

        # 样本外验证
        if val_hits:
            val_obj = objective_from_hits(val_hits, **kwargs)
            # 计算胜率差（简易过拟合检测）
            train_wr = _win_rate(train_hits, **kwargs)
            val_wr = _win_rate(val_hits, **kwargs)
            if train_wr - val_wr > overfit_penalty:
                train_obj *= 0.5  # 施加惩罚

        return train_obj

    study = optuna.create_study(direction="maximize")
    study.optimize(_objective, n_trials=n_trials)

    best = study.best_params
    objective_value = study.best_value

    # 归一化权重
    w_v = best["w_volume"]
    w_d = best["w_drop"]
    w_t = best["w_trend"]
    w_s = best["w_slow"]
    total = w_v + w_d + w_t + w_s
    w_v /= total
    w_d /= total
    w_t /= total
    w_s /= total

    # 计算验证集指标
    val_win_rate, val_mean_return = _val_metrics(
        val_hits,
        min_score=best["min_score"],
        w_volume=best["w_volume"],
        w_drop=best["w_drop"],
        w_trend=best["w_trend"],
        w_slow=best["w_slow"],
        drop_min=best["drop_min"],
        drop_max=best["drop_max"],
        max_daily_change=best["max_daily_change"],
    )

    return OptimizedParams(
        w_volume=w_v,
        w_drop=w_d,
        w_trend=w_t,
        w_slow=w_s,
        drop_min=best["drop_min"],
        drop_max=best["drop_max"],
        max_daily_change=best["max_daily_change"],
        volume_ratio=best.get("volume_ratio", 0.5),
        min_score=best["min_score"],
        confirmation_min_pass=best.get("confirmation_min_pass", 3),
        objective_value=objective_value,
        validation_win_rate=val_win_rate,
        validation_mean_return=val_mean_return,
    )


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------

def _win_rate(
    hits: list[BacktestHit],
    min_score: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
) -> float:
    """计算给定参数下通过门槛且 7d 收益为正的胜率。"""
    qualified: list[float] = []
    for hit in hits:
        new_score = score_with_weights(
            volume_ratio=hit.volume_ratio,
            drop_pct=hit.drop_pct,
            r_squared=hit.r_squared,
            max_daily_pct=hit.max_daily_pct,
            w_volume=w_volume,
            w_drop=w_drop,
            w_trend=w_trend,
            w_slow=w_slow,
            drop_min=drop_min,
            drop_max=drop_max,
            max_daily_change=max_daily_change,
        )
        if new_score >= min_score and hit.returns.get("7d") is not None:
            qualified.append(hit.returns["7d"])
    if not qualified:
        return 0.0
    return sum(1 for r in qualified if r > 0) / len(qualified)


def _val_metrics(
    hits: list[BacktestHit],
    min_score: float,
    w_volume: float,
    w_drop: float,
    w_trend: float,
    w_slow: float,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
) -> tuple[float, float]:
    """返回 (win_rate_7d, mean_return_7d)，无样本时均返回 0.0。"""
    qualified: list[float] = []
    for hit in hits:
        new_score = score_with_weights(
            volume_ratio=hit.volume_ratio,
            drop_pct=hit.drop_pct,
            r_squared=hit.r_squared,
            max_daily_pct=hit.max_daily_pct,
            w_volume=w_volume,
            w_drop=w_drop,
            w_trend=w_trend,
            w_slow=w_slow,
            drop_min=drop_min,
            drop_max=drop_max,
            max_daily_change=max_daily_change,
        )
        if new_score >= min_score and hit.returns.get("7d") is not None:
            qualified.append(hit.returns["7d"])
    if not qualified:
        return 0.0, 0.0
    win_rate = sum(1 for r in qualified if r > 0) / len(qualified)
    mean_return = sum(qualified) / len(qualified)
    return win_rate, mean_return
