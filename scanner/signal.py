from dataclasses import dataclass


@dataclass
class SignalConfig:
    min_score: float = 0.6
    hold_days: int = 3
    stop_loss: float = 0.05
    take_profit: float = 0.08


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
        signals.append(TradeSignal(
            symbol=m["symbol"],
            price=price,
            score=m["score"],
            drop_pct=m["drop_pct"],
            volume_ratio=m["volume_ratio"],
            window_days=m["window_days"],
            entry_price=price,
            stop_loss_price=price * (1 - signal_config.stop_loss),
            take_profit_price=price * (1 + signal_config.take_profit),
            hold_days=signal_config.hold_days,
        ))
    return signals
