import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch, MagicMock
from core.data.fetcher import KlineFetcher


@pytest.fixture
def mock_exchange():
    with patch("core.data.fetcher.ccxt") as mock_ccxt:
        exchange_instance = AsyncMock()
        exchange_class = MagicMock(return_value=exchange_instance)
        mock_ccxt.okx = exchange_class
        exchange_instance.fetch_ohlcv.return_value = [
            [1700000000000, 50000.0, 51000.0, 49000.0, 50500.0, 100.0],
            [1700003600000, 50500.0, 52000.0, 50000.0, 51500.0, 120.0],
        ]
        yield exchange_instance


@pytest.mark.asyncio
async def test_fetch_ohlcv_returns_dataframe(mock_exchange):
    fetcher = KlineFetcher("okx")
    fetcher.exchange = mock_exchange
    df = await fetcher.fetch_ohlcv("BTC-USDT-SWAP", "1h", limit=2)
    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[0] == 50500.0
