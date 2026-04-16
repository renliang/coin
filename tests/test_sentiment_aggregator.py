"""Tests for sentiment/aggregator.py."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sentiment.aggregator import aggregate, compute_boost
from sentiment.models import SentimentItem, SentimentSignal


_TS = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

_DEFAULT_WEIGHTS: dict[str, float] = {
    "twitter": 0.4,
    "telegram": 0.3,
    "news": 0.2,
    "onchain": 0.1,
}


def _make_item(
    source: str,
    symbol: str,
    score: float,
    confidence: float = 0.5,
) -> SentimentItem:
    return SentimentItem(
        source=source,
        symbol=symbol,
        score=score,
        confidence=confidence,
        raw_text="test",
        timestamp=_TS,
    )


class TestAggregate:
    def test_aggregate_empty_returns_empty(self) -> None:
        assert aggregate([], _DEFAULT_WEIGHTS) == []

    def test_aggregate_by_symbol(self) -> None:
        """Multiple sources for BTC/USDT should yield a single valid signal."""
        items = [
            _make_item("twitter", "BTC/USDT", 0.5),
            _make_item("telegram", "BTC/USDT", 0.3),
            _make_item("news", "BTC/USDT", 0.2),
        ]

        signals = aggregate(items, _DEFAULT_WEIGHTS)

        assert len(signals) == 1
        sig = signals[0]
        assert sig.symbol == "BTC/USDT"
        assert -1.0 <= sig.score <= 1.0
        assert sig.direction in ("bullish", "bearish", "neutral")
        assert 0.0 <= sig.confidence <= 1.0

    def test_aggregate_bullish_direction(self) -> None:
        items = [_make_item("twitter", "ETH/USDT", 0.8)]
        signals = aggregate(items, _DEFAULT_WEIGHTS)
        assert signals[0].direction == "bullish"

    def test_aggregate_bearish_direction(self) -> None:
        items = [_make_item("twitter", "SOL/USDT", -0.5)]
        signals = aggregate(items, _DEFAULT_WEIGHTS)
        assert signals[0].direction == "bearish"

    def test_aggregate_neutral_direction(self) -> None:
        items = [_make_item("twitter", "BNB/USDT", 0.0)]
        signals = aggregate(items, _DEFAULT_WEIGHTS)
        assert signals[0].direction == "neutral"

    def test_missing_source_normalized(self) -> None:
        """Only twitter data present — weights normalized, score matches twitter score."""
        items = [_make_item("twitter", "BTC/USDT", 0.6, confidence=0.6)]

        signals = aggregate(items, _DEFAULT_WEIGHTS)

        assert len(signals) == 1
        sig = signals[0]
        # Only twitter weight present → normalized to 1.0, score should be 0.6
        assert sig.score == pytest.approx(0.6, abs=1e-9)
        assert sig.direction == "bullish"

    def test_aggregate_multiple_symbols(self) -> None:
        """Items for different symbols should produce separate signals."""
        items = [
            _make_item("twitter", "BTC/USDT", 0.5),
            _make_item("twitter", "ETH/USDT", -0.5),
        ]

        signals = aggregate(items, _DEFAULT_WEIGHTS)

        assert len(signals) == 2
        symbols = {s.symbol for s in signals}
        assert symbols == {"BTC/USDT", "ETH/USDT"}

    def test_aggregate_empty_symbol_uses_global(self) -> None:
        """Items with no symbol should map to '__global__'."""
        items = [_make_item("news", "", 0.1)]
        signals = aggregate(items, _DEFAULT_WEIGHTS)
        assert signals[0].symbol == "__global__"

    def test_score_clamped_to_range(self) -> None:
        """Score must always be within [-1, 1] even with extreme weighted inputs."""
        items = [_make_item("twitter", "BTC/USDT", 1.0)]
        signals = aggregate(items, {"twitter": 1.0})
        assert -1.0 <= signals[0].score <= 1.0

    def test_mean_score_per_source(self) -> None:
        """Multiple items from same source should be averaged before weighting."""
        items = [
            _make_item("twitter", "BTC/USDT", 0.8),
            _make_item("twitter", "BTC/USDT", 0.2),
        ]
        signals = aggregate(items, _DEFAULT_WEIGHTS)
        # Mean of twitter = 0.5, normalized weight = 1.0 → score = 0.5
        assert signals[0].score == pytest.approx(0.5, abs=1e-9)


class TestComputeBoost:
    def test_compute_boost_bullish(self) -> None:
        signal = SentimentSignal(
            symbol="BTC/USDT", score=1.0, direction="bullish", confidence=0.8
        )
        boost = compute_boost(signal)
        assert boost == pytest.approx(0.2)

    def test_compute_boost_bearish(self) -> None:
        signal = SentimentSignal(
            symbol="BTC/USDT", score=-1.0, direction="bearish", confidence=0.8
        )
        boost = compute_boost(signal)
        assert boost == pytest.approx(-0.2)

    def test_boost_neutral_is_zero(self) -> None:
        signal = SentimentSignal(
            symbol="BTC/USDT", score=0.0, direction="neutral", confidence=0.5
        )
        boost = compute_boost(signal)
        assert boost == pytest.approx(0.0)

    def test_compute_boost_within_range(self) -> None:
        signal = SentimentSignal(
            symbol="ETH/USDT", score=0.5, direction="bullish", confidence=0.6
        )
        boost = compute_boost(signal, boost_range=0.2)
        assert -0.2 <= boost <= 0.2
        assert boost == pytest.approx(0.1)

    def test_compute_boost_custom_range(self) -> None:
        signal = SentimentSignal(
            symbol="SOL/USDT", score=0.5, direction="bullish", confidence=0.6
        )
        boost = compute_boost(signal, boost_range=0.4)
        assert boost == pytest.approx(0.2)
