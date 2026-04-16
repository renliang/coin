"""Telegram sentiment source via Telethon."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except Exception:
    TelegramClient = None  # type: ignore[assignment,misc]
    StringSession = None  # type: ignore[assignment]

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


class TelegramSource:
    """Fetches messages from Telegram channels using Telethon."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        channels: list[str | int],
        max_messages: int = 50,
    ) -> None:
        self._api_id = api_id
        self._api_hash = api_hash
        self._channels = channels
        self._max_messages = max_messages

    def _extract_symbol(self, text: str) -> str:
        """Find $CASHTAG in text and map to 'XXX/USDT'. Falls back to keyword matching."""
        match = _CASHTAG_RE.search(text)
        if match:
            ticker = match.group(1).upper()
            return _CASHTAG_MAP.get(ticker, "")

        text_upper = text.upper()
        for ticker, symbol in _CASHTAG_MAP.items():
            if ticker in text_upper:
                return symbol
        return ""

    def _parse_message(self, msg) -> SentimentItem | None:
        """Parse a Telethon message into a SentimentItem. Returns None if text is absent."""
        text = getattr(msg, "text", None)
        if text is None:
            return None

        date = getattr(msg, "date", None)
        if isinstance(date, datetime):
            ts = date if date.tzinfo is not None else date.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(tz=timezone.utc)

        symbol = self._extract_symbol(text)

        return SentimentItem(
            source="telegram",
            symbol=symbol,
            score=0.0,
            confidence=0.5,
            raw_text=text,
            timestamp=ts,
        )

    async def _fetch_async(self, symbols: list[str] | None) -> list[SentimentItem]:
        """Async implementation: connects to Telegram and iterates messages."""
        items: list[SentimentItem] = []
        async with TelegramClient(StringSession(), self._api_id, self._api_hash) as client:
            for channel in self._channels:
                try:
                    async for msg in client.iter_messages(channel, limit=self._max_messages):
                        parsed = self._parse_message(msg)
                        if parsed is not None:
                            items.append(parsed)
                except Exception as exc:
                    logger.warning(
                        "TelegramSource._fetch_async error for channel %r: %s", channel, exc
                    )
        return items

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        """Fetch messages from configured channels. Returns [] on error."""
        if TelegramClient is None:
            logger.warning("telethon is not installed; TelegramSource.fetch returns []")
            return []

        try:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._fetch_async(symbols))
            finally:
                loop.close()
        except Exception as exc:
            logger.warning("TelegramSource.fetch error: %s", exc)
            return []
