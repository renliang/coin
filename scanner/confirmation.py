from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ConfirmationResult:
    """信号确认结果。"""
    passed: bool
    passed_count: int
    score: float           # 确认层连续得分 [0, 1]
    bonus: float           # 加分值 [-0.10, +0.10]
    rsi_ok: bool
    obv_ok: bool
    volume_ratio_ok: bool
    mfi_ok: bool
    volume_surge_ok: bool
    atr_accel_ok: bool
    momentum_ok: bool
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


def compute_volume_surge(
    volumes: pd.Series,
    recent_days: int = 3,
    baseline_days: int = 7,
) -> float:
    """计算近 recent_days 日均量 / 前 baseline_days 日均量。

    返回比值（1.0=无变化，2.0=倍量）。数据不足返回 1.0。
    """
    if len(volumes) < recent_days + baseline_days:
        return 1.0
    recent_avg = volumes.iloc[-recent_days:].mean()
    baseline_avg = volumes.iloc[-(recent_days + baseline_days):-recent_days].mean()
    if baseline_avg == 0:
        return 1.0
    return float(recent_avg / baseline_avg)


def compute_atr_accel(
    highs: pd.Series,
    lows: pd.Series,
    closes: pd.Series,
    recent_days: int = 7,
    baseline_days: int = 14,
) -> float:
    """计算近 recent_days ATR / 前 baseline_days ATR。

    返回比值（1.0=无变化，>1.2=波动加速）。数据不足返回 1.0。
    """
    if len(closes) < recent_days + baseline_days + 1:
        return 1.0

    def _atr(h: pd.Series, l: pd.Series, c: pd.Series) -> float:
        prev_c = c.shift(1)
        tr = pd.concat([
            h - l,
            (h - prev_c).abs(),
            (l - prev_c).abs(),
        ], axis=1).max(axis=1)
        return float(tr.mean())

    cut = -(recent_days + baseline_days)
    recent_atr = _atr(
        highs.iloc[-recent_days:],
        lows.iloc[-recent_days:],
        closes.iloc[-(recent_days + 1):],
    )
    baseline_atr = _atr(
        highs.iloc[cut:-recent_days],
        lows.iloc[cut:-recent_days],
        closes.iloc[cut - 1:-recent_days],
    )
    if baseline_atr == 0:
        return 1.0
    return float(recent_atr / baseline_atr)


def compute_price_momentum(closes: pd.Series, days: int = 5) -> float:
    """计算近 days 日收益率。

    返回小数（0.05 = +5%, -0.10 = -10%）。数据不足返回 0.0。
    """
    if len(closes) < days + 1:
        return 0.0
    return float((closes.iloc[-1] - closes.iloc[-(days + 1)]) / closes.iloc[-(days + 1)])


def confirm_signal(
    df: pd.DataFrame,
    direction: str,
    min_pass: int = 4,
) -> ConfirmationResult:
    """对候选信号做多指标确认，返回连续评分和加分。

    Args:
        df: K线 DataFrame (需含 open/high/low/close/volume)
        direction: "long" 或 "short"
        min_pass: 6项检查中至少通过几项才算确认通过

    Returns:
        ConfirmationResult (含 score 和 bonus)
    """
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    # 计算原始指标值
    rsi = compute_rsi(closes, period=14)
    obv_trend = compute_obv_trend(closes, volumes, days=7)
    vol_ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)
    surge = compute_volume_surge(volumes, recent_days=3, baseline_days=7)
    accel = compute_atr_accel(highs, lows, closes, recent_days=7, baseline_days=14)
    momentum = compute_price_momentum(closes, days=5)

    # --- bool 判断（用于过滤） ---
    if direction == "long":
        rsi_ok = 30 <= rsi <= 70
        obv_ok = obv_trend > 0
        volume_ratio_ok = vol_ratio >= 1.0
        mfi_ok = 20 <= mfi <= 80
    else:
        rsi_ok = 30 <= rsi <= 70
        obv_ok = obv_trend < 0
        volume_ratio_ok = vol_ratio <= 1.0
        mfi_ok = 20 <= mfi <= 80
    volume_surge_ok = surge >= 1.5
    atr_accel_ok = accel > 1.2
    if direction == "long":
        momentum_ok = momentum >= -0.05
    else:
        momentum_ok = momentum <= 0.05

    checks = [bool(rsi_ok), bool(obv_ok), bool(volume_ratio_ok),
              bool(mfi_ok), bool(volume_surge_ok), bool(atr_accel_ok), bool(momentum_ok)]
    passed_count = sum(checks)

    # --- 连续分计算 [0, 1] ---
    rsi_score = max(0.0, 1.0 - abs(rsi - 50) / 50)

    total_obv = abs(compute_obv_trend(closes, volumes, days=len(closes) - 1)) + 1e-10
    obv_raw = min(1.0, max(0.0, abs(obv_trend) / total_obv * 10))
    if (direction == "long" and obv_trend > 0) or (direction == "short" and obv_trend < 0):
        obv_score = obv_raw
    else:
        obv_score = 1.0 - obv_raw

    if direction == "long":
        vr_score = min(1.0, vol_ratio / 2.0) if vol_ratio != float("inf") else 1.0
    else:
        if vol_ratio == float("inf"):
            vr_score = 0.0
        elif vol_ratio == 0:
            vr_score = 1.0
        else:
            vr_score = min(1.0, (1.0 / vol_ratio) / 2.0)

    mfi_score = max(0.0, 1.0 - abs(mfi - 50) / 50)
    surge_score = min(1.0, max(0.0, (surge - 1.0) / 1.0))
    accel_score = min(1.0, max(0.0, (accel - 1.0) / 0.5))
    if direction == "long":
        momentum_score = min(1.0, max(0.0, (momentum + 0.10) / 0.20))
    else:
        momentum_score = min(1.0, max(0.0, (-momentum + 0.10) / 0.20))

    # 7 项均分
    confirmation_score = (rsi_score + obv_score + vr_score + mfi_score + surge_score + accel_score + momentum_score) / 7.0

    # 加分：以 0.5 为中性，最大 ±0.10
    bonus = (confirmation_score - 0.5) * 0.2
    bonus = max(-0.10, min(0.10, bonus))

    return ConfirmationResult(
        passed=passed_count >= min_pass,
        passed_count=passed_count,
        score=round(confirmation_score, 4),
        bonus=round(bonus, 4),
        rsi_ok=checks[0],
        obv_ok=checks[1],
        volume_ratio_ok=checks[2],
        mfi_ok=checks[3],
        volume_surge_ok=checks[4],
        atr_accel_ok=checks[5],
        momentum_ok=checks[6],
        details={
            "rsi": round(rsi, 1),
            "obv_7d": round(obv_trend, 2),
            "up_down_vol_ratio": round(vol_ratio, 2) if vol_ratio != float("inf") else "inf",
            "mfi": round(mfi, 1),
            "volume_surge": round(surge, 2),
            "atr_accel": round(accel, 2),
            "momentum_5d": round(momentum, 4),
        },
    )
