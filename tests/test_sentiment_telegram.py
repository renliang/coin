"""Tests for sentiment/sources/telegram.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sentiment.sources.telegram import TelegramSource


@pytest.fixture()
def source() -> TelegramSource:
    return TelegramSource(
        api_id=12345,
        api_hash="abc123",
        channels=["crypto_news", -1001234567890],
        max_messages=10,
    )


class TestParseMessage:
    def test_parse_message(self, source: TelegramSource) -> None:
        msg = MagicMock()
        msg.text = "$ETH just hit a new ATH!"
        msg.date = datetime(2024, 2, 10, 8, 0, 0, tzinfo=timezone.utc)

        item = source._parse_message(msg)

        assert item is not None
        assert item.source == "telegram"
        assert item.symbol == "ETH/USDT"
        assert item.score == 0.0
        assert item.confidence == 0.5
        assert item.raw_text == "$ETH just hit a new ATH!"
        assert item.timestamp == datetime(2024, 2, 10, 8, 0, 0, tzinfo=timezone.utc)

    def test_parse_message_no_cashtag(self, source: TelegramSource) -> None:
        msg = MagicMock()
        msg.text = "General crypto market analysis"
        msg.date = datetime(2024, 2, 10, 8, 0, 0, tzinfo=timezone.utc)

        item = source._parse_message(msg)

        assert item is not None
        assert item.symbol == ""

    def test_parse_message_naive_datetime_gets_utc(self, source: TelegramSource) -> None:
        msg = MagicMock()
        msg.text = "$BTC update"
        msg.date = datetime(2024, 2, 10, 8, 0, 0)  # no tzinfo

        item = source._parse_message(msg)

        assert item is not None
        assert item.timestamp.tzinfo is not None

    def test_skip_none_text(self, source: TelegramSource) -> None:
        """Message with text=None should return None."""
        msg = MagicMock()
        msg.text = None

        result = source._parse_message(msg)

        assert result is None


class TestExtractSymbol:
    def test_eth_cashtag(self, source: TelegramSource) -> None:
        assert source._extract_symbol("$ETH is moving") == "ETH/USDT"

    def test_btc_cashtag(self, source: TelegramSource) -> None:
        assert source._extract_symbol("$BTC to the moon") == "BTC/USDT"

    def test_sol_cashtag(self, source: TelegramSource) -> None:
        assert source._extract_symbol("$SOL ecosystem growing") == "SOL/USDT"

    def test_no_cashtag_no_keyword_returns_empty(self, source: TelegramSource) -> None:
        assert source._extract_symbol("nothing relevant here") == ""

    def test_unknown_cashtag_returns_empty(self, source: TelegramSource) -> None:
        assert source._extract_symbol("$FOOBAR is interesting") == ""


class TestFetch:
    def test_fetch_returns_empty_when_telethon_none(self) -> None:
        """When telethon is not installed (None), fetch returns []."""
        with patch("sentiment.sources.telegram.TelegramClient", None):
            src = TelegramSource(
                api_id=1,
                api_hash="x",
                channels=["test"],
                max_messages=5,
            )
            result = src.fetch()
        assert result == []

    def test_fetch_error_returns_empty(self, source: TelegramSource) -> None:
        """If _fetch_async raises, fetch returns []."""
        with patch.object(source, "_fetch_async", side_effect=RuntimeError("conn error")):
            result = source.fetch()
        assert result == []

    def test_fetch_returns_items(self, source: TelegramSource) -> None:
        """fetch returns SentimentItems from mock messages via _fetch_async."""
        from sentiment.models import SentimentItem

        expected_items = [
            SentimentItem(
                source="telegram",
                symbol="BTC/USDT",
                score=0.0,
                confidence=0.5,
                raw_text="$BTC looking good",
                timestamp=datetime(2024, 2, 10, tzinfo=timezone.utc),
            )
        ]

        async def mock_fetch_async(symbols):
            return expected_items

        with patch.object(source, "_fetch_async", side_effect=mock_fetch_async):
            result = source.fetch()

        assert result == expected_items
