"""Tests for sentiment/sources/onchain.py."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sentiment.sources.onchain import EtherscanSource


def _make_source(min_value_usd: float = 1_000_000) -> EtherscanSource:
    return EtherscanSource(api_key="test-key", min_value_usd=min_value_usd)


def _wei(eth: float) -> str:
    """Convert ETH amount to wei string."""
    return str(int(eth * 1e18))


# A known Binance address from KNOWN_EXCHANGE_ADDRESSES
BINANCE_ADDR = "0x28c6c06298d514db089934071355e5743bf21d60"
OTHER_ADDR = "0xabc123def456abc123def456abc123def456abc1"


class TestEtherscanSource:
    # ------------------------------------------------------------------
    # _classify_direction
    # ------------------------------------------------------------------

    def test_detect_exchange_inflow(self) -> None:
        source = _make_source()
        direction = source._classify_direction(OTHER_ADDR, BINANCE_ADDR)
        assert direction == "inflow"

    def test_detect_exchange_outflow(self) -> None:
        source = _make_source()
        direction = source._classify_direction(BINANCE_ADDR, OTHER_ADDR)
        assert direction == "outflow"

    def test_detect_transfer_between_non_exchanges(self) -> None:
        source = _make_source()
        direction = source._classify_direction(OTHER_ADDR, OTHER_ADDR)
        assert direction == "transfer"

    def test_classify_direction_case_insensitive(self) -> None:
        source = _make_source()
        direction = source._classify_direction(OTHER_ADDR, BINANCE_ADDR.upper())
        assert direction == "inflow"

    # ------------------------------------------------------------------
    # _parse_transfer
    # ------------------------------------------------------------------

    def _make_tx(
        self,
        value_eth: float = 500.0,
        from_addr: str = OTHER_ADDR,
        to_addr: str = BINANCE_ADDR,
        tx_hash: str = "0xdeadbeef",
        timestamp: int = 1700000000,
    ) -> dict:
        return {
            "value": _wei(value_eth),
            "from": from_addr,
            "to": to_addr,
            "hash": tx_hash,
            "timeStamp": str(timestamp),
        }

    def test_parse_large_transfer_creates_item(self) -> None:
        """500 ETH at 3000 USD = 1.5M USD — above threshold."""
        source = _make_source(min_value_usd=1_000_000)
        tx = self._make_tx(value_eth=500.0)
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is not None
        assert item.source == "onchain"
        assert item.symbol == "ETH/USDT"
        assert item.score == 0.0
        assert item.confidence == 0.9
        payload = json.loads(item.raw_text)
        assert payload["direction"] == "inflow"
        assert payload["amount_usd"] == pytest.approx(1_500_000.0, rel=1e-3)
        assert payload["exchange"] == "binance"
        assert payload["tx_hash"] == "0xdeadbeef"

    def test_skip_small_transfer_returns_none(self) -> None:
        """1 ETH at 3000 USD = 3K — below 1M threshold."""
        source = _make_source(min_value_usd=1_000_000)
        tx = self._make_tx(value_eth=1.0)
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is None

    def test_skip_transfer_between_non_exchanges(self) -> None:
        """Transfer not involving any known exchange address is skipped."""
        source = _make_source(min_value_usd=1.0)
        tx = self._make_tx(value_eth=1000.0, from_addr=OTHER_ADDR, to_addr=OTHER_ADDR)
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is None

    def test_parse_outflow_direction(self) -> None:
        """From exchange to other address = outflow."""
        source = _make_source(min_value_usd=1_000_000)
        tx = self._make_tx(value_eth=500.0, from_addr=BINANCE_ADDR, to_addr=OTHER_ADDR)
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is not None
        payload = json.loads(item.raw_text)
        assert payload["direction"] == "outflow"

    def test_parse_transfer_timestamp(self) -> None:
        source = _make_source(min_value_usd=1_000_000)
        ts_unix = 1700000000
        tx = self._make_tx(value_eth=500.0, timestamp=ts_unix)
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is not None
        expected_ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc)
        assert item.timestamp == expected_ts

    def test_parse_transfer_invalid_value_returns_none(self) -> None:
        source = _make_source()
        tx = {"value": "not-a-number", "from": OTHER_ADDR, "to": BINANCE_ADDR, "hash": "0x1"}
        item = source._parse_transfer(tx, eth_price=3000.0)
        assert item is None

    def test_parse_transfer_exact_threshold_included(self) -> None:
        """Exactly at threshold should be included."""
        source = _make_source(min_value_usd=1_000_000)
        # 333.333... ETH * 3000 = 999,999 — below
        tx_below = self._make_tx(value_eth=333.0)
        assert source._parse_transfer(tx_below, eth_price=3000.0) is None
        # 334 ETH * 3000 = 1,002,000 — above
        tx_above = self._make_tx(value_eth=334.0)
        assert source._parse_transfer(tx_above, eth_price=3000.0) is not None

    # ------------------------------------------------------------------
    # _fetch_eth_price
    # ------------------------------------------------------------------

    def test_fetch_eth_price_success(self) -> None:
        source = _make_source()
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"result": {"ethusd": "2500.50"}}
        with patch("requests.get", return_value=mock_response):
            price = source._fetch_eth_price()
        assert price == pytest.approx(2500.50)

    def test_fetch_eth_price_fallback_on_error(self) -> None:
        source = _make_source()
        with patch("requests.get", side_effect=ConnectionError("down")):
            price = source._fetch_eth_price()
        assert price == 3000.0

    # ------------------------------------------------------------------
    # fetch
    # ------------------------------------------------------------------

    def test_fetch_api_error_returns_empty(self) -> None:
        source = _make_source()
        with patch("requests.get", side_effect=ConnectionError("network error")):
            result = source.fetch()
        assert result == []

    def test_fetch_http_error_returns_empty(self) -> None:
        source = _make_source()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 429")
        with patch("requests.get", return_value=mock_response):
            result = source.fetch()
        assert result == []

    def test_fetch_filters_small_transactions(self) -> None:
        """Only transactions above min_value_usd threshold are returned."""
        source = _make_source(min_value_usd=1_000_000)

        price_response = MagicMock()
        price_response.raise_for_status.return_value = None
        price_response.json.return_value = {"result": {"ethusd": "3000.0"}}

        tx_list_response = MagicMock()
        tx_list_response.raise_for_status.return_value = None
        tx_list_response.json.return_value = {
            "result": [
                # Large: 500 ETH = 1.5M USD — should be included
                {
                    "value": _wei(500.0),
                    "from": OTHER_ADDR,
                    "to": BINANCE_ADDR,
                    "hash": "0xbig",
                    "timeStamp": "1700000000",
                },
                # Small: 1 ETH = 3K USD — should be excluded
                {
                    "value": _wei(1.0),
                    "from": OTHER_ADDR,
                    "to": BINANCE_ADDR,
                    "hash": "0xsmall",
                    "timeStamp": "1700000001",
                },
            ]
        }

        responses = [price_response, tx_list_response]
        with patch("requests.get", side_effect=responses):
            result = source.fetch()

        assert len(result) == 1
        payload = json.loads(result[0].raw_text)
        assert payload["tx_hash"] == "0xbig"

    def test_fetch_returns_sentiment_items(self) -> None:
        source = _make_source(min_value_usd=100_000)

        price_response = MagicMock()
        price_response.raise_for_status.return_value = None
        price_response.json.return_value = {"result": {"ethusd": "3000.0"}}

        tx_list_response = MagicMock()
        tx_list_response.raise_for_status.return_value = None
        tx_list_response.json.return_value = {
            "result": [
                {
                    "value": _wei(100.0),
                    "from": OTHER_ADDR,
                    "to": BINANCE_ADDR,
                    "hash": "0xtest",
                    "timeStamp": "1700000000",
                },
            ]
        }

        with patch("requests.get", side_effect=[price_response, tx_list_response]):
            result = source.fetch()

        assert len(result) == 1
        item = result[0]
        assert item.source == "onchain"
        assert item.symbol == "ETH/USDT"
        assert item.confidence == 0.9
        assert item.score == 0.0

    def test_known_exchange_addresses_populated(self) -> None:
        source = _make_source()
        assert len(source.KNOWN_EXCHANGE_ADDRESSES) >= 5
        # All keys should be lowercase
        for addr in source.KNOWN_EXCHANGE_ADDRESSES:
            assert addr == addr.lower(), f"Address {addr} is not lowercase"
