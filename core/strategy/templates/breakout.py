from typing import Optional
import pandas as pd
import pandas_ta as ta
from core.strategy.base import BaseStrategy, Signal


class BreakoutStrategy(BaseStrategy):
    """
    N 周期最高/最低价突破 + ATR 止损
    params:
      lookback: int = 20
      atr_period: int = 14
      atr_sl_multiplier: float = 2.0
    """

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        if not self.should_handle(symbol, timeframe) or not self.enabled:
            return None

        lookback = self.params.get("lookback", 20)
        atr_period = self.params.get("atr_period", 14)
        atr_sl_mult = self.params.get("atr_sl_multiplier", 2.0)

        if len(df) < lookback + atr_period + 5:
            return None

        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
        if atr is None:
            return None

        price = df["close"].iloc[-1]
        prev_high = df["high"].iloc[-lookback - 1:-1].max()
        prev_low = df["low"].iloc[-lookback - 1:-1].min()
        atr_val = atr.iloc[-1]

        if pd.isna(atr_val):
            return None

        if price > prev_high:
            sl = price - atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="long",
                entry_price=price,
                stop_loss=sl,
                reason=f"突破{lookback}周期高点({prev_high:.2f})",
                strategy_id=self.strategy_id,
            )

        if price < prev_low:
            sl = price + atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="short",
                entry_price=price,
                stop_loss=sl,
                reason=f"跌破{lookback}周期低点({prev_low:.2f})",
                strategy_id=self.strategy_id,
            )

        return None
