from scanner.detector import DetectionResult


def score_result(
    result: DetectionResult,
    drop_min: float = 0.05,
    drop_max: float = 0.15,
    max_daily_change: float = 0.05,
) -> float:
    """对检测结果计算综合评分，范围[0, 1]。未命中返回0。"""
    if not result.matched:
        return 0.0

    # 缩量程度 (权重0.3): 1 - ratio，越小越好
    vol_score = max(0.0, min(1.0, 1.0 - result.volume_ratio))

    # 跌幅温和度 (权重0.25): 越接近区间中心越高
    mid = (drop_min + drop_max) / 2
    half_range = (drop_max - drop_min) / 2
    drop_score = max(0.0, 1.0 - abs(result.drop_pct - mid) / half_range)

    # 趋势稳定性 (权重0.25): R²值
    trend_score = max(0.0, min(1.0, result.r_squared))

    # 波动平稳度 (权重0.2): 最大单日涨跌幅越小越好
    slow_score = max(0.0, min(1.0, 1.0 - result.max_daily_pct / max_daily_change))

    return vol_score * 0.3 + drop_score * 0.25 + trend_score * 0.25 + slow_score * 0.2


def rank_results(items: list[dict], top_n: int = 20) -> list[dict]:
    """按score降序排列，取前top_n个。"""
    sorted_items = sorted(items, key=lambda x: x["score"], reverse=True)
    return sorted_items[:top_n]
