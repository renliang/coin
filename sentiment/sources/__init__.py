"""Sentiment source adapters."""
from typing import Protocol

from sentiment.models import SentimentItem


class SentimentSource(Protocol):
    def fetch(self, symbols: list[str]) -> list[SentimentItem]: ...
