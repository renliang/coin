"""Sentiment analysis using VADER with crypto lexicon extension and onchain rules."""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from sentiment.models import SentimentItem

_CRYPTO_LEXICON = {
    "moon": 3.0,
    "mooning": 3.2,
    "bullish": 2.5,
    "pump": 2.0,
    "breakout": 1.8,
    "hodl": 1.5,
    "accumulate": 1.5,
    "dip": -1.0,
    "buy the dip": 1.5,
    "bearish": -2.5,
    "dump": -2.5,
    "crash": -3.0,
    "rug": -3.5,
    "rugpull": -3.5,
    "scam": -3.0,
    "rekt": -2.5,
    "fud": -2.0,
    "liquidated": -2.5,
    "whale": 0.5,
    "diamond hands": 2.0,
    "paper hands": -1.5,
}

_analyzer: Optional[SentimentIntensityAnalyzer] = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    """Return the global VADER analyzer singleton, initializing lazily."""
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(_CRYPTO_LEXICON)
    return _analyzer


def analyze_text(text: str) -> float:
    """Analyze text sentiment using VADER with crypto lexicon extension.

    Returns a score in [-1, 1] where -1 is most negative and 1 is most positive.
    """
    analyzer = _get_analyzer()
    scores = analyzer.polarity_scores(text)
    return scores["compound"]


def analyze_onchain(item: SentimentItem) -> SentimentItem:
    """Rule-based sentiment analysis for onchain data.

    Parses item.raw_text as JSON with fields:
    - direction: "inflow" or "outflow"
    - amount_usd: float

    Inflow → negative score (sell pressure)
    Outflow → positive score (accumulation)
    Invalid JSON → score=0.0, confidence=0.3
    """
    try:
        data = json.loads(item.raw_text)
        direction = data["direction"]
        amount_usd = float(data["amount_usd"])

        magnitude = min(amount_usd / 10_000_000, 1.0)

        if direction == "inflow":
            score = -magnitude
        elif direction == "outflow":
            score = magnitude
        else:
            return replace(item, score=0.0, confidence=0.3)

        return replace(item, score=score, confidence=min(magnitude, 1.0))

    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return replace(item, score=0.0, confidence=0.3)
