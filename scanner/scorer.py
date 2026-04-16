from dataclasses import dataclass

from scanner.detector import DetectionResult


@dataclass(frozen=True)
class ScoreBreakdown:
    """蓄力模式评分分项。"""
    vol_score: float       # 缩量程度 [0,1]
    drop_score: float      # 跌幅温和度 [0,1]
    trend_score: float     # R² 趋势稳定性 [0,1]
    slow_score: float      # 波动平稳度 [0,1]
    w_volume: float = 0.3
    w_drop: float = 0.25
    w_trend: float = 0.25
    w_slow: float = 0.2
    total: float = 0.0

    def to_dict(self) -> dict:
        return {
            "mode": "accumulation",
            "components": [
                {"name": "缩量程度", "score": self.vol_score, "weight": self.w_volume},
                {"name": "跌幅温和", "score": self.drop_score, "weight": self.w_drop},
                {"name": "趋势稳定", "score": self.trend_score, "weight": self.w_trend},
                {"name": "波动平稳", "score": self.slow_score, "weight": self.w_slow},
            ],
            "total": self.total,
        }


def _compute_components(
    result: DetectionResult,
    drop_min: float,
    drop_max: float,
    max_daily_change: float,
) -> tuple[float, float, float, float]:
    vol_score = max(0.0, min(1.0, 1.0 - result.volume_ratio))
    mid = (drop_min + drop_max) / 2
    half_range = (drop_max - drop_min) / 2
    drop_score = max(0.0, 1.0 - abs(result.drop_pct - mid) / half_range)
    trend_score = max(0.0, min(1.0, result.r_squared))
    slow_score = max(0.0, min(1.0, 1.0 - result.max_daily_pct / max_daily_change))
    return vol_score, drop_score, trend_score, slow_score


def score_result(
    result: DetectionResult,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> float:
    """对检测结果计算综合评分，范围[0, 1]。未命中返回0。"""
    if not result.matched:
        return 0.0
    vol, drop, trend, slow = _compute_components(result, drop_min, drop_max, max_daily_change)
    return vol * 0.3 + drop * 0.25 + trend * 0.25 + slow * 0.2


def score_result_detailed(
    result: DetectionResult,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> ScoreBreakdown:
    """返回含分项明细的评分。未命中所有分项为 0。"""
    if not result.matched:
        return ScoreBreakdown(0, 0, 0, 0)
    vol, drop, trend, slow = _compute_components(result, drop_min, drop_max, max_daily_change)
    total = vol * 0.3 + drop * 0.25 + trend * 0.25 + slow * 0.2
    return ScoreBreakdown(vol, drop, trend, slow, total=total)


def rank_results(items: list[dict], top_n: int = 20) -> list[dict]:
    """按score降序排列，取前top_n个。"""
    sorted_items = sorted(items, key=lambda x: x["score"], reverse=True)
    return sorted_items[:top_n]
