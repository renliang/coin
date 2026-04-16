"""News sentiment sources: CryptoPanic API and RSS feeds."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import feedparser
import requests

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

_CODE_TO_SYMBOL: dict[str, str] = {
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


class CryptoPanicSource:
    """Fetches news from CryptoPanic API."""

    _API_URL = "https://cryptopanic.com/api/v1/posts/"

    def __init__(self, api_key: str, delay: float = 1.0) -> None:
        self._api_key = api_key
        self._delay = delay

    @staticmethod
    def _code_to_symbol(code: str) -> str:
        """Map coin code to symbol in 'XXX/USDT' format. Unknown codes return ''."""
        return _CODE_TO_SYMBOL.get(code.upper(), "")

    def _parse_response(self, data: dict) -> list[SentimentItem]:
        """Parse CryptoPanic API JSON response into SentimentItems."""
        items: list[SentimentItem] = []
        results = data.get("results", [])
        for result in results:
            title = result.get("title", "")
            published_at_str = result.get("published_at", "")
            currencies = result.get("currencies") or []

            try:
                ts = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                ts = datetime.now(tz=timezone.utc)

            if currencies:
                for currency in currencies:
                    code = currency.get("code", "")
                    symbol = self._code_to_symbol(code)
                    items.append(
                        SentimentItem(
                            source="cryptopanic",
                            symbol=symbol,
                            score=0.0,
                            confidence=0.7,
                            raw_text=title,
                            timestamp=ts,
                        )
                    )
            else:
                items.append(
                    SentimentItem(
                        source="cryptopanic",
                        symbol="",
                        score=0.0,
                        confidence=0.7,
                        raw_text=title,
                        timestamp=ts,
                    )
                )
        return items

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        """Fetch news from CryptoPanic API. Returns [] on error."""
        try:
            params: dict = {
                "auth_token": self._api_key,
                "kind": "news",
            }
            response = requests.get(self._API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            return self._parse_response(data)
        except Exception as exc:
            logger.warning("CryptoPanicSource.fetch error: %s", exc)
            return []


_DEFAULT_FEED_URLS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
]


class RSSSource:
    """Fetches news from RSS feeds."""

    def __init__(self, feed_urls: list[str] | None = None) -> None:
        self._feed_urls = feed_urls if feed_urls is not None else _DEFAULT_FEED_URLS

    def _parse_entry(self, entry) -> SentimentItem:
        """Extract title + summary from an RSS entry into a SentimentItem."""
        title = getattr(entry, "title", "") or ""
        summary = getattr(entry, "summary", "") or ""
        raw_text = f"{title} {summary}".strip()

        published_parsed = getattr(entry, "published_parsed", None)
        if published_parsed:
            try:
                ts = datetime(*published_parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                ts = datetime.now(tz=timezone.utc)
        else:
            ts = datetime.now(tz=timezone.utc)

        return SentimentItem(
            source="rss",
            symbol="",
            score=0.0,
            confidence=0.5,
            raw_text=raw_text,
            timestamp=ts,
        )

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        """Parse all configured RSS feeds, max 20 entries each. Logs errors and continues."""
        items: list[SentimentItem] = []
        for url in self._feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    items.append(self._parse_entry(entry))
            except Exception as exc:
                logger.warning("RSSSource.fetch error for %s: %s", url, exc)
        return items
