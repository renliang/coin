"""Tests for sentiment data models."""
from datetime import datetime

import pytest

from sentiment.models import SentimentItem, SentimentSignal


def _make_item(**kwargs) -> SentimentItem:
    defaults = dict(
        source="twitter",
        symbol="BTC/USDT",
        score=0.5,
        confidence=0.8,
        raw_text="BTC is looking bullish",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )
    defaults.update(kwargs)
    return SentimentItem(**defaults)


class TestSentimentItem:
    def test_create_valid(self):
        item = _make_item()
        assert item.source == "twitter"
        assert item.symbol == "BTC/USDT"
        assert item.score == 0.5
        assert item.confidence == 0.8
        assert item.raw_text == "BTC is looking bullish"
        assert item.timestamp == datetime(2024, 1, 1, 12, 0, 0)

    def test_score_boundary_min(self):
        item = _make_item(score=-1.0)
        assert item.score == -1.0

    def test_score_boundary_max(self):
        item = _make_item(score=1.0)
        assert item.score == 1.0

    def test_confidence_boundary_min(self):
        item = _make_item(confidence=0.0)
        assert item.confidence == 0.0

    def test_confidence_boundary_max(self):
        item = _make_item(confidence=1.0)
        assert item.confidence == 1.0

    def test_is_frozen(self):
        item = _make_item()
        with pytest.raises(AttributeError):
            item.score = 0.9  # type: ignore[misc]

    def test_score_too_low_raises(self):
        with pytest.raises(ValueError, match="score must be in"):
            _make_item(score=-1.1)

    def test_score_too_high_raises(self):
        with pytest.raises(ValueError, match="score must be in"):
            _make_item(score=1.1)

    def test_confidence_too_low_raises(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            _make_item(confidence=-0.1)

    def test_confidence_too_high_raises(self):
        with pytest.raises(ValueError, match="confidence must be in"):
            _make_item(confidence=1.1)

    def test_global_symbol_empty_string(self):
        item = _make_item(symbol="")
        assert item.symbol == ""

    def test_various_sources(self):
        for source in ("twitter", "telegram", "news", "onchain"):
            item = _make_item(source=source)
            assert item.source == source


class TestSentimentSignal:
    def test_create_valid(self):
        signal = SentimentSignal(
            symbol="BTC/USDT",
            score=0.75,
            direction="bullish",
            confidence=0.9,
        )
        assert signal.symbol == "BTC/USDT"
        assert signal.score == 0.75
        assert signal.direction == "bullish"
        assert signal.confidence == 0.9

    def test_bearish_direction(self):
        signal = SentimentSignal(
            symbol="ETH/USDT",
            score=-0.5,
            direction="bearish",
            confidence=0.7,
        )
        assert signal.direction == "bearish"

    def test_neutral_direction(self):
        signal = SentimentSignal(
            symbol="BTC/USDT",
            score=0.0,
            direction="neutral",
            confidence=0.5,
        )
        assert signal.direction == "neutral"

    def test_is_frozen(self):
        signal = SentimentSignal(
            symbol="BTC/USDT",
            score=0.5,
            direction="bullish",
            confidence=0.8,
        )
        with pytest.raises(AttributeError):
            signal.score = 0.9  # type: ignore[misc]
