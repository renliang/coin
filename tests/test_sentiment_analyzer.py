"""Tests for VADER sentiment analyzer with crypto lexicon and onchain rules."""
from datetime import datetime

import pytest

from sentiment.analyzer import analyze_onchain, analyze_text
from sentiment.models import SentimentItem


def _make_item(raw_text: str, score: float = 0.0, confidence: float = 0.5) -> SentimentItem:
    return SentimentItem(
        source="onchain",
        symbol="BTC/USDT",
        score=score,
        confidence=confidence,
        raw_text=raw_text,
        timestamp=datetime(2024, 1, 1),
    )


class TestAnalyzeText:
    def test_bullish_text(self) -> None:
        score = analyze_text("BTC is going to the moon! Super bullish!")
        assert score > 0.3, f"Expected bullish score > 0.3, got {score}"

    def test_bearish_text(self) -> None:
        score = analyze_text("This is a total rug pull, crash incoming")
        assert score < -0.3, f"Expected bearish score < -0.3, got {score}"

    def test_neutral_text(self) -> None:
        score = analyze_text("Bitcoin traded at 65000 today")
        assert -0.3 <= score <= 0.3, f"Expected neutral score in [-0.3, 0.3], got {score}"

    def test_crypto_lexicon_boost(self) -> None:
        moon_score = analyze_text("moon")
        increase_score = analyze_text("increase")
        assert moon_score > increase_score, (
            f"Expected 'moon' ({moon_score}) to score higher than 'increase' ({increase_score})"
        )


class TestAnalyzeOnchain:
    def test_large_inflow_bearish(self) -> None:
        raw = '{"direction": "inflow", "amount_usd": 50000000}'
        item = _make_item(raw)
        result = analyze_onchain(item)
        assert result.score < 0, f"Expected negative score for inflow, got {result.score}"

    def test_large_outflow_bullish(self) -> None:
        raw = '{"direction": "outflow", "amount_usd": 50000000}'
        item = _make_item(raw)
        result = analyze_onchain(item)
        assert result.score > 0, f"Expected positive score for outflow, got {result.score}"

    def test_inflow_magnitude_capped_at_1(self) -> None:
        raw = '{"direction": "inflow", "amount_usd": 100000000}'
        item = _make_item(raw)
        result = analyze_onchain(item)
        assert result.score == -1.0

    def test_outflow_magnitude_capped_at_1(self) -> None:
        raw = '{"direction": "outflow", "amount_usd": 100000000}'
        item = _make_item(raw)
        result = analyze_onchain(item)
        assert result.score == 1.0

    def test_partial_inflow_proportional(self) -> None:
        raw = '{"direction": "inflow", "amount_usd": 5000000}'
        item = _make_item(raw)
        result = analyze_onchain(item)
        assert result.score == pytest.approx(-0.5)

    def test_invalid_json_returns_neutral(self) -> None:
        item = _make_item("not valid json")
        result = analyze_onchain(item)
        assert result.score == 0.0
        assert result.confidence == 0.3

    def test_missing_fields_returns_neutral(self) -> None:
        item = _make_item('{"direction": "inflow"}')
        result = analyze_onchain(item)
        assert result.score == 0.0
        assert result.confidence == 0.3

    def test_returns_new_item_immutable(self) -> None:
        raw = '{"direction": "outflow", "amount_usd": 20000000}'
        item = _make_item(raw, score=0.0)
        result = analyze_onchain(item)
        assert result is not item
        assert item.score == 0.0  # original unchanged
