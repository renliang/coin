"""Onchain sentiment source: Etherscan whale transfer tracking."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import requests

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)


class EtherscanSource:
    """Tracks large ETH transfers to/from known exchanges via Etherscan API."""

    KNOWN_EXCHANGE_ADDRESSES: dict[str, str] = {
        # Binance
        "0x28c6c06298d514db089934071355e5743bf21d60": "binance",
        "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "binance",
        "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "binance",
        # Bybit
        "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "bybit",
        # Coinbase
        "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "coinbase",
        "0xa9d1e08c7793af67e9d92fe308d5697fb81d3e43": "coinbase",
        # Kraken
        "0x2910543af39aba0cd09dbb2d50200b3e800a63d2": "kraken",
        "0x0a869d79a7052c7f1b55a8ebabbea3420f0d1e13": "kraken",
        # OKX
        "0x6cc5f688a315f3dc28a7781717a9a798a59fda7b": "okx",
        # Huobi / HTX
        "0xab5c66752a9e8167967685f1450532fb96d5d24f": "huobi",
        "0x6748f50f686bfbca6fe8ad62b22228b87f31ff2b": "huobi",
    }

    _ETHERSCAN_API = "https://api.etherscan.io/api"

    def __init__(self, api_key: str, min_value_usd: float = 1_000_000) -> None:
        self._api_key = api_key
        self._min_value_usd = min_value_usd

    def _classify_direction(self, from_addr: str, to_addr: str) -> str:
        """Return 'inflow', 'outflow', or 'transfer' based on exchange address mapping."""
        from_lower = from_addr.lower()
        to_lower = to_addr.lower()
        if to_lower in self.KNOWN_EXCHANGE_ADDRESSES:
            return "inflow"
        if from_lower in self.KNOWN_EXCHANGE_ADDRESSES:
            return "outflow"
        return "transfer"

    def _parse_transfer(self, tx: dict, eth_price: float) -> SentimentItem | None:
        """
        Convert a raw Etherscan transaction dict to a SentimentItem.

        Returns None if:
        - value is below min_value_usd threshold
        - direction is 'transfer' (neither from nor to a known exchange)
        """
        try:
            value_wei = int(tx.get("value", "0"))
        except (ValueError, TypeError):
            return None

        value_eth = value_wei / 1e18
        amount_usd = value_eth * eth_price

        if amount_usd < self._min_value_usd:
            return None

        from_addr = tx.get("from", "")
        to_addr = tx.get("to", "")
        direction = self._classify_direction(from_addr, to_addr)

        if direction == "transfer":
            return None

        # Determine which side is the exchange
        from_lower = from_addr.lower()
        to_lower = to_addr.lower()
        exchange = (
            self.KNOWN_EXCHANGE_ADDRESSES.get(to_lower)
            or self.KNOWN_EXCHANGE_ADDRESSES.get(from_lower)
            or "unknown"
        )

        tx_hash = tx.get("hash", "")
        raw_text = json.dumps(
            {
                "direction": direction,
                "amount_usd": round(amount_usd, 2),
                "exchange": exchange,
                "tx_hash": tx_hash,
            }
        )

        try:
            ts_unix = int(tx.get("timeStamp", "0"))
            ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
        except (ValueError, TypeError):
            ts = datetime.now(tz=timezone.utc)

        return SentimentItem(
            source="onchain",
            symbol="ETH/USDT",
            score=0.0,
            confidence=0.9,
            raw_text=raw_text,
            timestamp=ts,
        )

    def _fetch_eth_price(self) -> float:
        """Fetch current ETH price from Etherscan. Falls back to 3000.0 on error."""
        try:
            params = {
                "module": "stats",
                "action": "ethprice",
                "apikey": self._api_key,
            }
            response = requests.get(self._ETHERSCAN_API, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return float(data["result"]["ethusd"])
        except Exception as exc:
            logger.warning("EtherscanSource._fetch_eth_price error: %s", exc)
            return 3000.0

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        """
        Fetch recent large ETH transfers from known exchange addresses.

        Returns [] on error.
        """
        try:
            eth_price = self._fetch_eth_price()

            # Use Binance hot wallet as a well-known address to scan
            address = "0x28c6c06298d514db089934071355e5743bf21d60"
            params = {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": 100,
                "sort": "desc",
                "apikey": self._api_key,
            }
            response = requests.get(self._ETHERSCAN_API, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            txs = data.get("result", [])
            if not isinstance(txs, list):
                return []

            items: list[SentimentItem] = []
            for tx in txs:
                item = self._parse_transfer(tx, eth_price)
                if item is not None:
                    items.append(item)
            return items

        except Exception as exc:
            logger.warning("EtherscanSource.fetch error: %s", exc)
            return []
