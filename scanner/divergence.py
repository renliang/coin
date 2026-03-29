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


def detect_divergence(
    df: "pd.DataFrame",
    pivot_len: int = 3,
    lookback: int = 60,
) -> "DivergenceResult":
    """检测MACD背离（占位，后续任务实现）。"""
    raise NotImplementedError("detect_divergence will be implemented in a future task")


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
