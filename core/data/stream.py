import asyncio
import logging
from typing import Callable, Awaitable
import ccxt.pro as ccxtpro
import pandas as pd

logger = logging.getLogger(__name__)

BarCallback = Callable[[str, str, pd.DataFrame], Awaitable[None]]


class MarketStream:
    """WebSocket 实时行情流，断线自动重连"""

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "", password: str = "", sandbox: bool = True):
        exchange_class = getattr(ccxtpro, exchange_id)
        self.exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)
        self._callbacks: list[BarCallback] = []
        self._running = False

    def on_bar(self, callback: BarCallback):
        """注册 K 线收盘回调"""
        self._callbacks.append(callback)

    async def watch_candles(self, symbol: str, timeframe: str):
        """持续监听 K 线更新，新 bar 收盘时触发回调"""
        self._running = True
        backoff = 1
        while self._running:
            try:
                candles = await self.exchange.watch_ohlcv(symbol, timeframe)
                df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("timestamp", inplace=True)
                for cb in self._callbacks:
                    await cb(symbol, timeframe, df)
                backoff = 1
            except Exception as e:
                logger.warning(f"WebSocket error: {e}, retry in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def stop(self):
        self._running = False
        await self.exchange.close()
