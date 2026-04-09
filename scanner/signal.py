from dataclasses import dataclass


@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08
    confirmation: bool = True
    confirmation_min_pass: int = 4


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
        signal_type = m.get("signal_type", "")
        is_bearish = signal_type == "顶背离"

        if is_bearish:
            sl_price = price * (1 + signal_config.stop_loss)
            tp_price = price * (1 - signal_config.take_profit)
        else:
            sl_price = price * (1 - signal_config.stop_loss)
            tp_price = price * (1 + signal_config.take_profit)

        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=m["score"],
            drop_pct=m.get("drop_pct", 0),
            volume_ratio=m.get("volume_ratio", 0),
            window_days=m.get("window_days", 0),
            entry_price=price,
            stop_loss_price=sl_price,
            take_profit_price=tp_price,
            hold_days=signal_config.hold_days,
            signal_type=signal_type,
            mode=m.get("mode", ""),
        ))
    return signals
