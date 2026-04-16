"""Multi-source sentiment aggregator with weighted fusion."""
from __future__ import annotations

from collections import defaultdict

from sentiment.models import SentimentItem, SentimentSignal


def aggregate(
    items: list[SentimentItem],
    weights: dict[str, float],
) -> list[SentimentSignal]:
    """Aggregate SentimentItems into SentimentSignals by symbol.

    - Groups items by symbol (empty symbol -> "__global__")
    - Within each symbol, takes the mean score per source
    - Computes a weighted sum, normalizing for sources that are absent
    - direction: score > 0.1 -> "bullish", < -0.1 -> "bearish", else "neutral"
    - Score is clamped to [-1, 1]
    """
    if not items:
        return []

    # Group items by symbol
    by_symbol: dict[str, list[SentimentItem]] = defaultdict(list)
    for item in items:
        key = item.symbol if item.symbol else "__global__"
        by_symbol[key].append(item)

    signals: list[SentimentSignal] = []

    for symbol, symbol_items in by_symbol.items():
        # Mean score per source
        source_scores: dict[str, float] = {}
        source_confidences: dict[str, list[float]] = defaultdict(list)
        by_source: dict[str, list[float]] = defaultdict(list)

        for item in symbol_items:
            by_source[item.source].append(item.score)
            source_confidences[item.source].append(item.confidence)

        for source, scores in by_source.items():
            source_scores[source] = sum(scores) / len(scores)

        # Weighted sum — normalize by the weight of sources that are present
        present_weight_total = sum(
            w for src, w in weights.items() if src in source_scores
        )

        if present_weight_total == 0.0:
            # Fallback: equal weight across present sources
            n = len(source_scores)
            weighted_score = sum(source_scores.values()) / n if n else 0.0
        else:
            weighted_score = sum(
                source_scores[src] * (weights[src] / present_weight_total)
                for src in source_scores
                if src in weights
            )
            # Handle sources not in weights dict
            sources_without_weight = [s for s in source_scores if s not in weights]
            if sources_without_weight:
                extra = sum(source_scores[s] for s in sources_without_weight) / len(
                    sources_without_weight
                )
                weighted_score = (weighted_score + extra) / 2.0

        # Clamp to [-1, 1]
        clamped = max(-1.0, min(1.0, weighted_score))

        # Direction
        if clamped > 0.1:
            direction = "bullish"
        elif clamped < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        # Mean confidence across all items for this symbol
        avg_confidence = sum(i.confidence for i in symbol_items) / len(symbol_items)
        avg_confidence = max(0.0, min(1.0, avg_confidence))

        signals.append(
            SentimentSignal(
                symbol=symbol,
                score=clamped,
                direction=direction,
                confidence=avg_confidence,
            )
        )

    return signals


def compute_boost(signal: SentimentSignal, boost_range: float = 0.2) -> float:
    """Return a position-size boost in [-boost_range, +boost_range].

    A bullish signal (score=1) returns +boost_range.
    A bearish signal (score=-1) returns -boost_range.
    A neutral signal (score=0) returns 0.
    """
    return signal.score * boost_range
