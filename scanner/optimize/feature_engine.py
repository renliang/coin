"""16 维特征提取引擎，用于信号评分模型。

导出:
    FEATURE_NAMES: list[str]  — 16 个特征名（按顺序）
    extract_features(match_dict, df, btc_df=None) -> list[float]
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from scanner.confirmation import (
    compute_atr_accel,
    compute_mfi,
    compute_obv_trend,
    compute_price_momentum,
    compute_rsi,
    compute_volume_surge,
)

# ──────────────────────────────────────────────
# 特征名（顺序固定，共 16 个）
# ──────────────────────────────────────────────
FEATURE_NAMES: list[str] = [
    # 信号特征 (6)
    "volume_ratio",
    "drop_pct",
    "r_squared",
    "max_daily_pct",
    "window_days",
    "score",
    # 确认层特征 (7)
    "rsi",
    "obv_7d",
    "mfi",
    "volume_surge",
    "atr_accel",
    "momentum_5d",
    "confirmation_score",
    # 市场环境 (3)
    "btc_return_7d",
    "btc_volatility_14d",
    "total_market_volume_change",
]

assert len(FEATURE_NAMES) == 16, "FEATURE_NAMES 必须恰好 16 个"


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _safe_float(v: Any) -> float:
    """将 NaN / inf / None 转为 0.0，其余转 float。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f):
        return 0.0
    return f


def _compute_confirmation_features(df: pd.DataFrame) -> dict[str, float]:
    """计算 7 个确认层特征。"""
    closes = df["close"]
    highs = df["high"]
    lows = df["low"]
    volumes = df["volume"]

    rsi = _safe_float(compute_rsi(closes, 14))
    obv_7d = _safe_float(compute_obv_trend(closes, volumes, 7))
    mfi = _safe_float(compute_mfi(highs, lows, closes, volumes, 14))
    surge = _safe_float(compute_volume_surge(volumes, 3, 7))
    accel = _safe_float(compute_atr_accel(highs, lows, closes, 7, 14))
    momentum = _safe_float(compute_price_momentum(closes, 5))

    # confirmation_score 均分
    rsi_score = max(0.0, 1.0 - abs(rsi - 50.0) / 50.0)
    mfi_score = max(0.0, 1.0 - abs(mfi - 50.0) / 50.0)
    surge_score = min(1.0, max(0.0, (surge - 1.0) / 1.0))
    accel_score = min(1.0, max(0.0, (accel - 1.0) / 0.5))
    momentum_score = min(1.0, max(0.0, (momentum + 0.10) / 0.20))
    confirmation = (rsi_score + mfi_score + surge_score + accel_score + momentum_score) / 5.0

    return {
        "rsi": rsi,
        "obv_7d": obv_7d,
        "mfi": mfi,
        "volume_surge": surge,
        "atr_accel": accel,
        "momentum_5d": momentum,
        "confirmation_score": _safe_float(confirmation),
    }


def _compute_btc_features(btc_df: pd.DataFrame | None) -> dict[str, float]:
    """计算 BTC 市场环境特征；btc_df 为 None 时返回 0。"""
    if btc_df is None or len(btc_df) < 15:
        return {"btc_return_7d": 0.0, "btc_volatility_14d": 0.0}

    closes = btc_df["close"]
    # 近 7 日收益率
    ret7 = _safe_float((closes.iloc[-1] - closes.iloc[-8]) / closes.iloc[-8])
    # 近 14 日波动率 (std / mean)
    recent14 = closes.iloc[-14:]
    mean14 = _safe_float(recent14.mean())
    vol14 = _safe_float(recent14.std() / mean14) if mean14 != 0.0 else 0.0

    return {"btc_return_7d": ret7, "btc_volatility_14d": vol14}


# ──────────────────────────────────────────────
# 主接口
# ──────────────────────────────────────────────

def extract_features(
    match_dict: dict[str, Any],
    df: pd.DataFrame,
    btc_df: pd.DataFrame | None = None,
) -> list[float]:
    """从 match_dict 和 K 线 df 提取 16 维特征向量。

    Args:
        match_dict: 检测结果字典，含 volume_ratio / drop_pct / r_squared /
                    max_daily_pct / window_days / score 等键。
        df:         目标标的 K 线 DataFrame（含 high/low/close/volume 列）。
        btc_df:     BTC K 线 DataFrame（可选）；为 None 时 BTC 相关特征填 0。

    Returns:
        长度为 16 的 float 列表，顺序与 FEATURE_NAMES 一致。
    """
    # 1. 信号特征
    signal_feats = [
        _safe_float(match_dict.get("volume_ratio", 0)),
        _safe_float(match_dict.get("drop_pct", 0)),
        _safe_float(match_dict.get("r_squared", 0)),
        _safe_float(match_dict.get("max_daily_pct", 0)),
        _safe_float(match_dict.get("window_days", 0)),
        _safe_float(match_dict.get("score", 0)),
    ]

    # 2. 确认层特征
    conf = _compute_confirmation_features(df)
    conf_feats = [
        conf["rsi"],
        conf["obv_7d"],
        conf["mfi"],
        conf["volume_surge"],
        conf["atr_accel"],
        conf["momentum_5d"],
        conf["confirmation_score"],
    ]

    # 3. 市场环境特征
    btc = _compute_btc_features(btc_df)
    market_feats = [
        btc["btc_return_7d"],
        btc["btc_volatility_14d"],
        _safe_float(compute_volume_surge(df["volume"], 3, 7)),  # total_market_volume_change
    ]

    features = signal_feats + conf_feats + market_feats
    assert len(features) == 16
    return features
