"""Sentiment data models."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SentimentItem:
    source: str          # "twitter" / "telegram" / "news" / "onchain"
    symbol: str          # "BTC/USDT" or "" (global)
    score: float         # [-1, 1]
    confidence: float    # [0, 1]
    raw_text: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not -1.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [-1, 1], got {self.score}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")


@dataclass(frozen=True)
class SentimentSignal:
    symbol: str
    score: float         # [-1, 1]
    direction: str       # "bullish" / "bearish" / "neutral"
    confidence: float    # [0, 1]
