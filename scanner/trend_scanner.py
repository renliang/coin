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
from scanner.trend_position_store import TrendPosition


@dataclass(frozen=True)
class TrendAction:
    """一个建议动作 (入场/加仓/平仓), 供外层执行器消费。"""
    action_type: str            # "entry" | "pyramid" | "exit"
    symbol: str
    price: float                # 执行价 (今日 close)
    reason: str                 # breakout / atr_pyramid / chandelier_stop / donchian_stop
    atr: float = 0.0
    trailing_high: float = 0.0
    stop_price: float = 0.0
    new_level: int = 0          # 入场或加仓后的层数
    donchian_high: float = 0.0
    donchian_low: float = 0.0
    chandelier_stop: float = 0.0


@dataclass(frozen=True)
class ScanTrendResult:
    entries: list[TrendAction]
    pyramid_adds: list[TrendAction]
    exits: list[TrendAction]


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


def scan_trend_actions(
    klines: dict[str, pd.DataFrame],
    btc_df: pd.DataFrame | None,
    positions: list[TrendPosition],
    entry_n: int = 30,
    exit_n: int = 15,
    trend_ema: int = 200,
    btc_trend_ema: int = 100,
    atr_period: int = 14,
    chandelier_mult: float = 3.0,
    pyramid_levels: int = 3,
    atr_pyramid_mult: float = 1.0,
    max_positions: int = 10,
) -> ScanTrendResult:
    """状态感知扫描: 综合考虑持仓状态, 产出 entry/pyramid/exit 三类动作。

    执行顺序 (每日):
      1. BTC 大盘判定 (弱 → 不入场不加仓, 但止损仍处理)
      2. 对每个持仓: 检查止损 (Donchian + Chandelier 取紧) → exit 信号
      3. 对每个未被止损的持仓: 检查金字塔加仓 → pyramid 信号 (BTC 强时)
      4. 对未持仓的币: 检查突破入场 → entry 信号 (BTC 强 + 有空位)
    """
    btc_ok = True
    if btc_df is not None and btc_trend_ema > 0:
        btc_ok = is_above_ema(btc_df["close"], btc_trend_ema)

    held_symbols = {p.symbol for p in positions if p.status == "open"}
    n_open = len(held_symbols)

    exits: list[TrendAction] = []
    pyramid_adds: list[TrendAction] = []
    entries: list[TrendAction] = []

    # ── Step 1: 持仓 - 止损检查 (无论 BTC 强弱都跑) ──
    to_close_symbols: set[str] = set()
    for pos in positions:
        if pos.status != "open":
            continue
        df = klines.get(pos.symbol)
        if df is None or len(df) < max(exit_n, atr_period) + 1:
            continue
        last_idx = len(df) - 1
        close = float(df["close"].iloc[last_idx])
        # Donchian 低点止损
        dl = donchian_low(df["close"], exit_n, up_to=last_idx, exclude_current=True)
        donchian_trigger = (not math.isnan(dl)) and close < dl
        # Chandelier trailing stop (基于 DB 里的 trailing_high + 当前 ATR)
        chandelier_trigger = False
        chandelier_stop = 0.0
        a = atr(df, period=atr_period)
        if chandelier_mult > 0 and pos.trailing_high > 0:
            chandelier_stop = pos.trailing_high - chandelier_mult * a
            chandelier_trigger = close < chandelier_stop
        if donchian_trigger or chandelier_trigger:
            reason = "chandelier_stop" if chandelier_trigger else "donchian_stop"
            exits.append(TrendAction(
                action_type="exit",
                symbol=pos.symbol,
                price=close,
                reason=reason,
                atr=a,
                trailing_high=pos.trailing_high,
                stop_price=max(chandelier_stop, dl if not math.isnan(dl) else 0.0),
                donchian_low=dl if not math.isnan(dl) else 0.0,
                chandelier_stop=chandelier_stop,
            ))
            to_close_symbols.add(pos.symbol)

    # ── Step 2: 金字塔加仓 (BTC 强势, 未被止损) ──
    if btc_ok:
        for pos in positions:
            if pos.status != "open" or pos.symbol in to_close_symbols:
                continue
            if pos.levels >= pyramid_levels:
                continue
            df = klines.get(pos.symbol)
            if df is None or len(df) < atr_period + 1:
                continue
            last_idx = len(df) - 1
            close = float(df["close"].iloc[last_idx])
            # 条件: 今日创持仓期间新高 + 浮盈 ≥ levels × k × ATR
            new_trailing = max(pos.trailing_high, close)
            if close < new_trailing:
                continue  # 今日不是新高
            a = atr(df, period=atr_period)
            threshold = pos.avg_price + pos.levels * atr_pyramid_mult * a
            if close >= threshold:
                pyramid_adds.append(TrendAction(
                    action_type="pyramid",
                    symbol=pos.symbol,
                    price=close,
                    reason="atr_pyramid",
                    atr=a,
                    trailing_high=new_trailing,
                    new_level=pos.levels + 1,
                ))

    # ── Step 3: 入场 (BTC 强势 + 有空位 + 未持仓) ──
    slots = max_positions - n_open
    if btc_ok and slots > 0:
        candidates: list[TrendAction] = []
        min_required = max(entry_n, trend_ema, atr_period) + 1
        for symbol, df in klines.items():
            if symbol in held_symbols:
                continue
            if df is None or len(df) < min_required:
                continue
            closes = df["close"].astype(float)
            last_idx = len(closes) - 1
            close = float(closes.iloc[last_idx])
            dh = donchian_high(closes, entry_n, up_to=last_idx, exclude_current=True)
            if math.isnan(dh) or close <= dh:
                continue
            if not is_above_ema(closes, trend_ema):
                continue
            a = atr(df, period=atr_period)
            dl = donchian_low(closes, exit_n, up_to=last_idx, exclude_current=True)
            if math.isnan(dl):
                continue
            chandelier = close - chandelier_mult * a
            strength = close / dh - 1.0 if dh > 0 else 0.0
            candidates.append(TrendAction(
                action_type="entry",
                symbol=symbol,
                price=close,
                reason="breakout",
                atr=a,
                trailing_high=close,
                new_level=1,
                donchian_high=dh,
                donchian_low=dl,
                chandelier_stop=chandelier,
                stop_price=max(chandelier, dl),
            ))
        # 按突破强度降序, 取前 slots 个
        candidates.sort(
            key=lambda s: (s.price / s.donchian_high - 1.0) if s.donchian_high > 0 else 0.0,
            reverse=True,
        )
        entries = candidates[:slots]

    return ScanTrendResult(entries=entries, pyramid_adds=pyramid_adds, exits=exits)
