import asyncio
from typing import Optional
import ccxt.async_support as ccxt
import pandas as pd


class KlineFetcher:
    """从交易所拉取历史 K 线"""

    def __init__(self, exchange_id: str, api_key: str = "", secret: str = "", password: str = "", sandbox: bool = True):
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange: ccxt.Exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "password": password,
            "enableRateLimit": True,
        })
        if sandbox:
            self.exchange.set_sandbox_mode(True)

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 500,
        since: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        拉取 K 线数据，返回 DataFrame。
        列: timestamp, open, high, low, close, volume
        """
        raw = await self.exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df

    async def close(self):
        await self.exchange.close()
