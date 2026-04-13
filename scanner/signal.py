import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0
    atr_tp_multiplier: float = 3.0
    confirmation: bool = True
    confirmation_min_pass: int = 4
    max_stop_loss: float = 0.05


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """计算 ATR (Average True Range)。返回最后一根K线的ATR值。"""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    return float(atr)


@dataclass
class TradeSignal:
    symbol: str
    price: float
    score: float
    drop_pct: float
    volume_ratio: float
    window_days: int
    entry_price: float
    stop_loss_price: float
    take_profit_price: float
    hold_days: int
    signal_type: str = ""
    mode: str = ""
    sl_capped: bool = False
    market_cap_m: float = 0.0


def _entry_discount(score: float) -> float:
    """评分越高回撤越小，评分越低回撤越大。"""
    if score >= 0.9:
        return 0.01
    if score >= 0.8:
        return 0.02
    if score >= 0.7:
        return 0.025
    return 0.03


def generate_signals(
    matches: list[dict],
    signal_config: SignalConfig,
) -> list[TradeSignal]:
    """过滤低分结果，为通过的结果生成交易建议。"""
    signals = []
    for m in matches:
        if m["score"] < signal_config.min_score:
            continue
        price = m["price"]
        score = m["score"]
        signal_type = m.get("signal_type", "")
        is_bearish = signal_type == "顶背离"

        atr = m.get("atr", 0)
        use_atr = atr > 0 and not math.isnan(atr)

        discount = _entry_discount(score)
        if is_bearish:
            entry = price * (1 + discount)
            if use_atr:
                sl_price = entry + signal_config.atr_sl_multiplier * atr
                tp_price = entry - signal_config.atr_tp_multiplier * atr
            else:
                sl_price = entry * (1 + signal_config.stop_loss)
                tp_price = entry * (1 - signal_config.take_profit)
        else:
            entry = price * (1 - discount)
            if use_atr:
                sl_price = entry - signal_config.atr_sl_multiplier * atr
                tp_price = entry + signal_config.atr_tp_multiplier * atr
            else:
                sl_price = entry * (1 - signal_config.stop_loss)
                tp_price = entry * (1 + signal_config.take_profit)

        # ATR 止损截断：若止损距离超过 max_stop_loss，收紧到上限
        sl_capped = False
        if use_atr:
            sl_dist = abs(sl_price - entry) / entry
            if sl_dist > signal_config.max_stop_loss:
                if is_bearish:
                    sl_price = entry * (1 + signal_config.max_stop_loss)
                else:
                    sl_price = entry * (1 - signal_config.max_stop_loss)
                sl_capped = True

        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=score,
            drop_pct=m.get("drop_pct", 0),
            volume_ratio=m.get("volume_ratio", 0),
            window_days=m.get("window_days", 0),
            entry_price=entry,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            hold_days=signal_config.hold_days,
            signal_type=signal_type,
            mode=m.get("mode", ""),
            sl_capped=sl_capped,
            market_cap_m=m.get("market_cap_m", 0.0),
        ))
    return signals
