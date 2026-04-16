"""Smart Money Concepts (SMC) 扫描模块。

基于 smartmoneyconcepts 库检测市场结构变化（BOS/CHoCH）、
Fair Value Gap（FVG）和 Order Blocks（OB），生成交易信号。
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from smartmoneyconcepts.smc import smc


@dataclass
class SmcResult:
    matched: bool
    signal_type: str = ""          # "看多结构" | "看空结构"
    direction: str = ""            # "bullish" | "bearish"
    structure_type: str = ""       # "BOS" | "CHoCH"
    structure_index: int = 0       # 结构突破发生的 K 线索引
    structure_level: float = 0.0   # 突破价位
    has_fvg: bool = False          # 是否有未回补的 FVG
    fvg_top: float = 0.0
    fvg_bottom: float = 0.0
    has_ob: bool = False           # 是否有未回补的 OB
    ob_top: float = 0.0
    ob_bottom: float = 0.0
    ob_volume: float = 0.0
    score: float = 0.0
    # 评分分项
    structure_score: float = 0.0
    fvg_score: float = 0.0
    ob_score: float = 0.0
    confluence_score: float = 0.0

    def score_breakdown_dict(self) -> dict:
        return {
            "mode": "smc",
            "components": [
                {"name": "结构突破", "score": self.structure_score, "weight": 0.35},
                {"name": "FVG缺口", "score": self.fvg_score, "weight": 0.25},
                {"name": "订单块", "score": self.ob_score, "weight": 0.25},
                {"name": "多信号共振", "score": self.confluence_score, "weight": 0.15},
            ],
            "total": self.score,
        }


def _prepare_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """将项目的 K 线 DataFrame 转换为 SMC 库要求的格式。"""
    ohlc = pd.DataFrame({
        "open": df["open"].astype(float),
        "high": df["high"].astype(float),
        "low": df["low"].astype(float),
        "close": df["close"].astype(float),
        "volume": df["volume"].astype(float),
    })
    ohlc.reset_index(drop=True, inplace=True)
    return ohlc


def _find_latest_structure(
    bos_choch_df: pd.DataFrame,
    n: int,
    freshness: int,
) -> tuple[str, int, float, int] | None:
    """找到最近的 BOS 或 CHoCH 信号。

    Returns:
        (structure_type, direction, level, index) 或 None
        direction: 1=bullish, -1=bearish
    """
    # 先找 CHoCH（反转信号，优先级更高）
    for i in range(n - 1, max(n - freshness - 1, -1), -1):
        row = bos_choch_df.iloc[i]
        if not np.isnan(row.get("CHOCH", np.nan)):
            direction = int(row["CHOCH"])
            level = float(row["Level"])
            return "CHoCH", direction, level, i

    # 再找 BOS（趋势延续）
    for i in range(n - 1, max(n - freshness - 1, -1), -1):
        row = bos_choch_df.iloc[i]
        if not np.isnan(row.get("BOS", np.nan)):
            direction = int(row["BOS"])
            level = float(row["Level"])
            return "BOS", direction, level, i

    return None


def _find_nearest_fvg(
    fvg_df: pd.DataFrame,
    price: float,
    direction: int,
    n: int,
    lookback: int,
) -> tuple[float, float, int] | None:
    """找到与当前价格最近的、方向匹配的、未回补的 FVG。

    Returns:
        (top, bottom, index) 或 None
    """
    best = None
    best_dist = float("inf")

    for i in range(max(0, n - lookback), n):
        row = fvg_df.iloc[i]
        fvg_dir = row.get("FVG", np.nan)
        if np.isnan(fvg_dir):
            continue
        if int(fvg_dir) != direction:
            continue
        # 检查是否已被回补（MitigatedIndex > 0 表示已回补）
        mitigated = row.get("MitigatedIndex", 0)
        if not np.isnan(mitigated) and mitigated > 0:
            continue

        top = float(row["Top"])
        bottom = float(row["Bottom"])
        mid = (top + bottom) / 2
        dist = abs(price - mid) / price

        if dist < best_dist:
            best_dist = dist
            best = (top, bottom, i)

    return best


def _find_nearest_ob(
    ob_df: pd.DataFrame,
    price: float,
    direction: int,
    n: int,
    lookback: int,
) -> tuple[float, float, float, int] | None:
    """找到与当前价格最近的、方向匹配的、未回补的 OB。

    Returns:
        (top, bottom, volume, index) 或 None
    """
    best = None
    best_dist = float("inf")

    for i in range(max(0, n - lookback), n):
        row = ob_df.iloc[i]
        ob_dir = row.get("OB", np.nan)
        if np.isnan(ob_dir):
            continue
        if int(ob_dir) != direction:
            continue
        mitigated = row.get("MitigatedIndex", 0)
        if not np.isnan(mitigated) and mitigated > 0:
            continue

        top = float(row["Top"])
        bottom = float(row["Bottom"])
        mid = (top + bottom) / 2
        dist = abs(price - mid) / price

        if dist < best_dist:
            best_dist = dist
            best = (top, bottom, float(row.get("OBVolume", 0)), i)

    return best


def _score_smc(
    structure_type: str,
    structure_freshness: float,
    has_fvg: bool,
    fvg_proximity: float,
    has_ob: bool,
    ob_proximity: float,
) -> tuple[float, float, float, float, float]:
    """计算 SMC 评分 [0, 1]。

    Args:
        structure_type: "CHoCH" (反转，权重更高) 或 "BOS"
        structure_freshness: 结构突破的新鲜度 [0, 1]（越近越高）
        has_fvg: 是否有未回补 FVG
        fvg_proximity: FVG 与当前价格的距离评分 [0, 1]（越近越高）
        has_ob: 是否有未回补 OB
        ob_proximity: OB 与当前价格的距离评分 [0, 1]
    """
    # 结构评分：CHoCH 比 BOS 得分更高（反转信号更有价值）
    type_bonus = 1.0 if structure_type == "CHoCH" else 0.7
    structure_score = type_bonus * structure_freshness

    # FVG 评分
    fvg_score = fvg_proximity if has_fvg else 0.0

    # OB 评分
    ob_score = ob_proximity if has_ob else 0.0

    # 共振评分：多个信号同时出现时加分
    signal_count = 1  # 至少有结构突破
    if has_fvg:
        signal_count += 1
    if has_ob:
        signal_count += 1
    confluence_score = min(1.0, (signal_count - 1) / 2.0)

    total = (
        structure_score * 0.35
        + fvg_score * 0.25
        + ob_score * 0.25
        + confluence_score * 0.15
    )
    return total, structure_score, fvg_score, ob_score, confluence_score


def detect_smc(
    df: pd.DataFrame,
    swing_length: int = 10,
    freshness_candles: int = 10,
    fvg_lookback: int = 30,
    ob_lookback: int = 30,
    proximity_max: float = 0.05,
) -> SmcResult:
    """检测 Smart Money Concepts 模式。

    Args:
        df: K 线 DataFrame（需含 open/high/low/close/volume）
        swing_length: swing high/low 的窗口长度
        freshness_candles: 结构突破的新鲜度窗口（最近 N 根 K 线内）
        fvg_lookback: FVG 搜索回看范围
        ob_lookback: OB 搜索回看范围
        proximity_max: FVG/OB 与价格的最大距离（超过此距离评分为 0）
    """
    if len(df) < swing_length * 2 + 5:
        return SmcResult(matched=False)

    ohlc = _prepare_ohlc(df)
    n = len(ohlc)
    price = float(ohlc["close"].iloc[-1])

    # Step 1: 计算 swing highs/lows
    swing_hl = smc.swing_highs_lows(ohlc, swing_length=swing_length)

    # Step 2: 检测 BOS/CHoCH
    bos_choch = smc.bos_choch(ohlc, swing_hl)
    structure = _find_latest_structure(bos_choch, n, freshness_candles)

    if structure is None:
        return SmcResult(matched=False)

    structure_type, direction, level, struct_idx = structure
    freshness_ratio = max(0.0, 1.0 - (n - 1 - struct_idx) / freshness_candles)

    # Step 3: 检测 FVG
    fvg_df = smc.fvg(ohlc)
    fvg_result = _find_nearest_fvg(fvg_df, price, direction, n, fvg_lookback)
    has_fvg = fvg_result is not None
    fvg_top, fvg_bottom = 0.0, 0.0
    fvg_proximity = 0.0
    if fvg_result:
        fvg_top, fvg_bottom, _ = fvg_result
        fvg_mid = (fvg_top + fvg_bottom) / 2
        dist = abs(price - fvg_mid) / price
        fvg_proximity = max(0.0, 1.0 - dist / proximity_max)

    # Step 4: 检测 Order Blocks
    ob_df = smc.ob(ohlc, swing_hl)
    ob_result = _find_nearest_ob(ob_df, price, direction, n, ob_lookback)
    has_ob = ob_result is not None
    ob_top, ob_bottom, ob_volume = 0.0, 0.0, 0.0
    ob_proximity = 0.0
    if ob_result:
        ob_top, ob_bottom, ob_volume, _ = ob_result
        ob_mid = (ob_top + ob_bottom) / 2
        dist = abs(price - ob_mid) / price
        ob_proximity = max(0.0, 1.0 - dist / proximity_max)

    # Step 5: 评分
    total, s_struct, s_fvg, s_ob, s_confluence = _score_smc(
        structure_type, freshness_ratio, has_fvg, fvg_proximity, has_ob, ob_proximity,
    )

    if direction == 1:
        signal_type = "看多结构"
        dir_str = "bullish"
    else:
        signal_type = "看空结构"
        dir_str = "bearish"

    return SmcResult(
        matched=True,
        signal_type=signal_type,
        direction=dir_str,
        structure_type=structure_type,
        structure_index=struct_idx,
        structure_level=round(level, 6),
        has_fvg=has_fvg,
        fvg_top=round(fvg_top, 6),
        fvg_bottom=round(fvg_bottom, 6),
        has_ob=has_ob,
        ob_top=round(ob_top, 6),
        ob_bottom=round(ob_bottom, 6),
        ob_volume=round(ob_volume, 2),
        score=round(total, 4),
        structure_score=round(s_struct, 4),
        fvg_score=round(s_fvg, 4),
        ob_score=round(s_ob, 4),
        confluence_score=round(s_confluence, 4),
    )
