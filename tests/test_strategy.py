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
