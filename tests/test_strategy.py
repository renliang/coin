import pandas as pd
import pytest
from core.strategy.base import BaseStrategy, Signal


class AlwaysBuyStrategy(BaseStrategy):
    def on_bar(self, symbol, timeframe, df):
        price = df["close"].iloc[-1]
        return Signal(
            symbol=symbol,
            direction="long",
            entry_price=price,
            stop_loss=price * 0.99,
            strategy_id=self.strategy_id,
        )


def make_df(n=20):
    return pd.DataFrame({
        "open": [100.0] * n,
        "high": [105.0] * n,
        "low": [95.0] * n,
        "close": [102.0] * n,
        "volume": [1000.0] * n,
    })


def test_signal_returned():
    s = AlwaysBuyStrategy("test", "BTC-USDT-SWAP", "1h")
    sig = s.on_bar("BTC-USDT-SWAP", "1h", make_df())
    assert sig is not None
    assert sig.direction == "long"
    assert sig.stop_loss < sig.entry_price


def test_should_handle():
    s = AlwaysBuyStrategy("test", "BTC-USDT-SWAP", "1h")
    assert s.should_handle("BTC-USDT-SWAP", "1h")
    assert not s.should_handle("ETH-USDT-SWAP", "1h")


def test_no_signal_returns_none():
    class NeverBuy(BaseStrategy):
        def on_bar(self, symbol, timeframe, df):
            return None

    s = NeverBuy("test", "BTC-USDT-SWAP", "1h")
    assert s.on_bar("BTC-USDT-SWAP", "1h", make_df()) is None


import numpy as np
from core.strategy.templates.momentum import MomentumStrategy
from core.strategy.templates.breakout import BreakoutStrategy


def make_trend_df(n=100, trend="up"):
    prices = np.linspace(100, 120, n) if trend == "up" else np.linspace(120, 100, n)
    return pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.002,
        "low": prices * 0.998,
        "close": prices,
        "volume": [1000.0] * n,
    })


def test_momentum_returns_signal_or_none():
    s = MomentumStrategy("m1", "BTC-USDT-SWAP", "1h")
    df = make_trend_df(100)
    result = s.on_bar("BTC-USDT-SWAP", "1h", df)
    assert result is None or result.direction in ("long", "short")


def test_breakout_requires_enough_bars():
    s = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 20})
    short_df = make_trend_df(10)
    result = s.on_bar("BTC-USDT-SWAP", "1h", short_df)
    assert result is None


def test_breakout_long_signal_on_new_high():
    s = BreakoutStrategy("b1", "BTC-USDT-SWAP", "1h", params={"lookback": 5})
    prices = [100.0] * 30
    prices[-1] = 115.0  # 新高突破
    df = pd.DataFrame({
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices,
        "volume": [1000.0] * 30,
    })
    result = s.on_bar("BTC-USDT-SWAP", "1h", df)
    assert result is not None
    assert result.direction == "long"
