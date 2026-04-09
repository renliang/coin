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


def confirm_signal(
    df: pd.DataFrame,
    direction: str,
    min_pass: int = 3,
) -> ConfirmationResult:
    """对候选信号做多指标确认。

    Args:
        df: K线 DataFrame (需含 open/high/low/close/volume)
        direction: "long" 或 "short"
        min_pass: 4项检查中至少通过几项才算确认通过

    Returns:
        ConfirmationResult
    """
    closes = df["close"].astype(float)
    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    volumes = df["volume"].astype(float)

    rsi = compute_rsi(closes, period=14)
    obv_trend = compute_obv_trend(closes, volumes, days=7)
    vol_ratio = compute_up_down_volume_ratio(closes, volumes, days=7)
    mfi = compute_mfi(highs, lows, closes, volumes, period=14)

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

    checks = [bool(rsi_ok), bool(obv_ok), bool(volume_ratio_ok), bool(mfi_ok)]
    passed_count = sum(checks)

    return ConfirmationResult(
        passed=passed_count >= min_pass,
        rsi_ok=checks[0],
        obv_ok=checks[1],
        volume_ratio_ok=checks[2],
        mfi_ok=checks[3],
        passed_count=passed_count,
        details={
            "rsi": round(rsi, 1),
            "obv_7d": round(obv_trend, 2),
            "up_down_vol_ratio": round(vol_ratio, 2) if vol_ratio != float("inf") else "inf",
            "mfi": round(mfi, 1),
        },
    )
