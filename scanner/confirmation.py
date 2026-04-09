from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ConfirmationResult:
    """信号确认结果。"""
    passed: bool
    rsi_ok: bool
    obv_ok: bool
    volume_ratio_ok: bool
    mfi_ok: bool
    passed_count: int
    details: dict


def compute_rsi(closes: pd.Series, period: int = 14) -> float:
    """计算 RSI(period)，返回最新值。"""
    deltas = closes.diff()
    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)
    avg_gain = gains.rolling(period).mean().iloc[-1]
    avg_loss = losses.rolling(period).mean().iloc[-1]
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def compute_obv_trend(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float:
    """计算近 days 日的 OBV 净变化。正=净流入，负=净流出。"""
    obv = pd.Series(0.0, index=closes.index)
    for i in range(1, len(closes)):
        if closes.iloc[i] > closes.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] + volumes.iloc[i]
        elif closes.iloc[i] < closes.iloc[i - 1]:
            obv.iloc[i] = obv.iloc[i - 1] - volumes.iloc[i]
        else:
            obv.iloc[i] = obv.iloc[i - 1]
    return float(obv.iloc[-1] - obv.iloc[-(days + 1)])


def compute_up_down_volume_ratio(closes: pd.Series, volumes: pd.Series, days: int = 7) -> float:
    """计算近 days 日上涨日总成交量 / 下跌日总成交量。"""
    up_vol = 0.0
    down_vol = 0.0
    start = max(1, len(closes) - days)
    for i in range(start, len(closes)):
        if closes.iloc[i] >= closes.iloc[i - 1]:
            up_vol += volumes.iloc[i]
        else:
            down_vol += volumes.iloc[i]
    if down_vol == 0:
        return float("inf")
    return up_vol / down_vol


def compute_mfi(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    volumes: pd.Series,
    period: int = 14,
) -> float:
    """计算 MFI(period)，返回最新值。"""
    typical_price = (highs + lows + closes) / 3.0
    raw_mf = typical_price * volumes
    pos_mf = pd.Series(0.0, index=closes.index)
    neg_mf = pd.Series(0.0, index=closes.index)
    for i in range(1, len(typical_price)):
        if typical_price.iloc[i] > typical_price.iloc[i - 1]:
            pos_mf.iloc[i] = raw_mf.iloc[i]
        else:
            neg_mf.iloc[i] = raw_mf.iloc[i]
    pos_sum = pos_mf.rolling(period).sum().iloc[-1]
    neg_sum = neg_mf.rolling(period).sum().iloc[-1]
    if neg_sum == 0:
        return 100.0
    return float(100.0 - 100.0 / (1.0 + pos_sum / neg_sum))
