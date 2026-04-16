from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class DivergenceResult:
    """背离检测结果"""
    divergence_type: str    # "bullish" | "bearish" | "none"
    price_1: float          # 第一个极值点价格
    price_2: float          # 第二个极值点价格
    dif_1: float            # 第一个极值点DIF值
    dif_2: float            # 第二个极值点DIF值
    pivot_distance: int     # 两极值点间距（K线根数）
    score: float            # 综合评分 [0, 1]
    # 评分分项（可选，detect_divergence 会填充）
    strength_score: float = 0.0
    confirm_score: float = 0.0
    time_score: float = 0.0

    def score_breakdown_dict(self) -> dict:
        return {
            "mode": "divergence",
            "components": [
                {"name": "背离强度", "score": self.strength_score, "weight": 0.5},
                {"name": "MACD确认", "score": self.confirm_score, "weight": 0.3},
                {"name": "时间合理", "score": self.time_score, "weight": 0.2},
            ],
            "total": self.score,
        }


def compute_macd(
    closes: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD指标，返回 (DIF, DEA, MACD柱)。"""
    ema_fast = closes.ewm(span=fast, adjust=False).mean()
    ema_slow = closes.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    hist = (dif - dea) * 2
    return dif, dea, hist


def _score_divergence(
    price_1: float,
    price_2: float,
    dif_1: float,
    dif_2: float,
    hist: pd.Series,
    idx_1: int,
    idx_2: int,
    div_type: str,
) -> tuple[float, float, float, float]:
    """计算背离评分 [0, 1]，返回 (total, strength, confirm, time_score)。

    三个维度:
    - 背离强度 (权重0.5): 价格差与DIF差的偏离程度
    - MACD柱确认 (权重0.3): 第二极值点附近柱状图是否收缩
    - 时间合理性 (权重0.2): 间距越接近30天越好
    """
    # 1. 背离强度: 价格变化率与DIF变化率方向相反的程度
    price_change = abs(price_2 - price_1) / abs(price_1) if price_1 != 0 else 0
    dif_change = abs(dif_2 - dif_1) / (abs(dif_1) + 1e-10)
    strength = min(1.0, (price_change + dif_change) / 1.0)

    # 2. MACD柱确认: 第二极值点附近的柱值是否在回归零轴
    window = 5
    start = max(0, idx_2 - window)
    end = min(len(hist), idx_2 + window + 1)
    hist_slice = hist.iloc[start:end].values
    if div_type == "bullish":
        hist_trend = np.mean(np.diff(hist_slice)) if len(hist_slice) > 1 else 0
        confirm = min(1.0, max(0.0, hist_trend / (abs(hist.iloc[idx_1]) + 1e-10) * 10))
    else:
        hist_trend = np.mean(np.diff(hist_slice)) if len(hist_slice) > 1 else 0
        confirm = min(1.0, max(0.0, -hist_trend / (abs(hist.iloc[idx_1]) + 1e-10) * 10))

    # 3. 时间合理性: 间距接近30天得分最高，线性衰减
    distance = idx_2 - idx_1
    time_score = max(0.0, 1.0 - abs(distance - 30) / 30)

    total = strength * 0.5 + confirm * 0.3 + time_score * 0.2
    return total, strength, confirm, time_score


def detect_divergence(
    df: pd.DataFrame,
    pivot_len: int = 7,
    min_distance: int = 15,
    max_distance: int = 60,
    min_price_diff: float = 0.05,
) -> DivergenceResult:
    """在日K线数据中检测MACD背离。

    需要至少40根K线(26根MACD预热 + 检测空间)。
    """
    none_result = DivergenceResult(
        divergence_type="none",
        price_1=0, price_2=0,
        dif_1=0, dif_2=0,
        pivot_distance=0,
        score=0.0,
    )

    if len(df) < 40:
        return none_result

    closes = df["close"].astype(float)
    dif, dea, hist = compute_macd(closes)

    # 在MACD预热期之后寻找极值点
    warmup = 26
    close_after = closes.iloc[warmup:]
    lows, highs = find_pivots(close_after, pivot_len=pivot_len)

    # 将索引调整回原始DataFrame
    lows = [i + warmup for i in lows]
    highs = [i + warmup for i in highs]

    best_result = none_result

    # 检查底背离: 遍历波谷对
    for i in range(len(lows) - 1):
        for j in range(i + 1, len(lows)):
            idx1, idx2 = lows[i], lows[j]
            dist = idx2 - idx1
            if dist < min_distance or dist > max_distance:
                continue
            p1, p2 = float(closes.iloc[idx1]), float(closes.iloc[idx2])
            d1, d2 = float(dif.iloc[idx1]), float(dif.iloc[idx2])
            # 底背离: 价格创新低（差距≥min_price_diff），DIF未创新低
            if p2 < p1 and d2 > d1 and (p1 - p2) / p1 >= min_price_diff:
                total, s_str, s_conf, s_time = _score_divergence(p1, p2, d1, d2, hist, idx1, idx2, "bullish")
                if total > best_result.score:
                    best_result = DivergenceResult(
                        divergence_type="bullish",
                        price_1=p1, price_2=p2,
                        dif_1=d1, dif_2=d2,
                        pivot_distance=dist,
                        score=total,
                        strength_score=s_str,
                        confirm_score=s_conf,
                        time_score=s_time,
                    )

    # 检查顶背离: 遍历波峰对
    for i in range(len(highs) - 1):
        for j in range(i + 1, len(highs)):
            idx1, idx2 = highs[i], highs[j]
            dist = idx2 - idx1
            if dist < min_distance or dist > max_distance:
                continue
            p1, p2 = float(closes.iloc[idx1]), float(closes.iloc[idx2])
            d1, d2 = float(dif.iloc[idx1]), float(dif.iloc[idx2])
            # 顶背离: 价格创新高（差距≥min_price_diff），DIF未创新高
            if p2 > p1 and d2 < d1 and (p2 - p1) / p1 >= min_price_diff:
                total, s_str, s_conf, s_time = _score_divergence(p1, p2, d1, d2, hist, idx1, idx2, "bearish")
                if total > best_result.score:
                    best_result = DivergenceResult(
                        divergence_type="bearish",
                        price_1=p1, price_2=p2,
                        dif_1=d1, dif_2=d2,
                        pivot_distance=dist,
                        score=total,
                        strength_score=s_str,
                        confirm_score=s_conf,
                        time_score=s_time,
                    )

    return best_result


def find_pivots(
    series: pd.Series,
    pivot_len: int = 3,
) -> tuple[list[int], list[int]]:
    """找局部波谷和波峰的索引。

    波谷：某点比前后各 pivot_len 个点都低。
    波峰：某点比前后各 pivot_len 个点都高。
    """
    values = series.values.astype(float)
    n = len(values)
    lows = []
    highs = []
    for i in range(pivot_len, n - pivot_len):
        window = values[i - pivot_len: i + pivot_len + 1]
        if values[i] == np.min(window):
            lows.append(i)
        if values[i] == np.max(window):
            highs.append(i)
    return lows, highs
