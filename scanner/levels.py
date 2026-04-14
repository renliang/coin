import pandas as pd


def find_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 支撑位价格列表（升序）。
    判定：lows[i] 严格小于左 left 根和右 right 根的最小值。
    数据不足时返回空列表。
    """
    if len(df) < left + right + 1:
        return []
    lows = df["low"].values.astype(float)
    pivots = []
    for i in range(left, len(lows) - right):
        left_min = float(min(lows[i - left:i]))
        right_min = float(min(lows[i + 1:i + right + 1]))
        if lows[i] < left_min and lows[i] < right_min:
            pivots.append(float(lows[i]))
    return sorted(set(pivots))


def find_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> list[float]:
    """返回 Pivot 阻力位价格列表（升序）。"""
    if len(df) < left + right + 1:
        return []
    highs = df["high"].values.astype(float)
    pivots = []
    for i in range(left, len(highs) - right):
        left_max = float(max(highs[i - left:i]))
        right_max = float(max(highs[i + 1:i + right + 1]))
        if highs[i] > left_max and highs[i] > right_max:
            pivots.append(float(highs[i]))
    return sorted(set(pivots))


def nearest_support(
    df: pd.DataFrame, price: float, max_dist: float | None = None
) -> float | None:
    """返回低于 price 的最近支撑位。
    max_dist：(price - level) / price 的上限，None 表示不过滤。
    """
    levels = find_pivot_lows(df)
    candidates = [l for l in levels if l < price]
    if max_dist is not None:
        candidates = [l for l in candidates if (price - l) / price <= max_dist]
    return max(candidates) if candidates else None


def nearest_resistance(
    df: pd.DataFrame, price: float, max_dist: float | None = None
) -> float | None:
    """返回高于 price 的最近阻力位。
    max_dist：(level - price) / price 的上限，None 表示不过滤。
    """
    levels = find_pivot_highs(df)
    candidates = [l for l in levels if l > price]
    if max_dist is not None:
        candidates = [l for l in candidates if (l - price) / price <= max_dist]
    return min(candidates) if candidates else None
