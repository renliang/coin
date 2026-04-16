"""Alternative.me 恐惧贪婪指数 — 完全免费，无需 API Key。"""
import logging
from datetime import datetime, timezone

import requests

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

# 恐惧贪婪指数 → [-1, 1] 映射
# 0=极度恐惧 → -1.0,  50=中性 → 0.0,  100=极度贪婪 → 1.0
def _fgi_to_score(value: int) -> float:
    return round((value - 50) / 50, 4)


class FearGreedSource:
    """Alternative.me Crypto Fear & Greed Index."""

    API_URL = "https://api.alternative.me/fng/"

    def __init__(self, limit: int = 1) -> None:
        self._limit = limit

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        try:
            resp = requests.get(self.API_URL, params={"limit": self._limit}, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            items: list[SentimentItem] = []
            for entry in data.get("data", []):
                value = int(entry["value"])
                score = _fgi_to_score(value)
                classification = entry.get("value_classification", "")
                ts = datetime.fromtimestamp(int(entry["timestamp"]), tz=timezone.utc)

                items.append(SentimentItem(
                    source="feargreed",
                    symbol="",  # 全局指标
                    score=score,
                    confidence=0.8,
                    raw_text=f"Fear & Greed Index: {value} ({classification})",
                    timestamp=ts,
                ))

            return items
        except Exception:
            logger.warning("Fear & Greed Index fetch failed", exc_info=True)
            return []
