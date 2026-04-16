"""Tests for sentiment/sources/twitter.py."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from sentiment.sources.twitter import TwitterSource


@pytest.fixture()
def source() -> TwitterSource:
    return TwitterSource(
        keywords=["bitcoin", "ethereum"],
        kol_list=["@elonmusk", "VitalikButerin"],
        max_tweets=10,
    )


class TestParseTweet:
    def test_parse_tweet(self, source: TwitterSource) -> None:
        tweet = MagicMock()
        tweet.rawContent = "$BTC is going to the moon!"
        tweet.date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        item = source._parse_tweet(tweet)

        assert item.source == "twitter"
        assert item.symbol == "BTC/USDT"
        assert item.score == 0.0
        assert item.confidence == 0.6
        assert item.raw_text == "$BTC is going to the moon!"
        assert item.timestamp == datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_tweet_uses_symbol_hint_when_no_cashtag(
        self, source: TwitterSource
    ) -> None:
        tweet = MagicMock()
        tweet.rawContent = "Crypto markets are volatile today"
        tweet.date = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

        item = source._parse_tweet(tweet, symbol_hint="ETH/USDT")

        assert item.symbol == "ETH/USDT"

    def test_parse_tweet_naive_datetime_gets_utc(self, source: TwitterSource) -> None:
        tweet = MagicMock()
        tweet.rawContent = "BTC update"
        tweet.date = datetime(2024, 1, 15, 12, 0, 0)  # no tzinfo

        item = source._parse_tweet(tweet)

        assert item.timestamp.tzinfo is not None


class TestExtractSymbol:
    def test_btc_cashtag(self, source: TwitterSource) -> None:
        assert source._extract_symbol("$BTC is rising") == "BTC/USDT"

    def test_eth_cashtag(self, source: TwitterSource) -> None:
        assert source._extract_symbol("Bought some $ETH today") == "ETH/USDT"

    def test_sol_cashtag(self, source: TwitterSource) -> None:
        assert source._extract_symbol("$SOL pumping hard") == "SOL/USDT"

    def test_no_cashtag_returns_empty(self, source: TwitterSource) -> None:
        assert source._extract_symbol("crypto markets look good") == ""

    def test_unknown_cashtag_returns_empty(self, source: TwitterSource) -> None:
        assert source._extract_symbol("$UNKNOWN token") == ""

    def test_keyword_fallback(self, source: TwitterSource) -> None:
        # No cashtag but contains the ticker word
        result = source._extract_symbol("Bitcoin is moving")
        # "BTC" not in "Bitcoin", so should be empty (keyword fallback checks ticker, not full name)
        assert result == ""

    def test_cashtag_takes_priority(self, source: TwitterSource) -> None:
        assert source._extract_symbol("$ETH but also BTC") == "ETH/USDT"


class TestFetch:
    def test_fetch_error_returns_empty(self, source: TwitterSource) -> None:
        """If the scraper raises, fetch returns []."""
        with patch("sentiment.sources.twitter.sntwitter") as mock_sntwitter:
            mock_scraper = MagicMock()
            mock_scraper.get_items.side_effect = RuntimeError("network error")
            mock_sntwitter.TwitterSearchScraper.return_value = mock_scraper

            result = source.fetch()

        assert result == []

    def test_fetch_returns_items(self, source: TwitterSource) -> None:
        """fetch returns SentimentItems from mock tweets."""
        tweet1 = MagicMock()
        tweet1.rawContent = "$BTC bullish"
        tweet1.date = datetime(2024, 1, 15, tzinfo=timezone.utc)

        tweet2 = MagicMock()
        tweet2.rawContent = "$ETH breaking out"
        tweet2.date = datetime(2024, 1, 15, tzinfo=timezone.utc)

        with patch("sentiment.sources.twitter.sntwitter") as mock_sntwitter:
            mock_scraper = MagicMock()
            mock_scraper.get_items.return_value = iter([tweet1, tweet2])
            mock_sntwitter.TwitterSearchScraper.return_value = mock_scraper

            result = source.fetch()

        assert len(result) >= 1
        assert all(item.source == "twitter" for item in result)

    def test_fetch_returns_empty_when_snscrape_none(self) -> None:
        """When snscrape is not installed (None), fetch returns []."""
        with patch("sentiment.sources.twitter.sntwitter", None):
            src = TwitterSource(keywords=["btc"], kol_list=[], max_tweets=5)
            result = src.fetch()
        assert result == []
