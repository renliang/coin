"""Tests for sentiment/sources/news.py."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sentiment.sources.news import CryptoPanicSource, RSSSource


# ---------------------------------------------------------------------------
# CryptoPanicSource tests
# ---------------------------------------------------------------------------


class TestCryptoPanicSource:
    def _make_source(self) -> CryptoPanicSource:
        return CryptoPanicSource(api_key="test-key")

    def test_symbol_mapping_known(self) -> None:
        assert CryptoPanicSource._code_to_symbol("BTC") == "BTC/USDT"
        assert CryptoPanicSource._code_to_symbol("ETH") == "ETH/USDT"
        assert CryptoPanicSource._code_to_symbol("SOL") == "SOL/USDT"

    def test_symbol_mapping_case_insensitive(self) -> None:
        assert CryptoPanicSource._code_to_symbol("btc") == "BTC/USDT"
        assert CryptoPanicSource._code_to_symbol("Eth") == "ETH/USDT"

    def test_symbol_mapping_unknown(self) -> None:
        assert CryptoPanicSource._code_to_symbol("UNKNOWN_COIN") == ""
        assert CryptoPanicSource._code_to_symbol("XYZ999") == ""

    def test_parse_response_basic(self) -> None:
        source = self._make_source()
        data = {
            "results": [
                {
                    "title": "Bitcoin hits new high",
                    "published_at": "2024-01-15T10:30:00Z",
                    "currencies": [{"code": "BTC"}],
                }
            ]
        }
        items = source._parse_response(data)
        assert len(items) == 1
        item = items[0]
        assert item.source == "cryptopanic"
        assert item.symbol == "BTC/USDT"
        assert item.score == 0.0
        assert item.confidence == 0.7
        assert item.raw_text == "Bitcoin hits new high"
        assert item.timestamp == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_parse_response_multiple_currencies(self) -> None:
        source = self._make_source()
        data = {
            "results": [
                {
                    "title": "Crypto market update",
                    "published_at": "2024-01-15T10:00:00Z",
                    "currencies": [{"code": "BTC"}, {"code": "ETH"}],
                }
            ]
        }
        items = source._parse_response(data)
        # One item per currency
        assert len(items) == 2
        symbols = {item.symbol for item in items}
        assert symbols == {"BTC/USDT", "ETH/USDT"}

    def test_parse_response_no_currencies(self) -> None:
        source = self._make_source()
        data = {
            "results": [
                {
                    "title": "General crypto news",
                    "published_at": "2024-01-15T10:00:00Z",
                    "currencies": [],
                }
            ]
        }
        items = source._parse_response(data)
        assert len(items) == 1
        assert items[0].symbol == ""

    def test_parse_response_unknown_currency_code(self) -> None:
        source = self._make_source()
        data = {
            "results": [
                {
                    "title": "New coin launch",
                    "published_at": "2024-01-15T10:00:00Z",
                    "currencies": [{"code": "UNKN"}],
                }
            ]
        }
        items = source._parse_response(data)
        assert len(items) == 1
        assert items[0].symbol == ""

    def test_parse_response_empty_results(self) -> None:
        source = self._make_source()
        items = source._parse_response({"results": []})
        assert items == []

    def test_parse_response_invalid_timestamp_falls_back(self) -> None:
        source = self._make_source()
        data = {
            "results": [
                {
                    "title": "Test",
                    "published_at": "not-a-date",
                    "currencies": [{"code": "BTC"}],
                }
            ]
        }
        items = source._parse_response(data)
        assert len(items) == 1
        # Should have a valid datetime (fallback to now)
        assert isinstance(items[0].timestamp, datetime)

    def test_fetch_with_api_error_returns_empty(self) -> None:
        source = self._make_source()
        with patch("requests.get", side_effect=ConnectionError("network error")):
            result = source.fetch()
        assert result == []

    def test_fetch_with_http_error_returns_empty(self) -> None:
        source = self._make_source()
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 403")
        with patch("requests.get", return_value=mock_response):
            result = source.fetch()
        assert result == []

    def test_fetch_success(self) -> None:
        source = self._make_source()
        mock_data = {
            "results": [
                {
                    "title": "ETH upgrade live",
                    "published_at": "2024-03-01T08:00:00Z",
                    "currencies": [{"code": "ETH"}],
                }
            ]
        }
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = mock_data
        with patch("requests.get", return_value=mock_response):
            result = source.fetch()
        assert len(result) == 1
        assert result[0].symbol == "ETH/USDT"
        assert result[0].raw_text == "ETH upgrade live"


# ---------------------------------------------------------------------------
# RSSSource tests
# ---------------------------------------------------------------------------


def _make_rss_entry(
    title: str = "Test headline",
    summary: str = "Test summary",
    published_parsed: tuple | None = (2024, 3, 15, 12, 0, 0, 4, 75, 0),
):
    entry = SimpleNamespace(
        title=title,
        summary=summary,
        published_parsed=published_parsed,
    )
    return entry


class TestRSSSource:
    def test_parse_entry_basic(self) -> None:
        source = RSSSource(feed_urls=[])
        entry = _make_rss_entry(title="BTC surge", summary="Bitcoin climbs 10%")
        item = source._parse_entry(entry)
        assert item.source == "rss"
        assert item.symbol == ""
        assert item.score == 0.0
        assert item.confidence == 0.5
        assert "BTC surge" in item.raw_text
        assert "Bitcoin climbs 10%" in item.raw_text

    def test_parse_entry_timestamp(self) -> None:
        source = RSSSource(feed_urls=[])
        entry = _make_rss_entry(published_parsed=(2024, 3, 15, 12, 0, 0, 4, 75, 0))
        item = source._parse_entry(entry)
        assert item.timestamp == datetime(2024, 3, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_entry_no_published_falls_back(self) -> None:
        source = RSSSource(feed_urls=[])
        entry = _make_rss_entry(published_parsed=None)
        item = source._parse_entry(entry)
        assert isinstance(item.timestamp, datetime)

    def test_parse_entry_no_summary(self) -> None:
        source = RSSSource(feed_urls=[])
        entry = SimpleNamespace(title="Solo title", summary=None, published_parsed=None)
        item = source._parse_entry(entry)
        assert item.raw_text == "Solo title"

    def test_default_feed_urls(self) -> None:
        source = RSSSource()
        assert len(source._feed_urls) == 2
        assert any("cointelegraph" in url for url in source._feed_urls)
        assert any("coindesk" in url for url in source._feed_urls)

    def test_custom_feed_urls(self) -> None:
        urls = ["https://example.com/feed1", "https://example.com/feed2"]
        source = RSSSource(feed_urls=urls)
        assert source._feed_urls == urls

    def test_fetch_uses_feedparser(self) -> None:
        entries = [
            _make_rss_entry(title=f"News {i}") for i in range(25)
        ]
        mock_feed = SimpleNamespace(entries=entries)
        source = RSSSource(feed_urls=["https://fake.feed/rss"])
        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch()
        # Max 20 entries per feed
        assert len(result) == 20

    def test_fetch_multiple_feeds(self) -> None:
        entries = [_make_rss_entry(title=f"Article {i}") for i in range(5)]
        mock_feed = SimpleNamespace(entries=entries)
        source = RSSSource(feed_urls=["https://feed1.com/rss", "https://feed2.com/rss"])
        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch()
        assert len(result) == 10  # 5 per feed × 2 feeds

    def test_fetch_error_on_one_feed_continues(self) -> None:
        good_entries = [_make_rss_entry(title="Good article")]
        good_feed = SimpleNamespace(entries=good_entries)

        call_count = 0

        def fake_parse(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("network error")
            return good_feed

        source = RSSSource(feed_urls=["https://bad.feed/rss", "https://good.feed/rss"])
        with patch("feedparser.parse", side_effect=fake_parse):
            result = source.fetch()
        # Should still return items from the second feed
        assert len(result) == 1
        assert result[0].raw_text.startswith("Good article")

    def test_fetch_returns_empty_on_all_errors(self) -> None:
        source = RSSSource(feed_urls=["https://bad.feed/rss"])
        with patch("feedparser.parse", side_effect=RuntimeError("fail")):
            result = source.fetch()
        assert result == []

    def test_fetch_with_symbols_filter_ignored(self) -> None:
        """RSSSource ignores symbols filter (returns all global news)."""
        entries = [_make_rss_entry()]
        mock_feed = SimpleNamespace(entries=entries)
        source = RSSSource(feed_urls=["https://fake.feed/rss"])
        with patch("feedparser.parse", return_value=mock_feed):
            result = source.fetch(symbols=["BTC/USDT"])
        assert len(result) == 1
