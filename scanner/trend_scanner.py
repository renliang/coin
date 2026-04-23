"""趋势跟踪 实时入场信号扫描器 (Phase 1a)。

给定最新 K 线, 判定当天(最后一根 bar)是否触发入场信号。
配合 CLI `coin scan --mode trend` 使用, 只产出信号不下单。

持仓状态管理 / 金字塔加仓 / 动态止损触发等, 见 Phase 1b。
"""
from __future__ import annotations

from dataclasses import dataclass

import math

import pandas as pd

from scanner.trend_follow import atr, donchian_high, donchian_low, is_above_ema


@dataclass(frozen=True)
class TrendEntrySignal:
    symbol: str
    entry_price: float              # 今日收盘价 (建议挂 entry_price ±0.1% 市价)
    atr: float                      # 入场时 ATR14, 用于计算止损位
    donchian_high: float            # 被突破的那个高点
    initial_stop_chandelier: float  # entry - chandelier_mult × ATR
    initial_stop_donchian: float    # 过去 exit_n 日最低收盘
    breakout_strength: float        # (entry / donchian_high - 1), 越大信号越强


def scan_trend_entries(
    klines: dict[str, pd.DataFrame],
    btc_df: pd.DataFrame | None,
    entry_n: int = 30,
    exit_n: int = 15,
    trend_ema: int = 200,
    btc_trend_ema: int = 100,
    atr_period: int = 14,
    chandelier_mult: float = 3.0,
) -> list[TrendEntrySignal]:
    """扫描当前一根 K 线触发的趋势跟踪入场信号, 按突破强度降序返回。

    判定条件 (全部满足):
      1. 单币突破: 今日 close > 过去 entry_n 日最高 close (不含今日)
      2. 单币趋势: 今日 close > 本币 EMA(trend_ema)
      3. 大盘过滤: BTC 今日 close > BTC EMA(btc_trend_ema)
      4. 数据充足: 该币 K 线长度 ≥ max(entry_n, trend_ema, atr_period) + 1

    Returns:
        按 breakout_strength 降序排列的入场信号列表。
    """
    # 先判大盘: BTC 弱直接返回空
    if btc_df is not None and btc_trend_ema > 0:
        if not is_above_ema(btc_df["close"], btc_trend_ema):
            return []

    signals: list[TrendEntrySignal] = []
    min_required = max(entry_n, trend_ema, atr_period) + 1

    for symbol, df in klines.items():
        if df is None or len(df) < min_required:
            continue
        closes = df["close"].astype(float)
        last_idx = len(closes) - 1
        close = float(closes.iloc[last_idx])
        # 条件 1: 突破过去 entry_n 日最高 close (不含今日)
        dh = donchian_high(closes, entry_n, up_to=last_idx, exclude_current=True)
        if math.isnan(dh) or close <= dh:
            continue
        # 条件 2: 单币 EMA 趋势
        if not is_above_ema(closes, trend_ema):
            continue
        # 计算止损位 + 强度
        a = atr(df, period=atr_period)
        dl = donchian_low(closes, exit_n, up_to=last_idx, exclude_current=True)
        if math.isnan(dl):
            continue
        chandelier = close - chandelier_mult * a
        strength = close / dh - 1.0 if dh > 0 else 0.0
        signals.append(TrendEntrySignal(
            symbol=symbol,
            entry_price=close,
            atr=a,
            donchian_high=dh,
            initial_stop_chandelier=chandelier,
            initial_stop_donchian=dl,
            breakout_strength=strength,
        ))

    signals.sort(key=lambda s: s.breakout_strength, reverse=True)
    return signals
