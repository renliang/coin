"""Twitter/X sentiment source via snscrape."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

try:
    import snscrape.modules.twitter as sntwitter
except Exception:
    sntwitter = None  # type: ignore[assignment]

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

_CASHTAG_MAP: dict[str, str] = {
    "BTC": "BTC/USDT",
    "ETH": "ETH/USDT",
    "SOL": "SOL/USDT",
    "BNB": "BNB/USDT",
    "XRP": "XRP/USDT",
    "ADA": "ADA/USDT",
    "DOGE": "DOGE/USDT",
    "DOT": "DOT/USDT",
    "AVAX": "AVAX/USDT",
    "MATIC": "MATIC/USDT",
    "LINK": "LINK/USDT",
    "UNI": "UNI/USDT",
    "LTC": "LTC/USDT",
    "ATOM": "ATOM/USDT",
    "ETC": "ETC/USDT",
    "XLM": "XLM/USDT",
    "BCH": "BCH/USDT",
    "ALGO": "ALGO/USDT",
    "VET": "VET/USDT",
    "FIL": "FIL/USDT",
    "TRX": "TRX/USDT",
    "NEAR": "NEAR/USDT",
    "APT": "APT/USDT",
    "ARB": "ARB/USDT",
    "OP": "OP/USDT",
    "SUI": "SUI/USDT",
}

_CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")


class TwitterSource:
    """Fetches tweets from Twitter/X using snscrape."""

    def __init__(
        self,
        keywords: list[str],
        kol_list: list[str],
        max_tweets: int = 50,
    ) -> None:
        self._keywords = keywords
        self._kol_list = kol_list
        self._max_tweets = max_tweets

    def _extract_symbol(self, text: str) -> str:
        """Find $CASHTAG in text and map to 'XXX/USDT'. Falls back to keyword matching."""
        match = _CASHTAG_RE.search(text)
        if match:
            ticker = match.group(1).upper()
            return _CASHTAG_MAP.get(ticker, "")

        # Keyword fallback
        text_upper = text.upper()
        for ticker, symbol in _CASHTAG_MAP.items():
            if ticker in text_upper:
                return symbol
        return ""

    def _parse_tweet(self, tweet, symbol_hint: str = "") -> SentimentItem:
        """Parse a tweet object into a SentimentItem."""
        raw_text = getattr(tweet, "rawContent", "") or ""
        date = getattr(tweet, "date", None)
        if isinstance(date, datetime):
            ts = date if date.tzinfo is not None else date.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(tz=timezone.utc)

        symbol = self._extract_symbol(raw_text) or symbol_hint

        return SentimentItem(
            source="twitter",
            symbol=symbol,
            score=0.0,
            confidence=0.6,
            raw_text=raw_text,
            timestamp=ts,
        )

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        """Fetch tweets from KOL list + keyword queries. Returns [] on error."""
        if sntwitter is None:
            logger.warning("snscrape is not installed; TwitterSource.fetch returns []")
            return []

        items: list[SentimentItem] = []
        queries: list[tuple[str, str]] = []

        # KOL-based queries
        for kol in self._kol_list:
            handle = kol.lstrip("@")
            queries.append((f"from:{handle}", ""))

        # Keyword-based queries
        for kw in self._keywords:
            queries.append((kw, ""))

        for query, symbol_hint in queries:
            try:
                scraper = sntwitter.TwitterSearchScraper(query)
                for i, tweet in enumerate(scraper.get_items()):
                    if i >= self._max_tweets:
                        break
                    items.append(self._parse_tweet(tweet, symbol_hint=symbol_hint))
            except Exception as exc:
                logger.warning("TwitterSource.fetch error for query %r: %s", query, exc)

        return items
