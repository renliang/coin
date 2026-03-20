from dataclasses import dataclass, field
from typing import Literal, Optional
import pandas as pd


@dataclass
class Signal:
    symbol: str
    direction: Literal["long", "short", "close"]
    entry_price: float
    stop_loss: float
    take_profit: Optional[float] = None
    reason: str = ""
    strategy_id: str = ""


class BaseStrategy:
    """所有策略的基类"""

    def __init__(self, strategy_id: str, symbol: str, timeframe: str, params: dict = {}):
        self.strategy_id = strategy_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.params = params
        self.enabled = True

    def on_bar(self, symbol: str, timeframe: str, df: pd.DataFrame) -> Optional[Signal]:
        """
        每根 K 线收盘时调用。
        df: 包含最近 N 根 K 线的 DataFrame，列为 open/high/low/close/volume
        返回 Signal 或 None
        """
        raise NotImplementedError

    def on_tick(self, symbol: str, price: float):
        """实时价格更新（可选覆写，用于动态止损）"""
        pass

    def should_handle(self, symbol: str, timeframe: str) -> bool:
        return symbol == self.symbol and timeframe == self.timeframe
