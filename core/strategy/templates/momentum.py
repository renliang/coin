from typing import Optional
import pandas as pd
import pandas_ta as ta
from core.strategy.base import BaseStrategy, Signal


class MomentumStrategy(BaseStrategy):
    """
    EMA 趋势过滤 + RSI 超卖/超买入场
    params:
      ema_period: int = 20
      rsi_period: int = 14
      rsi_oversold: float = 30
      rsi_overbought: float = 70
      atr_period: int = 14
      atr_sl_multiplier: float = 1.5
    """

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        if not self.should_handle(symbol, timeframe) or not self.enabled:
            return None
        if len(df) < max(self.params.get("ema_period", 20), self.params.get("rsi_period", 14)) + 5:
            return None

        ema_period = self.params.get("ema_period", 20)
        rsi_period = self.params.get("rsi_period", 14)
        rsi_oversold = self.params.get("rsi_oversold", 30)
        rsi_overbought = self.params.get("rsi_overbought", 70)
        atr_period = self.params.get("atr_period", 14)
        atr_sl_mult = self.params.get("atr_sl_multiplier", 1.5)

        ema = ta.ema(df["close"], length=ema_period)
        rsi = ta.rsi(df["close"], length=rsi_period)
        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)

        if ema is None or rsi is None or atr is None:
            return None

        price = df["close"].iloc[-1]
        ema_val = ema.iloc[-1]
        rsi_val = rsi.iloc[-1]
        atr_val = atr.iloc[-1]

        if pd.isna(ema_val) or pd.isna(rsi_val) or pd.isna(atr_val):
            return None

        # 多单：价格在 EMA 上方 + RSI 超卖反弹
        if price > ema_val and rsi_val < rsi_oversold:
            sl = price - atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="long",
                entry_price=price,
                stop_loss=sl,
                reason=f"EMA上方+RSI超卖({rsi_val:.1f})",
                strategy_id=self.strategy_id,
            )

        # 空单：价格在 EMA 下方 + RSI 超买
        if price < ema_val and rsi_val > rsi_overbought:
            sl = price + atr_val * atr_sl_mult
            return Signal(
                symbol=symbol,
                direction="short",
                entry_price=price,
                stop_loss=sl,
                reason=f"EMA下方+RSI超买({rsi_val:.1f})",
                strategy_id=self.strategy_id,
            )

        return None
