# Sentiment + Portfolio 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 coin 项目新增舆情分析模块和多策略组合管理模块，实现全自动运行。

**Architecture:** 在现有 `scanner/` 同级新增 `sentiment/` 和 `portfolio/` 两个 Python 包。舆情模块采集 Twitter/Telegram/新闻/链上数据，融合为情绪信号注入评分。组合模块基于 Riskfolio-Lib 做策略权重分配，三层风控，自动再平衡。两个模块通过 CLI 子命令和 serve 定时任务集成。

**Tech Stack:** Python 3.11+, snscrape, Telethon, vaderSentiment, feedparser, Riskfolio-Lib, QuantStats, SQLite, APScheduler

---

## File Structure

### New Files

```
sentiment/
├── __init__.py              # 包初始化 + SentimentConfig dataclass
├── models.py                # SentimentItem, SentimentSignal dataclasses
├── store.py                 # SQLite 表创建 + CRUD（sentiment_items, sentiment_signals）
├── sources/
│   ├── __init__.py          # Source protocol 定义
│   ├── twitter.py           # snscrape 抓取
│   ├── telegram.py          # Telethon 监听
│   ├── news.py              # CryptoPanic API + RSS
│   └── onchain.py           # Etherscan 大额转账
├── analyzer.py              # VADER + crypto 词典 + 链上规则引擎
└── aggregator.py            # 多源融合 → SentimentSignal

portfolio/
├── __init__.py              # 包初始化 + PortfolioConfig dataclass
├── models.py                # StrategyResult, PortfolioState dataclasses
├── store.py                 # SQLite 表创建 + CRUD（portfolio_nav, strategy_weights, risk_events）
├── allocator.py             # Riskfolio-Lib CVaR 优化
├── risk.py                  # 三层风控
├── rebalancer.py            # 自动再平衡
└── tracker.py               # QuantStats 绩效报告
```

### Modified Files

```
cli/__init__.py              # 新增 sentiment/portfolio 子命令
main.py                      # 新增 run_sentiment_*, run_portfolio_* 入口函数, load_config 扩展
config.yaml                  # 新增 sentiment/portfolio 配置段
requirements.txt             # 新增依赖
```

---

## Phase 1: 舆情模块

### Task 1: 数据模型与存储

**Files:**
- Create: `sentiment/__init__.py`
- Create: `sentiment/models.py`
- Create: `sentiment/store.py`
- Create: `sentiment/sources/__init__.py`
- Test: `tests/test_sentiment_models.py`

- [ ] **Step 1: Write failing tests for data models**

```python
# tests/test_sentiment_models.py
from datetime import datetime

import pytest


class TestSentimentItem:
    def test_create_item(self):
        from sentiment.models import SentimentItem

        item = SentimentItem(
            source="twitter",
            symbol="BTC/USDT",
            score=0.75,
            confidence=0.9,
            raw_text="BTC to the moon!",
            timestamp=datetime(2026, 4, 16, 12, 0, 0),
        )
        assert item.source == "twitter"
        assert item.score == 0.75
        assert item.confidence == 0.9

    def test_item_is_frozen(self):
        from sentiment.models import SentimentItem

        item = SentimentItem(
            source="news", symbol="", score=0.5,
            confidence=0.8, raw_text="test",
            timestamp=datetime(2026, 4, 16),
        )
        with pytest.raises(AttributeError):
            item.score = 0.9  # type: ignore[misc]

    def test_score_clamped(self):
        from sentiment.models import SentimentItem

        with pytest.raises(ValueError):
            SentimentItem(
                source="twitter", symbol="BTC/USDT",
                score=1.5, confidence=0.5, raw_text="x",
                timestamp=datetime(2026, 4, 16),
            )


class TestSentimentSignal:
    def test_create_signal(self):
        from sentiment.models import SentimentSignal

        sig = SentimentSignal(
            symbol="BTC/USDT", score=0.6,
            direction="bullish", confidence=0.85,
        )
        assert sig.direction == "bullish"

    def test_direction_from_score(self):
        from sentiment.models import SentimentSignal

        assert SentimentSignal(symbol="", score=0.3, direction="bullish", confidence=0.5).direction == "bullish"
        assert SentimentSignal(symbol="", score=-0.3, direction="bearish", confidence=0.5).direction == "bearish"
        assert SentimentSignal(symbol="", score=0.0, direction="neutral", confidence=0.5).direction == "neutral"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentiment'`

- [ ] **Step 3: Implement data models**

```python
# sentiment/__init__.py
"""舆情分析模块。"""

# sentiment/models.py
"""舆情数据模型。"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SentimentItem:
    """单条舆情数据。"""
    source: str          # "twitter" / "telegram" / "news" / "onchain"
    symbol: str          # "BTC/USDT" 或 ""（全局情绪）
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
    """融合后的情绪信号。"""
    symbol: str          # "BTC/USDT" 或 ""（全局）
    score: float         # [-1, 1]
    direction: str       # "bullish" / "bearish" / "neutral"
    confidence: float    # [0, 1]
```

```python
# sentiment/sources/__init__.py
"""数据源适配器协议。"""
from typing import Protocol

from sentiment.models import SentimentItem


class SentimentSource(Protocol):
    """所有数据源必须实现此接口。"""

    def fetch(self, symbols: list[str]) -> list[SentimentItem]:
        """采集指定币种的舆情数据。symbols 为空时采集全局数据。"""
        ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_models.py -v`
Expected: All PASS

- [ ] **Step 5: Write failing tests for store**

```python
# tests/test_sentiment_store.py
import os
import tempfile
from datetime import datetime

import pytest

from sentiment.models import SentimentItem, SentimentSignal


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    os.environ["COIN_DB_PATH"] = path
    yield path
    os.environ.pop("COIN_DB_PATH", None)


class TestSentimentStore:
    def test_save_and_query_items(self, db_path):
        from sentiment.store import save_items, query_items

        items = [
            SentimentItem(
                source="twitter", symbol="BTC/USDT", score=0.8,
                confidence=0.9, raw_text="bullish tweet",
                timestamp=datetime(2026, 4, 16, 12, 0),
            ),
            SentimentItem(
                source="news", symbol="ETH/USDT", score=-0.3,
                confidence=0.7, raw_text="bearish article",
                timestamp=datetime(2026, 4, 16, 12, 5),
            ),
        ]
        save_items(items, db_path=db_path)
        result = query_items(symbol="BTC/USDT", limit=10, db_path=db_path)
        assert len(result) == 1
        assert result[0]["source"] == "twitter"
        assert result[0]["score"] == 0.8

    def test_save_and_query_signals(self, db_path):
        from sentiment.store import save_signal, query_latest_signal

        sig = SentimentSignal(
            symbol="BTC/USDT", score=0.65,
            direction="bullish", confidence=0.85,
        )
        save_signal(sig, db_path=db_path)
        result = query_latest_signal("BTC/USDT", db_path=db_path)
        assert result is not None
        assert result["direction"] == "bullish"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'save_items' from 'sentiment.store'`

- [ ] **Step 7: Implement store**

```python
# sentiment/store.py
"""舆情数据 SQLite 存储。"""
import sqlite3
from datetime import datetime

from sentiment.models import SentimentItem, SentimentSignal

_DEFAULT_DB = "scanner.db"


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    import os
    path = db_path or os.environ.get("COIN_DB_PATH", _DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            symbol TEXT NOT NULL,
            score REAL NOT NULL,
            confidence REAL NOT NULL,
            raw_text TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sentiment_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            score REAL NOT NULL,
            direction TEXT NOT NULL,
            confidence REAL NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_items(items: list[SentimentItem], db_path: str | None = None) -> int:
    conn = _get_conn(db_path)
    try:
        for item in items:
            conn.execute(
                "INSERT INTO sentiment_items (source, symbol, score, confidence, raw_text, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (item.source, item.symbol, item.score, item.confidence,
                 item.raw_text, item.timestamp.strftime("%Y-%m-%d %H:%M:%S")),
            )
        conn.commit()
        return len(items)
    finally:
        conn.close()


def query_items(
    symbol: str = "",
    source: str = "",
    limit: int = 50,
    db_path: str | None = None,
) -> list[dict]:
    conn = _get_conn(db_path)
    try:
        clauses = []
        params: list = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if source:
            clauses.append("source = ?")
            params.append(source)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = conn.execute(
            f"SELECT * FROM sentiment_items {where} ORDER BY timestamp DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_signal(signal: SentimentSignal, db_path: str | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO sentiment_signals (symbol, score, direction, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (signal.symbol, signal.score, signal.direction, signal.confidence, now),
        )
        conn.commit()
    finally:
        conn.close()


def query_latest_signal(symbol: str, db_path: str | None = None) -> dict | None:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM sentiment_signals WHERE symbol = ? ORDER BY created_at DESC LIMIT 1",
            (symbol,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_store.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add sentiment/ tests/test_sentiment_models.py tests/test_sentiment_store.py
git commit -m "feat(sentiment): add data models and SQLite store"
```

---

### Task 2: 情绪分析器（VADER + crypto 词典）

**Files:**
- Create: `sentiment/analyzer.py`
- Test: `tests/test_sentiment_analyzer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_analyzer.py
from datetime import datetime

import pytest

from sentiment.models import SentimentItem


class TestVaderAnalyzer:
    def test_bullish_text(self):
        from sentiment.analyzer import analyze_text

        result = analyze_text("BTC is going to the moon! Super bullish!")
        assert result > 0.3

    def test_bearish_text(self):
        from sentiment.analyzer import analyze_text

        result = analyze_text("This is a total rug pull, crash incoming")
        assert result < -0.3

    def test_neutral_text(self):
        from sentiment.analyzer import analyze_text

        result = analyze_text("Bitcoin traded at 65000 today")
        assert -0.3 <= result <= 0.3

    def test_crypto_lexicon_boost(self):
        from sentiment.analyzer import analyze_text

        moon_score = analyze_text("moon")
        plain_score = analyze_text("increase")
        assert moon_score > plain_score


class TestOnchainRules:
    def test_large_inflow_bearish(self):
        from sentiment.analyzer import analyze_onchain

        item = SentimentItem(
            source="onchain", symbol="BTC/USDT", score=0.0,
            confidence=1.0,
            raw_text='{"direction": "inflow", "amount_usd": 5000000, "exchange": "binance"}',
            timestamp=datetime(2026, 4, 16),
        )
        result = analyze_onchain(item)
        assert result.score < 0  # 流入交易所 = 看空

    def test_large_outflow_bullish(self):
        from sentiment.analyzer import analyze_onchain

        item = SentimentItem(
            source="onchain", symbol="BTC/USDT", score=0.0,
            confidence=1.0,
            raw_text='{"direction": "outflow", "amount_usd": 5000000, "exchange": "binance"}',
            timestamp=datetime(2026, 4, 16),
        )
        result = analyze_onchain(item)
        assert result.score > 0  # 流出交易所 = 看多
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_analyzer.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Install vaderSentiment**

Run: `.venv/bin/pip install vaderSentiment && echo 'vaderSentiment>=3.3.2' >> requirements.txt`

- [ ] **Step 4: Implement analyzer**

```python
# sentiment/analyzer.py
"""情绪分析 — VADER + 加密货币词典 + 链上规则引擎。"""
import json

from dataclasses import replace
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from sentiment.models import SentimentItem

# 加密货币专用词典扩展
_CRYPTO_LEXICON: dict[str, float] = {
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

_analyzer: SentimentIntensityAnalyzer | None = None


def _get_analyzer() -> SentimentIntensityAnalyzer:
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentIntensityAnalyzer()
        _analyzer.lexicon.update(_CRYPTO_LEXICON)
    return _analyzer


def analyze_text(text: str) -> float:
    """对文本做情绪分析，返回 [-1, 1] 分值。"""
    analyzer = _get_analyzer()
    scores = analyzer.polarity_scores(text)
    return float(scores["compound"])


def analyze_onchain(item: SentimentItem) -> SentimentItem:
    """链上数据走规则引擎，返回带 score 的新 SentimentItem。"""
    try:
        data = json.loads(item.raw_text)
    except (json.JSONDecodeError, TypeError):
        return replace(item, score=0.0, confidence=0.3)

    direction = data.get("direction", "")
    amount = data.get("amount_usd", 0)

    # 金额越大信号越强
    magnitude = min(amount / 10_000_000, 1.0)  # 1000 万美元 = 满分

    if direction == "inflow":
        score = -magnitude  # 流入交易所 = 卖压
    elif direction == "outflow":
        score = magnitude   # 流出交易所 = 囤币
    else:
        score = 0.0

    return replace(item, score=round(score, 4), confidence=0.9)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_analyzer.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sentiment/analyzer.py tests/test_sentiment_analyzer.py requirements.txt
git commit -m "feat(sentiment): add VADER analyzer with crypto lexicon and onchain rules"
```

---

### Task 3: 新闻数据源（CryptoPanic + RSS）

**Files:**
- Create: `sentiment/sources/news.py`
- Test: `tests/test_sentiment_news.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_news.py
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


class TestCryptoPanicSource:
    def test_parse_response(self):
        from sentiment.sources.news import CryptoPanicSource

        raw_response = {
            "results": [
                {
                    "title": "Bitcoin Surges Past 70K",
                    "published_at": "2026-04-16T12:00:00Z",
                    "currencies": [{"code": "BTC"}],
                    "kind": "news",
                },
                {
                    "title": "Ethereum Faces Selling Pressure",
                    "published_at": "2026-04-16T12:05:00Z",
                    "currencies": [{"code": "ETH"}],
                    "kind": "news",
                },
            ]
        }

        source = CryptoPanicSource(api_key="test_key")
        items = source._parse_response(raw_response)
        assert len(items) == 2
        assert items[0].source == "news"
        assert items[0].symbol == "BTC/USDT"
        assert items[0].raw_text == "Bitcoin Surges Past 70K"

    def test_symbol_mapping(self):
        from sentiment.sources.news import CryptoPanicSource

        source = CryptoPanicSource(api_key="test_key")
        assert source._code_to_symbol("BTC") == "BTC/USDT"
        assert source._code_to_symbol("ETH") == "ETH/USDT"
        assert source._code_to_symbol("UNKNOWN_XYZ") == ""

    @patch("sentiment.sources.news.requests.get")
    def test_fetch_with_api_error(self, mock_get):
        from sentiment.sources.news import CryptoPanicSource

        mock_get.side_effect = Exception("API timeout")
        source = CryptoPanicSource(api_key="test_key")
        items = source.fetch(symbols=["BTC/USDT"])
        assert items == []  # 失败降级为空列表


class TestRSSSource:
    def test_parse_feed_entry(self):
        from sentiment.sources.news import RSSSource

        entry = MagicMock()
        entry.title = "Crypto Market Update"
        entry.published_parsed = (2026, 4, 16, 12, 0, 0, 0, 0, 0)
        entry.get.return_value = "Crypto Market Update: BTC rallies"

        source = RSSSource(feed_urls=["https://example.com/rss"])
        item = source._parse_entry(entry)
        assert item.source == "news"
        assert "Crypto Market Update" in item.raw_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_news.py -v`
Expected: FAIL

- [ ] **Step 3: Install feedparser**

Run: `.venv/bin/pip install feedparser && echo 'feedparser>=6.0.0' >> requirements.txt`

- [ ] **Step 4: Implement news source**

```python
# sentiment/sources/news.py
"""新闻数据源 — CryptoPanic API + RSS 聚合。"""
import logging
import time
from calendar import timegm
from datetime import datetime, timezone

import feedparser
import requests

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

# 常见币种代号到交易对映射
_COIN_MAP: dict[str, str] = {
    "BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT",
    "BNB": "BNB/USDT", "XRP": "XRP/USDT", "DOGE": "DOGE/USDT",
    "ADA": "ADA/USDT", "AVAX": "AVAX/USDT", "DOT": "DOT/USDT",
    "MATIC": "MATIC/USDT", "LINK": "LINK/USDT", "UNI": "UNI/USDT",
    "ATOM": "ATOM/USDT", "LTC": "LTC/USDT", "ARB": "ARB/USDT",
    "OP": "OP/USDT", "APT": "APT/USDT", "SUI": "SUI/USDT",
}


class CryptoPanicSource:
    """CryptoPanic API 新闻源。"""

    BASE_URL = "https://cryptopanic.com/api/v1/posts/"

    def __init__(self, api_key: str, delay: float = 1.0) -> None:
        self._api_key = api_key
        self._delay = delay

    def _code_to_symbol(self, code: str) -> str:
        return _COIN_MAP.get(code.upper(), "")

    def _parse_response(self, data: dict) -> list[SentimentItem]:
        items: list[SentimentItem] = []
        for post in data.get("results", []):
            currencies = post.get("currencies") or []
            symbol = ""
            if currencies:
                symbol = self._code_to_symbol(currencies[0].get("code", ""))

            try:
                ts = datetime.fromisoformat(post["published_at"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                ts = datetime.now(timezone.utc)

            items.append(SentimentItem(
                source="news",
                symbol=symbol,
                score=0.0,  # 待 analyzer 分析
                confidence=0.7,
                raw_text=post.get("title", ""),
                timestamp=ts,
            ))
        return items

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        try:
            params = {"auth_token": self._api_key, "kind": "news"}
            if symbols:
                codes = [s.split("/")[0] for s in symbols]
                params["currencies"] = ",".join(codes)
            resp = requests.get(self.BASE_URL, params=params, timeout=10)
            resp.raise_for_status()
            return self._parse_response(resp.json())
        except Exception:
            logger.warning("CryptoPanic fetch failed", exc_info=True)
            return []


class RSSSource:
    """RSS 聚合新闻源。"""

    DEFAULT_FEEDS = [
        "https://cointelegraph.com/rss",
        "https://www.coindesk.com/arc/outboundfeeds/rss/",
    ]

    def __init__(self, feed_urls: list[str] | None = None) -> None:
        self._feed_urls = feed_urls or self.DEFAULT_FEEDS

    def _parse_entry(self, entry) -> SentimentItem:
        title = getattr(entry, "title", "")
        published = getattr(entry, "published_parsed", None)
        if published:
            ts = datetime.fromtimestamp(timegm(published), tz=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)

        summary = entry.get("summary", "") if hasattr(entry, "get") else ""
        raw_text = f"{title}. {summary}" if summary else title

        return SentimentItem(
            source="news",
            symbol="",  # RSS 通常无币种标注
            score=0.0,
            confidence=0.5,
            raw_text=raw_text,
            timestamp=ts,
        )

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        items: list[SentimentItem] = []
        for url in self._feed_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    items.append(self._parse_entry(entry))
            except Exception:
                logger.warning(f"RSS fetch failed: {url}", exc_info=True)
        return items
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_news.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sentiment/sources/news.py tests/test_sentiment_news.py requirements.txt
git commit -m "feat(sentiment): add CryptoPanic and RSS news sources"
```

---

### Task 4: 链上数据源（Etherscan）

**Files:**
- Create: `sentiment/sources/onchain.py`
- Test: `tests/test_sentiment_onchain.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_onchain.py
from datetime import datetime
from unittest.mock import patch

import pytest


class TestEtherscanSource:
    def test_parse_large_transfer(self):
        from sentiment.sources.onchain import EtherscanSource

        source = EtherscanSource(api_key="test", min_value_usd=1_000_000)
        raw_tx = {
            "from": "0xabc123",
            "to": "0xdef456",
            "value": "500000000000000000000",  # 500 ETH
            "timeStamp": "1713264000",
            "hash": "0x123",
        }
        # 假设 ETH 价格 3000 → 500 * 3000 = 1.5M → 超过阈值
        item = source._parse_transfer(raw_tx, eth_price=3000.0)
        assert item is not None
        assert item.source == "onchain"
        assert "direction" in item.raw_text

    def test_skip_small_transfer(self):
        from sentiment.sources.onchain import EtherscanSource

        source = EtherscanSource(api_key="test", min_value_usd=1_000_000)
        raw_tx = {
            "from": "0xabc123",
            "to": "0xdef456",
            "value": "1000000000000000000",  # 1 ETH
            "timeStamp": "1713264000",
            "hash": "0x123",
        }
        item = source._parse_transfer(raw_tx, eth_price=3000.0)
        assert item is None  # 3000 USD < 1M 阈值

    def test_detect_exchange_inflow(self):
        from sentiment.sources.onchain import EtherscanSource, KNOWN_EXCHANGE_ADDRESSES

        source = EtherscanSource(api_key="test", min_value_usd=1_000_000)
        exchange_addr = list(KNOWN_EXCHANGE_ADDRESSES.keys())[0]
        direction = source._classify_direction("0xwallet", exchange_addr)
        assert direction == "inflow"

    def test_detect_exchange_outflow(self):
        from sentiment.sources.onchain import EtherscanSource, KNOWN_EXCHANGE_ADDRESSES

        source = EtherscanSource(api_key="test", min_value_usd=1_000_000)
        exchange_addr = list(KNOWN_EXCHANGE_ADDRESSES.keys())[0]
        direction = source._classify_direction(exchange_addr, "0xwallet")
        assert direction == "outflow"

    @patch("sentiment.sources.onchain.requests.get")
    def test_fetch_api_error(self, mock_get):
        from sentiment.sources.onchain import EtherscanSource

        mock_get.side_effect = Exception("timeout")
        source = EtherscanSource(api_key="test", min_value_usd=1_000_000)
        assert source.fetch(symbols=[]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_onchain.py -v`
Expected: FAIL

- [ ] **Step 3: Implement onchain source**

```python
# sentiment/sources/onchain.py
"""链上数据源 — Etherscan 大额转账监控。"""
import json
import logging
from datetime import datetime, timezone

import requests

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

# 已知交易所热钱包地址（部分）
KNOWN_EXCHANGE_ADDRESSES: dict[str, str] = {
    "0x28c6c06298d514db089934071355e5743bf21d60": "binance",
    "0x21a31ee1afc51d94c2efccaa2092ad1028285549": "binance",
    "0xdfd5293d8e347dfe59e90efd55b2956a1343963d": "binance",
    "0x56eddb7aa87536c09ccc2793473599fd21a8b17f": "binance",
    "0x1ab4973a48dc892cd9971ece8e01dcc7688f8f23": "bybit",
    "0xf89d7b9c864f589bbf53a82105107622b35eaa40": "bybit",
    "0x2faf487a4414fe77e2327f0bf4ae2a264a776ad2": "ftx",
    "0x71660c4005ba85c37ccec55d0c4493e66fe775d3": "coinbase",
    "0x503828976d22510aad0201ac7ec88293211d23da": "coinbase",
}


class EtherscanSource:
    """Etherscan API 大额转账监控。"""

    BASE_URL = "https://api.etherscan.io/api"

    def __init__(self, api_key: str, min_value_usd: float = 1_000_000) -> None:
        self._api_key = api_key
        self._min_value_usd = min_value_usd

    def _classify_direction(self, from_addr: str, to_addr: str) -> str:
        from_lower = from_addr.lower()
        to_lower = to_addr.lower()
        from_is_exchange = from_lower in KNOWN_EXCHANGE_ADDRESSES
        to_is_exchange = to_lower in KNOWN_EXCHANGE_ADDRESSES

        if to_is_exchange and not from_is_exchange:
            return "inflow"
        if from_is_exchange and not to_is_exchange:
            return "outflow"
        return "transfer"

    def _parse_transfer(
        self, tx: dict, eth_price: float,
    ) -> SentimentItem | None:
        value_wei = int(tx.get("value", "0"))
        value_eth = value_wei / 1e18
        value_usd = value_eth * eth_price

        if value_usd < self._min_value_usd:
            return None

        from_addr = tx.get("from", "")
        to_addr = tx.get("to", "")
        direction = self._classify_direction(from_addr, to_addr)

        if direction == "transfer":
            return None  # 交易所之间或钱包之间忽略

        ts = datetime.fromtimestamp(int(tx.get("timeStamp", 0)), tz=timezone.utc)

        raw = json.dumps({
            "direction": direction,
            "amount_usd": round(value_usd),
            "amount_eth": round(value_eth, 2),
            "exchange": KNOWN_EXCHANGE_ADDRESSES.get(
                to_addr.lower(), KNOWN_EXCHANGE_ADDRESSES.get(from_addr.lower(), "unknown")
            ),
            "tx_hash": tx.get("hash", ""),
        })

        return SentimentItem(
            source="onchain",
            symbol="ETH/USDT",
            score=0.0,  # 待 analyzer.analyze_onchain 处理
            confidence=0.9,
            raw_text=raw,
            timestamp=ts,
        )

    def _fetch_eth_price(self) -> float:
        try:
            resp = requests.get(
                self.BASE_URL,
                params={"module": "stats", "action": "ethprice", "apikey": self._api_key},
                timeout=10,
            )
            data = resp.json()
            return float(data["result"]["ethusd"])
        except Exception:
            logger.warning("Failed to fetch ETH price, using fallback")
            return 3000.0

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        try:
            eth_price = self._fetch_eth_price()
            resp = requests.get(
                self.BASE_URL,
                params={
                    "module": "account",
                    "action": "txlist",
                    "address": list(KNOWN_EXCHANGE_ADDRESSES.keys())[0],
                    "page": 1,
                    "offset": 50,
                    "sort": "desc",
                    "apikey": self._api_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            txs = data.get("result", [])
            if not isinstance(txs, list):
                return []

            items: list[SentimentItem] = []
            for tx in txs:
                item = self._parse_transfer(tx, eth_price)
                if item is not None:
                    items.append(item)
            return items
        except Exception:
            logger.warning("Etherscan fetch failed", exc_info=True)
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_onchain.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sentiment/sources/onchain.py tests/test_sentiment_onchain.py
git commit -m "feat(sentiment): add Etherscan onchain whale tracking source"
```

---

### Task 5: Twitter 数据源

**Files:**
- Create: `sentiment/sources/twitter.py`
- Test: `tests/test_sentiment_twitter.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_twitter.py
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


class TestTwitterSource:
    def test_parse_tweet(self):
        from sentiment.sources.twitter import TwitterSource

        source = TwitterSource(keywords=["BTC"], kol_list=[])
        tweet = MagicMock()
        tweet.rawContent = "BTC is pumping hard! $100k incoming"
        tweet.date = datetime(2026, 4, 16, 12, 0, 0)
        tweet.user.username = "crypto_trader"

        item = source._parse_tweet(tweet, symbol_hint="BTC/USDT")
        assert item.source == "twitter"
        assert item.symbol == "BTC/USDT"
        assert "BTC is pumping" in item.raw_text

    def test_extract_symbols_from_text(self):
        from sentiment.sources.twitter import TwitterSource

        source = TwitterSource(keywords=["BTC", "ETH"], kol_list=[])
        assert source._extract_symbol("$BTC looking strong") == "BTC/USDT"
        assert source._extract_symbol("$ETH breaking out") == "ETH/USDT"
        assert source._extract_symbol("crypto market is up") == ""

    @patch("sentiment.sources.twitter.sntwitter")
    def test_fetch_error_returns_empty(self, mock_sn):
        from sentiment.sources.twitter import TwitterSource

        mock_sn.TwitterSearchScraper.side_effect = Exception("blocked")
        source = TwitterSource(keywords=["BTC"], kol_list=[])
        assert source.fetch(symbols=["BTC/USDT"]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_twitter.py -v`
Expected: FAIL

- [ ] **Step 3: Install snscrape**

Run: `.venv/bin/pip install snscrape && echo 'snscrape>=0.7.0' >> requirements.txt`

- [ ] **Step 4: Implement Twitter source**

```python
# sentiment/sources/twitter.py
"""Twitter/X 数据源 — snscrape 抓取。"""
import logging
import re
from datetime import datetime, timezone

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

try:
    import snscrape.modules.twitter as sntwitter
except ImportError:
    sntwitter = None  # type: ignore[assignment]

# 币种 cashtag 到交易对映射
_CASHTAG_MAP: dict[str, str] = {
    "BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT",
    "BNB": "BNB/USDT", "XRP": "XRP/USDT", "DOGE": "DOGE/USDT",
    "ADA": "ADA/USDT", "AVAX": "AVAX/USDT", "DOT": "DOT/USDT",
    "LINK": "LINK/USDT", "UNI": "UNI/USDT", "ARB": "ARB/USDT",
    "OP": "OP/USDT", "APT": "APT/USDT", "SUI": "SUI/USDT",
}

_CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")


class TwitterSource:
    """Twitter 舆情抓取（snscrape）。"""

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
        match = _CASHTAG_RE.search(text)
        if match:
            tag = match.group(1).upper()
            return _CASHTAG_MAP.get(tag, "")
        for kw in self._keywords:
            if kw.upper() in text.upper():
                return _CASHTAG_MAP.get(kw.upper(), "")
        return ""

    def _parse_tweet(self, tweet, symbol_hint: str = "") -> SentimentItem:
        text = tweet.rawContent if hasattr(tweet, "rawContent") else str(tweet)
        ts = tweet.date if hasattr(tweet, "date") else datetime.now(timezone.utc)
        symbol = symbol_hint or self._extract_symbol(text)

        return SentimentItem(
            source="twitter",
            symbol=symbol,
            score=0.0,  # 待 analyzer 分析
            confidence=0.6,
            raw_text=text,
            timestamp=ts,
        )

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        if sntwitter is None:
            logger.warning("snscrape not installed, Twitter source disabled")
            return []

        items: list[SentimentItem] = []
        queries: list[str] = []

        # KOL 推文
        for user in self._kol_list:
            queries.append(f"from:{user}")

        # 关键词搜索
        if symbols:
            for s in symbols:
                code = s.split("/")[0]
                queries.append(f"${code} OR #{code}")
        else:
            for kw in self._keywords:
                queries.append(f"${kw} OR #{kw}")

        for query in queries:
            try:
                scraper = sntwitter.TwitterSearchScraper(f"{query} lang:en")
                count = 0
                for tweet in scraper.get_items():
                    if count >= self._max_tweets:
                        break
                    symbol_hint = ""
                    if symbols and len(symbols) == 1:
                        symbol_hint = symbols[0]
                    items.append(self._parse_tweet(tweet, symbol_hint))
                    count += 1
            except Exception:
                logger.warning(f"Twitter fetch failed for query: {query}", exc_info=True)

        return items
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_twitter.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sentiment/sources/twitter.py tests/test_sentiment_twitter.py requirements.txt
git commit -m "feat(sentiment): add Twitter/X source via snscrape"
```

---

### Task 6: Telegram 数据源

**Files:**
- Create: `sentiment/sources/telegram.py`
- Test: `tests/test_sentiment_telegram.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_telegram.py
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


class TestTelegramSource:
    def test_parse_message(self):
        from sentiment.sources.telegram import TelegramSource

        source = TelegramSource(api_id=0, api_hash="", channels=[])
        msg = MagicMock()
        msg.text = "BTC looking very bullish, breakout imminent"
        msg.date = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        msg.chat.title = "Crypto Signals"

        item = source._parse_message(msg)
        assert item.source == "telegram"
        assert "BTC looking very bullish" in item.raw_text

    def test_skip_none_text(self):
        from sentiment.sources.telegram import TelegramSource

        source = TelegramSource(api_id=0, api_hash="", channels=[])
        msg = MagicMock()
        msg.text = None
        msg.date = datetime(2026, 4, 16, tzinfo=timezone.utc)

        item = source._parse_message(msg)
        assert item is None

    def test_extract_symbol_from_message(self):
        from sentiment.sources.telegram import TelegramSource

        source = TelegramSource(api_id=0, api_hash="", channels=[])
        assert source._extract_symbol("$ETH breaking out now!") == "ETH/USDT"
        assert source._extract_symbol("random chat message") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_telegram.py -v`
Expected: FAIL

- [ ] **Step 3: Install Telethon**

Run: `.venv/bin/pip install telethon && echo 'telethon>=1.36.0' >> requirements.txt`

- [ ] **Step 4: Implement Telegram source**

```python
# sentiment/sources/telegram.py
"""Telegram 数据源 — Telethon 频道监听。"""
import asyncio
import logging
import re
from datetime import datetime, timezone

from sentiment.models import SentimentItem

logger = logging.getLogger(__name__)

try:
    from telethon import TelegramClient
    from telethon.tl.types import Message
except ImportError:
    TelegramClient = None  # type: ignore[assignment,misc]

_CASHTAG_RE = re.compile(r"\$([A-Z]{2,10})\b")
_SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT",
    "BNB": "BNB/USDT", "XRP": "XRP/USDT", "DOGE": "DOGE/USDT",
    "ADA": "ADA/USDT", "AVAX": "AVAX/USDT", "LINK": "LINK/USDT",
    "ARB": "ARB/USDT", "OP": "OP/USDT", "APT": "APT/USDT",
}


class TelegramSource:
    """Telegram 频道/群组消息采集。"""

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
        match = _CASHTAG_RE.search(text)
        if match:
            tag = match.group(1).upper()
            return _SYMBOL_MAP.get(tag, "")
        for code, symbol in _SYMBOL_MAP.items():
            if code in text.upper():
                return symbol
        return ""

    def _parse_message(self, msg) -> SentimentItem | None:
        text = getattr(msg, "text", None)
        if not text:
            return None

        ts = getattr(msg, "date", datetime.now(timezone.utc))
        symbol = self._extract_symbol(text)

        return SentimentItem(
            source="telegram",
            symbol=symbol,
            score=0.0,
            confidence=0.5,
            raw_text=text,
            timestamp=ts,
        )

    async def _fetch_async(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        if TelegramClient is None:
            logger.warning("telethon not installed, Telegram source disabled")
            return []

        items: list[SentimentItem] = []
        client = TelegramClient("sentiment_session", self._api_id, self._api_hash)

        try:
            await client.start()
            for channel in self._channels:
                try:
                    async for msg in client.iter_messages(channel, limit=self._max_messages):
                        item = self._parse_message(msg)
                        if item is not None:
                            items.append(item)
                except Exception:
                    logger.warning(f"Failed to fetch from channel: {channel}", exc_info=True)
        except Exception:
            logger.warning("Telegram client failed", exc_info=True)
        finally:
            await client.disconnect()

        return items

    def fetch(self, symbols: list[str] | None = None) -> list[SentimentItem]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(
                        asyncio.run, self._fetch_async(symbols)
                    ).result(timeout=60)
            return asyncio.run(self._fetch_async(symbols))
        except Exception:
            logger.warning("Telegram fetch failed", exc_info=True)
            return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_telegram.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add sentiment/sources/telegram.py tests/test_sentiment_telegram.py requirements.txt
git commit -m "feat(sentiment): add Telegram source via Telethon"
```

---

### Task 7: 多源融合（aggregator）

**Files:**
- Create: `sentiment/aggregator.py`
- Test: `tests/test_sentiment_aggregator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sentiment_aggregator.py
from datetime import datetime

import pytest

from sentiment.models import SentimentItem, SentimentSignal


class TestAggregator:
    def _make_items(self) -> list[SentimentItem]:
        ts = datetime(2026, 4, 16, 12, 0, 0)
        return [
            SentimentItem("twitter", "BTC/USDT", 0.8, 0.9, "bullish tweet", ts),
            SentimentItem("twitter", "BTC/USDT", 0.6, 0.8, "another bullish", ts),
            SentimentItem("news", "BTC/USDT", 0.3, 0.7, "positive news", ts),
            SentimentItem("news", "BTC/USDT", -0.2, 0.6, "mixed news", ts),
            SentimentItem("onchain", "BTC/USDT", -0.5, 0.9, '{"direction":"inflow"}', ts),
        ]

    def test_aggregate_by_symbol(self):
        from sentiment.aggregator import aggregate

        items = self._make_items()
        weights = {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2}
        signals = aggregate(items, weights)

        btc_signal = next((s for s in signals if s.symbol == "BTC/USDT"), None)
        assert btc_signal is not None
        assert -1.0 <= btc_signal.score <= 1.0
        assert btc_signal.direction in ("bullish", "bearish", "neutral")

    def test_aggregate_empty_returns_neutral(self):
        from sentiment.aggregator import aggregate

        weights = {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2}
        signals = aggregate([], weights)
        assert signals == []

    def test_missing_source_normalized(self):
        from sentiment.aggregator import aggregate

        ts = datetime(2026, 4, 16)
        items = [
            SentimentItem("twitter", "ETH/USDT", 0.8, 0.9, "bullish", ts),
            # 没有 telegram / news / onchain
        ]
        weights = {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2}
        signals = aggregate(items, weights)

        eth_signal = next((s for s in signals if s.symbol == "ETH/USDT"), None)
        assert eth_signal is not None
        # 只有 twitter 数据，权重归一化后 twitter=1.0
        assert eth_signal.score > 0

    def test_compute_boost(self):
        from sentiment.aggregator import compute_boost

        sig = SentimentSignal(symbol="BTC/USDT", score=0.8, direction="bullish", confidence=0.9)
        boost = compute_boost(sig, boost_range=0.2)
        assert 0 < boost <= 0.2

        sig_bear = SentimentSignal(symbol="BTC/USDT", score=-0.8, direction="bearish", confidence=0.9)
        boost_bear = compute_boost(sig_bear, boost_range=0.2)
        assert -0.2 <= boost_bear < 0

    def test_boost_neutral_is_zero(self):
        from sentiment.aggregator import compute_boost

        sig = SentimentSignal(symbol="BTC/USDT", score=0.0, direction="neutral", confidence=0.5)
        assert compute_boost(sig, boost_range=0.2) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sentiment_aggregator.py -v`
Expected: FAIL

- [ ] **Step 3: Implement aggregator**

```python
# sentiment/aggregator.py
"""多源舆情融合 → 统一 SentimentSignal。"""
from collections import defaultdict

from sentiment.models import SentimentItem, SentimentSignal


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def aggregate(
    items: list[SentimentItem],
    weights: dict[str, float],
) -> list[SentimentSignal]:
    """按 symbol 分组，加权融合各数据源分值。

    缺失的数据源会被跳过，权重自动归一化。
    """
    if not items:
        return []

    # 按 symbol 分组，每个 symbol 内再按 source 分组取均值
    by_symbol: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    confidence_by_symbol: dict[str, list[float]] = defaultdict(list)

    for item in items:
        key = item.symbol or "__global__"
        by_symbol[key][item.source].append(item.score)
        confidence_by_symbol[key].append(item.confidence)

    signals: list[SentimentSignal] = []

    for symbol, sources in by_symbol.items():
        # 每个 source 取均值
        source_scores: dict[str, float] = {}
        for source, scores in sources.items():
            source_scores[source] = _mean(scores)

        # 加权求和（仅计算有数据的源，归一化权重）
        available_weights = {s: w for s, w in weights.items() if s in source_scores}
        total_weight = sum(available_weights.values())
        if total_weight == 0:
            continue

        weighted_score = sum(
            source_scores[s] * (w / total_weight)
            for s, w in available_weights.items()
        )

        # 钳位到 [-1, 1]
        score = max(-1.0, min(1.0, weighted_score))

        if score > 0.1:
            direction = "bullish"
        elif score < -0.1:
            direction = "bearish"
        else:
            direction = "neutral"

        confidence = _mean(confidence_by_symbol.get(symbol, [0.5]))

        display_symbol = "" if symbol == "__global__" else symbol
        signals.append(SentimentSignal(
            symbol=display_symbol,
            score=round(score, 4),
            direction=direction,
            confidence=round(confidence, 4),
        ))

    return signals


def compute_boost(signal: SentimentSignal, boost_range: float = 0.2) -> float:
    """将情绪信号转换为评分加权因子。

    返回 [-boost_range, +boost_range] 范围的浮点数。
    """
    return round(signal.score * boost_range, 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sentiment_aggregator.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add sentiment/aggregator.py tests/test_sentiment_aggregator.py
git commit -m "feat(sentiment): add multi-source aggregator with weighted fusion"
```

---

## Phase 2: 组合管理模块

### Task 8: 组合数据模型与存储

**Files:**
- Create: `portfolio/__init__.py`
- Create: `portfolio/models.py`
- Create: `portfolio/store.py`
- Test: `tests/test_portfolio_models.py`
- Test: `tests/test_portfolio_store.py`

- [ ] **Step 1: Write failing tests for models**

```python
# tests/test_portfolio_models.py
import pytest


class TestStrategyResult:
    def test_create(self):
        from portfolio.models import StrategyResult

        sr = StrategyResult(
            strategy_id="divergence",
            sharpe=1.2,
            win_rate=0.65,
            max_drawdown=0.08,
            daily_returns=[0.01, -0.005, 0.02, 0.003],
        )
        assert sr.strategy_id == "divergence"
        assert sr.sharpe == 1.2

    def test_frozen(self):
        from portfolio.models import StrategyResult

        sr = StrategyResult(
            strategy_id="divergence", sharpe=1.0,
            win_rate=0.5, max_drawdown=0.1,
            daily_returns=[],
        )
        with pytest.raises(AttributeError):
            sr.sharpe = 2.0  # type: ignore[misc]


class TestPortfolioState:
    def test_create(self):
        from portfolio.models import PortfolioState

        state = PortfolioState(
            weights={"divergence": 0.4, "accumulation": 0.3, "breakout": 0.3},
            nav=10500.0,
            high_water_mark=10500.0,
            halted_strategies=set(),
            portfolio_halted=False,
        )
        assert state.nav == 10500.0
        assert sum(state.weights.values()) == pytest.approx(1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_models.py -v`
Expected: FAIL

- [ ] **Step 3: Implement models**

```python
# portfolio/__init__.py
"""多策略组合管理模块。"""

# portfolio/models.py
"""组合管理数据模型。"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class StrategyResult:
    """单策略绩效快照。"""
    strategy_id: str
    sharpe: float
    win_rate: float
    max_drawdown: float
    daily_returns: list[float] = field(default_factory=list)


@dataclass
class PortfolioState:
    """组合当前状态（可变 — 运行时更新）。"""
    weights: dict[str, float]
    nav: float
    high_water_mark: float
    halted_strategies: set[str] = field(default_factory=set)
    portfolio_halted: bool = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_models.py -v`
Expected: All PASS

- [ ] **Step 5: Write failing tests for store**

```python
# tests/test_portfolio_store.py
import os
from datetime import date

import pytest


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    os.environ["COIN_DB_PATH"] = path
    yield path
    os.environ.pop("COIN_DB_PATH", None)


class TestPortfolioStore:
    def test_save_and_query_nav(self, db_path):
        from portfolio.store import save_nav, query_nav_history

        save_nav(date(2026, 4, 15), nav=10000.0, hwm=10000.0, db_path=db_path)
        save_nav(date(2026, 4, 16), nav=10200.0, hwm=10200.0, db_path=db_path)

        history = query_nav_history(limit=10, db_path=db_path)
        assert len(history) == 2
        assert history[0]["nav"] == 10200.0

    def test_save_and_query_weights(self, db_path):
        from portfolio.store import save_weights, query_latest_weights

        weights = {"divergence": 0.4, "accumulation": 0.35, "breakout": 0.25}
        save_weights(date(2026, 4, 16), weights, db_path=db_path)

        result = query_latest_weights(db_path=db_path)
        assert len(result) == 3
        assert result["divergence"] == 0.4

    def test_save_risk_event(self, db_path):
        from portfolio.store import save_risk_event, query_risk_events

        save_risk_event(
            level="strategy", strategy_id="divergence",
            event_type="daily_limit", details="loss exceeded 3%",
            db_path=db_path,
        )
        events = query_risk_events(limit=10, db_path=db_path)
        assert len(events) == 1
        assert events[0]["level"] == "strategy"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_store.py -v`
Expected: FAIL

- [ ] **Step 7: Implement store**

```python
# portfolio/store.py
"""组合管理 SQLite 存储。"""
import sqlite3
from datetime import date, datetime

_DEFAULT_DB = "scanner.db"


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    import os
    path = db_path or os.environ.get("COIN_DB_PATH", _DEFAULT_DB)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS portfolio_nav (
            date TEXT PRIMARY KEY,
            nav REAL NOT NULL,
            high_water_mark REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            weight REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS risk_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def save_nav(d: date, nav: float, hwm: float, db_path: str | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO portfolio_nav (date, nav, high_water_mark) VALUES (?, ?, ?)",
            (d.isoformat(), nav, hwm),
        )
        conn.commit()
    finally:
        conn.close()


def query_nav_history(limit: int = 90, db_path: str | None = None) -> list[dict]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM portfolio_nav ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_weights(d: date, weights: dict[str, float], db_path: str | None = None) -> None:
    conn = _get_conn(db_path)
    try:
        # 删除当天旧数据再写入
        conn.execute("DELETE FROM strategy_weights WHERE date = ?", (d.isoformat(),))
        for strategy_id, weight in weights.items():
            conn.execute(
                "INSERT INTO strategy_weights (date, strategy_id, weight) VALUES (?, ?, ?)",
                (d.isoformat(), strategy_id, weight),
            )
        conn.commit()
    finally:
        conn.close()


def query_latest_weights(db_path: str | None = None) -> dict[str, float]:
    conn = _get_conn(db_path)
    try:
        row = conn.execute(
            "SELECT date FROM strategy_weights ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if not row:
            return {}
        latest_date = row["date"]
        rows = conn.execute(
            "SELECT strategy_id, weight FROM strategy_weights WHERE date = ?",
            (latest_date,),
        ).fetchall()
        return {r["strategy_id"]: r["weight"] for r in rows}
    finally:
        conn.close()


def save_risk_event(
    level: str,
    strategy_id: str,
    event_type: str,
    details: str,
    db_path: str | None = None,
) -> None:
    conn = _get_conn(db_path)
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO risk_events (level, strategy_id, event_type, details, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (level, strategy_id, event_type, details, now),
        )
        conn.commit()
    finally:
        conn.close()


def query_risk_events(limit: int = 50, db_path: str | None = None) -> list[dict]:
    conn = _get_conn(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM risk_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_store.py -v`
Expected: All PASS

- [ ] **Step 9: Commit**

```bash
git add portfolio/ tests/test_portfolio_models.py tests/test_portfolio_store.py
git commit -m "feat(portfolio): add data models and SQLite store"
```

---

### Task 9: 资金分配器（Riskfolio-Lib CVaR）

**Files:**
- Create: `portfolio/allocator.py`
- Test: `tests/test_portfolio_allocator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_portfolio_allocator.py
import pytest

from portfolio.models import StrategyResult


def _make_strategies() -> list[StrategyResult]:
    """构造 3 个策略的模拟数据。"""
    import random
    random.seed(42)
    return [
        StrategyResult(
            strategy_id="divergence", sharpe=1.5, win_rate=0.65, max_drawdown=0.08,
            daily_returns=[random.gauss(0.002, 0.01) for _ in range(90)],
        ),
        StrategyResult(
            strategy_id="accumulation", sharpe=0.8, win_rate=0.55, max_drawdown=0.12,
            daily_returns=[random.gauss(0.001, 0.015) for _ in range(90)],
        ),
        StrategyResult(
            strategy_id="breakout", sharpe=1.1, win_rate=0.60, max_drawdown=0.10,
            daily_returns=[random.gauss(0.0015, 0.012) for _ in range(90)],
        ),
    ]


class TestAllocator:
    def test_optimize_returns_valid_weights(self):
        from portfolio.allocator import optimize_weights

        strategies = _make_strategies()
        weights = optimize_weights(
            strategies, max_weight=0.5, min_weight=0.05,
        )
        assert set(weights.keys()) == {"divergence", "accumulation", "breakout"}
        assert all(0.05 <= w <= 0.5 for w in weights.values())
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_negative_sharpe_gets_min_weight(self):
        from portfolio.allocator import optimize_weights

        strategies = [
            StrategyResult("good", sharpe=1.5, win_rate=0.6, max_drawdown=0.08,
                          daily_returns=[0.01] * 90),
            StrategyResult("bad", sharpe=-0.5, win_rate=0.3, max_drawdown=0.2,
                          daily_returns=[-0.005] * 90),
        ]
        weights = optimize_weights(strategies, max_weight=0.95, min_weight=0.05)
        assert weights["bad"] == pytest.approx(0.05, abs=0.01)

    def test_fallback_equal_weight(self):
        from portfolio.allocator import optimize_weights

        # 空收益 → 无法优化 → 等权
        strategies = [
            StrategyResult("a", sharpe=0, win_rate=0, max_drawdown=0, daily_returns=[]),
            StrategyResult("b", sharpe=0, win_rate=0, max_drawdown=0, daily_returns=[]),
        ]
        weights = optimize_weights(strategies, max_weight=0.5, min_weight=0.05)
        assert weights["a"] == pytest.approx(0.5)
        assert weights["b"] == pytest.approx(0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_allocator.py -v`
Expected: FAIL

- [ ] **Step 3: Install riskfolio-lib**

Run: `.venv/bin/pip install riskfolio-lib && echo 'riskfolio-lib>=6.0.0' >> requirements.txt`

- [ ] **Step 4: Implement allocator**

```python
# portfolio/allocator.py
"""策略资金分配 — Riskfolio-Lib CVaR 优化。"""
import logging

import numpy as np
import pandas as pd

from portfolio.models import StrategyResult

logger = logging.getLogger(__name__)


def optimize_weights(
    strategies: list[StrategyResult],
    max_weight: float = 0.5,
    min_weight: float = 0.05,
) -> dict[str, float]:
    """基于历史收益率做均值-CVaR 优化，返回策略权重。

    约束：
    - 单策略权重 ∈ [min_weight, max_weight]
    - 夏普 < 0 的策略强制 min_weight
    - 数据不足时回退等权
    """
    if not strategies:
        return {}

    # 数据不足 → 等权
    has_data = all(len(s.daily_returns) >= 30 for s in strategies)
    if not has_data:
        n = len(strategies)
        return {s.strategy_id: round(1.0 / n, 4) for s in strategies}

    # 构造收益率 DataFrame
    returns_dict: dict[str, list[float]] = {}
    min_len = min(len(s.daily_returns) for s in strategies)
    for s in strategies:
        returns_dict[s.strategy_id] = s.daily_returns[:min_len]
    returns_df = pd.DataFrame(returns_dict)

    # 负夏普策略强制 min_weight
    forced_min: set[str] = set()
    for s in strategies:
        if s.sharpe < 0:
            forced_min.add(s.strategy_id)

    try:
        import riskfolio as rp

        port = rp.Portfolio(returns=returns_df)
        port.assets_stats(method_mu="hist", method_cov="hist")

        # CVaR 优化
        w = port.optimization(
            model="Classic",
            rm="CVaR",
            obj="Sharpe",
            hist=True,
            rf=0,
            l=0,
        )

        if w is None or w.empty:
            raise ValueError("Optimization returned empty weights")

        weights: dict[str, float] = {}
        for strategy_id in returns_df.columns:
            raw_w = float(w.loc[strategy_id, "weights"]) if strategy_id in w.index else min_weight
            if strategy_id in forced_min:
                raw_w = min_weight
            weights[strategy_id] = max(min_weight, min(max_weight, raw_w))

        # 归一化
        total = sum(weights.values())
        weights = {k: round(v / total, 4) for k, v in weights.items()}
        return weights

    except Exception:
        logger.warning("CVaR optimization failed, falling back to equal weight", exc_info=True)
        n = len(strategies)
        return {s.strategy_id: round(1.0 / n, 4) for s in strategies}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_allocator.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add portfolio/allocator.py tests/test_portfolio_allocator.py requirements.txt
git commit -m "feat(portfolio): add CVaR-based strategy weight allocator"
```

---

### Task 10: 三层风控

**Files:**
- Create: `portfolio/risk.py`
- Test: `tests/test_portfolio_risk.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_portfolio_risk.py
import os
from datetime import date

import pytest

from portfolio.models import PortfolioState


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    os.environ["COIN_DB_PATH"] = path
    yield path
    os.environ.pop("COIN_DB_PATH", None)


class TestRiskCheck:
    def test_strategy_daily_limit(self):
        from portfolio.risk import check_strategy_risk

        # 策略当日亏损 4% → 超过 3% 限制
        result = check_strategy_risk(
            strategy_id="divergence",
            daily_pnl_pct=-0.04,
            limit=0.03,
        )
        assert result.halted is True
        assert result.reason == "daily_limit"

    def test_strategy_within_limit(self):
        from portfolio.risk import check_strategy_risk

        result = check_strategy_risk(
            strategy_id="divergence",
            daily_pnl_pct=-0.02,
            limit=0.03,
        )
        assert result.halted is False

    def test_portfolio_drawdown_halt(self):
        from portfolio.risk import check_portfolio_risk

        state = PortfolioState(
            weights={"a": 0.5, "b": 0.5},
            nav=9400.0,
            high_water_mark=10000.0,
            halted_strategies=set(),
            portfolio_halted=False,
        )
        # 回撤 = (10000 - 9400) / 10000 = 6% → 超过 5% 限制
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is True

    def test_portfolio_within_drawdown(self):
        from portfolio.risk import check_portfolio_risk

        state = PortfolioState(
            weights={"a": 0.5, "b": 0.5},
            nav=9600.0,
            high_water_mark=10000.0,
            halted_strategies=set(),
            portfolio_halted=False,
        )
        # 回撤 = 4% → 未超过 5%
        result = check_portfolio_risk(state, drawdown_limit=0.05)
        assert result.portfolio_halted is False

    def test_update_high_water_mark(self):
        from portfolio.risk import update_hwm

        state = PortfolioState(
            weights={}, nav=10500.0, high_water_mark=10000.0,
        )
        new_state = update_hwm(state)
        assert new_state.high_water_mark == 10500.0

    def test_hwm_no_update_on_decline(self):
        from portfolio.risk import update_hwm

        state = PortfolioState(
            weights={}, nav=9500.0, high_water_mark=10000.0,
        )
        new_state = update_hwm(state)
        assert new_state.high_water_mark == 10000.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_risk.py -v`
Expected: FAIL

- [ ] **Step 3: Implement risk module**

```python
# portfolio/risk.py
"""三层风控 — 仓位级 / 策略级 / 组合级。"""
import logging
from dataclasses import dataclass

from portfolio.models import PortfolioState

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StrategyRiskResult:
    strategy_id: str
    halted: bool
    reason: str  # "" / "daily_limit"


@dataclass(frozen=True)
class PortfolioRiskResult:
    portfolio_halted: bool
    drawdown_pct: float
    reason: str  # "" / "drawdown_halt"


def check_strategy_risk(
    strategy_id: str,
    daily_pnl_pct: float,
    limit: float = 0.03,
) -> StrategyRiskResult:
    """策略级风控：单策略当日亏损超过 limit 则暂停。"""
    if daily_pnl_pct < -limit:
        logger.warning(
            f"[风控] 策略 {strategy_id} 当日亏损 {daily_pnl_pct:.2%} 超过限制 {limit:.2%}，暂停开仓"
        )
        return StrategyRiskResult(strategy_id=strategy_id, halted=True, reason="daily_limit")
    return StrategyRiskResult(strategy_id=strategy_id, halted=False, reason="")


def check_portfolio_risk(
    state: PortfolioState,
    drawdown_limit: float = 0.05,
) -> PortfolioRiskResult:
    """组合级风控：总回撤超过 drawdown_limit 则暂停所有开仓。"""
    if state.high_water_mark <= 0:
        return PortfolioRiskResult(portfolio_halted=False, drawdown_pct=0.0, reason="")

    drawdown = (state.high_water_mark - state.nav) / state.high_water_mark

    if drawdown > drawdown_limit:
        logger.warning(
            f"[风控] 组合回撤 {drawdown:.2%} 超过限制 {drawdown_limit:.2%}，暂停所有开仓"
        )
        return PortfolioRiskResult(
            portfolio_halted=True,
            drawdown_pct=round(drawdown, 4),
            reason="drawdown_halt",
        )
    return PortfolioRiskResult(
        portfolio_halted=False,
        drawdown_pct=round(drawdown, 4),
        reason="",
    )


def update_hwm(state: PortfolioState) -> PortfolioState:
    """更新高水位线。"""
    if state.nav > state.high_water_mark:
        state.high_water_mark = state.nav
    return state
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_risk.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add portfolio/risk.py tests/test_portfolio_risk.py
git commit -m "feat(portfolio): add three-layer risk control"
```

---

### Task 11: 自动再平衡

**Files:**
- Create: `portfolio/rebalancer.py`
- Test: `tests/test_portfolio_rebalancer.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_portfolio_rebalancer.py
import pytest


class TestRebalancer:
    def test_drift_detected(self):
        from portfolio.rebalancer import check_drift

        target = {"a": 0.4, "b": 0.3, "c": 0.3}
        actual = {"a": 0.6, "b": 0.25, "c": 0.15}
        drift = check_drift(target, actual, threshold=0.2)
        assert drift is True  # a 偏离 50% > 20%

    def test_no_drift(self):
        from portfolio.rebalancer import check_drift

        target = {"a": 0.4, "b": 0.3, "c": 0.3}
        actual = {"a": 0.42, "b": 0.30, "c": 0.28}
        drift = check_drift(target, actual, threshold=0.2)
        assert drift is False

    def test_compute_adjustments(self):
        from portfolio.rebalancer import compute_adjustments

        target = {"a": 0.5, "b": 0.3, "c": 0.2}
        actual = {"a": 0.7, "b": 0.2, "c": 0.1}
        total_capital = 10000.0

        adjustments = compute_adjustments(target, actual, total_capital)
        assert adjustments["a"] < 0  # 减少
        assert adjustments["b"] > 0  # 增加
        assert adjustments["c"] > 0  # 增加
        assert sum(adjustments.values()) == pytest.approx(0.0, abs=1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_rebalancer.py -v`
Expected: FAIL

- [ ] **Step 3: Implement rebalancer**

```python
# portfolio/rebalancer.py
"""自动再平衡 — 检测漂移、计算调整量。"""
import logging

logger = logging.getLogger(__name__)


def check_drift(
    target: dict[str, float],
    actual: dict[str, float],
    threshold: float = 0.2,
) -> bool:
    """检查实际权重是否偏离目标超过阈值。

    偏离度 = |actual - target| / target，任一策略超过阈值即触发。
    """
    for strategy_id, target_w in target.items():
        actual_w = actual.get(strategy_id, 0.0)
        if target_w == 0:
            continue
        drift = abs(actual_w - target_w) / target_w
        if drift > threshold:
            logger.info(
                f"[再平衡] {strategy_id} 偏离 {drift:.1%} > {threshold:.1%}"
            )
            return True
    return False


def compute_adjustments(
    target: dict[str, float],
    actual: dict[str, float],
    total_capital: float,
) -> dict[str, float]:
    """计算每个策略需要调整的资金量（正=加仓，负=减仓）。"""
    adjustments: dict[str, float] = {}
    for strategy_id, target_w in target.items():
        actual_w = actual.get(strategy_id, 0.0)
        diff = target_w - actual_w
        adjustments[strategy_id] = round(diff * total_capital, 2)
    return adjustments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_rebalancer.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add portfolio/rebalancer.py tests/test_portfolio_rebalancer.py
git commit -m "feat(portfolio): add drift detection and rebalancing"
```

---

### Task 12: 绩效追踪（QuantStats 报告）

**Files:**
- Create: `portfolio/tracker.py`
- Test: `tests/test_portfolio_tracker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_portfolio_tracker.py
import os

import pytest


class TestPortfolioTracker:
    def test_compute_strategy_stats(self):
        from portfolio.tracker import compute_strategy_stats

        daily_returns = [0.01, -0.005, 0.02, 0.003, -0.01, 0.015, 0.008]
        stats = compute_strategy_stats("divergence", daily_returns)
        assert stats["strategy_id"] == "divergence"
        assert "sharpe" in stats
        assert "max_drawdown" in stats
        assert "win_rate" in stats
        assert stats["win_rate"] > 0

    def test_compute_empty_returns(self):
        from portfolio.tracker import compute_strategy_stats

        stats = compute_strategy_stats("empty", [])
        assert stats["sharpe"] == 0.0
        assert stats["win_rate"] == 0.0

    def test_generate_report(self, tmp_path):
        from portfolio.tracker import generate_portfolio_report

        strategy_returns = {
            "divergence": [0.01, -0.005, 0.02, 0.003, -0.01] * 20,
            "accumulation": [0.005, -0.003, 0.01, -0.002, 0.008] * 20,
        }
        weights = {"divergence": 0.6, "accumulation": 0.4}
        output_path = str(tmp_path / "report.html")

        generate_portfolio_report(strategy_returns, weights, output_path)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_portfolio_tracker.py -v`
Expected: FAIL

- [ ] **Step 3: Install quantstats**

Run: `.venv/bin/pip install quantstats && echo 'quantstats>=0.0.62' >> requirements.txt`

- [ ] **Step 4: Implement tracker**

```python
# portfolio/tracker.py
"""组合级绩效追踪 — QuantStats 报告生成。"""
import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_strategy_stats(strategy_id: str, daily_returns: list[float]) -> dict:
    """计算单策略核心指标。"""
    if not daily_returns:
        return {
            "strategy_id": strategy_id,
            "sharpe": 0.0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "total_return": 0.0,
        }

    returns = np.array(daily_returns)
    wins = int(np.sum(returns > 0))
    total = len(returns)
    win_rate = wins / total if total > 0 else 0.0

    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns))
    sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0

    # 最大回撤
    cumulative = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cumulative)
    drawdowns = (peak - cumulative) / peak
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    total_return = float(cumulative[-1] - 1) if len(cumulative) > 0 else 0.0

    return {
        "strategy_id": strategy_id,
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "max_drawdown": round(max_dd, 4),
        "total_return": round(total_return, 4),
    }


def generate_portfolio_report(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
    output_path: str = "results/portfolio_report.html",
) -> None:
    """生成组合绩效 HTML 报告。"""
    try:
        import quantstats as qs

        # 构造加权组合收益序列
        min_len = min(len(r) for r in strategy_returns.values()) if strategy_returns else 0
        if min_len == 0:
            logger.warning("No return data, skipping report")
            return

        portfolio_returns = np.zeros(min_len)
        for strategy_id, returns in strategy_returns.items():
            w = weights.get(strategy_id, 0.0)
            portfolio_returns += np.array(returns[:min_len]) * w

        # 生成日期索引
        dates = pd.date_range(end=pd.Timestamp.now(), periods=min_len, freq="D")
        series = pd.Series(portfolio_returns, index=dates, name="Portfolio")

        qs.reports.html(series, output=output_path, title="Coin Quant Portfolio")
        logger.info(f"[绩效] 报告已生成: {output_path}")

    except ImportError:
        logger.warning("quantstats not installed, generating basic report")
        _generate_basic_report(strategy_returns, weights, output_path)
    except Exception:
        logger.warning("QuantStats report failed, generating basic report", exc_info=True)
        _generate_basic_report(strategy_returns, weights, output_path)


def _generate_basic_report(
    strategy_returns: dict[str, list[float]],
    weights: dict[str, float],
    output_path: str,
) -> None:
    """降级版：纯文本 HTML 报告。"""
    lines = ["<html><body><h1>Portfolio Report</h1>"]
    for sid, returns in strategy_returns.items():
        stats = compute_strategy_stats(sid, returns)
        w = weights.get(sid, 0.0)
        lines.append(f"<h2>{sid} (weight: {w:.1%})</h2>")
        lines.append(f"<p>Sharpe: {stats['sharpe']}, Win Rate: {stats['win_rate']:.1%}, "
                     f"Max DD: {stats['max_drawdown']:.1%}, Return: {stats['total_return']:.1%}</p>")
    lines.append("</body></html>")

    with open(output_path, "w") as f:
        f.write("\n".join(lines))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_portfolio_tracker.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add portfolio/tracker.py tests/test_portfolio_tracker.py requirements.txt
git commit -m "feat(portfolio): add QuantStats performance tracker and report"
```

---

## Phase 3: 集成

### Task 13: config.yaml 扩展 + load_config 更新

**Files:**
- Modify: `config.yaml`
- Modify: `main.py:64-116` (load_config 函数)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py
import os
import tempfile

import pytest
import yaml


class TestLoadConfig:
    def test_load_sentiment_config(self, tmp_path):
        cfg = {
            "proxy": {"https": ""},
            "scanner": {},
            "signal": {},
            "sentiment": {
                "enabled": True,
                "weights": {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2},
                "boost_range": 0.15,
            },
            "portfolio": {"enabled": True, "total_capital_pct": 0.8},
        }
        path = str(tmp_path / "config.yaml")
        with open(path, "w") as f:
            yaml.dump(cfg, f)

        from main import load_config

        scanner_cfg, signal_cfg, trading_cfg, schedule_cfg, sentiment_cfg, portfolio_cfg = load_config(path)
        assert sentiment_cfg["enabled"] is True
        assert sentiment_cfg["boost_range"] == 0.15
        assert portfolio_cfg["enabled"] is True

    def test_missing_sentiment_defaults(self, tmp_path):
        cfg = {"proxy": {"https": ""}, "scanner": {}, "signal": {}}
        path = str(tmp_path / "config.yaml")
        with open(path, "w") as f:
            yaml.dump(cfg, f)

        from main import load_config

        _, _, _, _, sentiment_cfg, portfolio_cfg = load_config(path)
        assert sentiment_cfg["enabled"] is False
        assert portfolio_cfg["enabled"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `load_config` returns 4-tuple, not 6

- [ ] **Step 3: Add sentiment/portfolio sections to config.yaml**

Append to `config.yaml`:

```yaml
sentiment:
  enabled: false
  weights:
    twitter: 0.3
    telegram: 0.2
    news: 0.3
    onchain: 0.2
  boost_range: 0.2
  vader_threshold: 0.5
  llm_enabled: false
  twitter:
    keywords: ["BTC", "ETH", "SOL"]
    kol_list: []
    interval_minutes: 30
  telegram:
    channels: []
    api_id_env: "TELEGRAM_API_ID"
    api_hash_env: "TELEGRAM_API_HASH"
  news:
    cryptopanic_api_key_env: "CRYPTOPANIC_API_KEY"
    interval_minutes: 15
  onchain:
    etherscan_api_key_env: "ETHERSCAN_API_KEY"
    min_transfer_usd: 1000000
    interval_minutes: 5

portfolio:
  enabled: false
  total_capital_pct: 0.8
  max_strategy_weight: 0.5
  min_strategy_weight: 0.05
  lookback_days: 90
  rebalance_interval: "weekly"
  rebalance_drift_threshold: 0.2
  risk:
    strategy_daily_loss_limit: 0.03
    portfolio_drawdown_limit: 0.05
```

- [ ] **Step 4: Update load_config in main.py to return 6 values**

In `main.py`, modify `load_config` to also parse and return sentiment and portfolio config dicts. Update the return type to a 6-tuple. Add default values for when sections are missing:

```python
def load_config(
    path: str = "config.yaml",
) -> tuple[dict, SignalConfig, TradingConfig, ScheduleConfig, dict, dict]:
    # ... existing code ...

    # sentiment config
    sentiment_cfg = dict(raw.get("sentiment", {}))
    if "enabled" not in sentiment_cfg:
        sentiment_cfg["enabled"] = False
    if "weights" not in sentiment_cfg:
        sentiment_cfg["weights"] = {"twitter": 0.3, "telegram": 0.2, "news": 0.3, "onchain": 0.2}
    if "boost_range" not in sentiment_cfg:
        sentiment_cfg["boost_range"] = 0.2

    # portfolio config
    portfolio_cfg = dict(raw.get("portfolio", {}))
    if "enabled" not in portfolio_cfg:
        portfolio_cfg["enabled"] = False

    return scanner_cfg, signal_config, trading_config, schedule_config, sentiment_cfg, portfolio_cfg
```

- [ ] **Step 5: Update all callers of load_config**

In `cli/__init__.py:88`, update the unpacking:

```python
config, signal_config, trading_config, schedule_config, sentiment_config, portfolio_config = load_config(args.config)
```

Update all other callers in `main.py` that call `load_config` (search for existing callers).

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: All PASS

- [ ] **Step 7: Run full test suite to check no regressions**

Run: `.venv/bin/pytest tests/ -v`
Expected: All existing tests still PASS

- [ ] **Step 8: Commit**

```bash
git add config.yaml main.py cli/__init__.py tests/test_config.py
git commit -m "feat: extend load_config with sentiment and portfolio config sections"
```

---

### Task 14: CLI 子命令扩展

**Files:**
- Modify: `cli/__init__.py`
- Modify: `main.py` (add entry functions)

- [ ] **Step 1: Add sentiment and portfolio subcommands to cli/__init__.py**

Add after the `retrain` subparser:

```python
    # ── sentiment ────────────────────────────────────────
    p_sent = sub.add_parser("sentiment", help="舆情分析")
    p_sent.add_argument(
        "action",
        nargs="?",
        default="scan",
        choices=["scan", "status"],
        help="scan=采集舆情, status=查看情绪 (默认: scan)",
    )
    p_sent.add_argument("--symbols", nargs="+", help="指定币种")

    # ── portfolio ────────────────────────────────────────
    p_port = sub.add_parser("portfolio", help="组合管理")
    p_port.add_argument(
        "action",
        nargs="?",
        default="status",
        choices=["status", "rebalance", "report"],
        help="status=查看权重, rebalance=再平衡, report=绩效报告 (默认: status)",
    )
```

- [ ] **Step 2: Add routing logic in cli/__init__.py**

Add after the `retrain` elif block:

```python
    elif args.command == "sentiment":
        if args.action == "status":
            run_sentiment_status()
        else:
            run_sentiment_scan(sentiment_config, symbols_override=getattr(args, "symbols", None))

    elif args.command == "portfolio":
        if args.action == "rebalance":
            run_portfolio_rebalance(portfolio_config)
        elif args.action == "report":
            run_portfolio_report(portfolio_config)
        else:
            run_portfolio_status(portfolio_config)
```

Update the imports block:

```python
    from main import (
        # ... existing imports ...
        run_sentiment_scan,
        run_sentiment_status,
        run_portfolio_status,
        run_portfolio_rebalance,
        run_portfolio_report,
    )
```

- [ ] **Step 3: Add stub entry functions in main.py**

```python
def run_sentiment_scan(sentiment_config: dict, symbols_override: list[str] | None = None):
    """手动触发舆情采集。"""
    from sentiment.aggregator import aggregate, compute_boost
    from sentiment.analyzer import analyze_text, analyze_onchain
    from sentiment.store import save_items, save_signal
    from sentiment.sources.news import CryptoPanicSource, RSSSource

    if not sentiment_config.get("enabled"):
        print("[舆情] 未启用，请在 config.yaml 中设置 sentiment.enabled: true")
        return

    weights = sentiment_config.get("weights", {})
    all_items = []

    # 新闻采集
    news_cfg = sentiment_config.get("news", {})
    api_key = os.environ.get(news_cfg.get("cryptopanic_api_key_env", ""), "")
    if api_key:
        source = CryptoPanicSource(api_key=api_key)
        all_items.extend(source.fetch(symbols=symbols_override))
    rss = RSSSource()
    all_items.extend(rss.fetch())

    # NLP 分析
    analyzed = []
    for item in all_items:
        if item.source == "onchain":
            analyzed.append(analyze_onchain(item))
        else:
            score = analyze_text(item.raw_text)
            from dataclasses import replace
            analyzed.append(replace(item, score=score))

    if analyzed:
        save_items(analyzed)

    # 融合
    signals = aggregate(analyzed, weights)
    for sig in signals:
        save_signal(sig)
        boost = compute_boost(sig, sentiment_config.get("boost_range", 0.2))
        print(f"  {sig.symbol or '全局':12s}  情绪={sig.score:+.3f}  {sig.direction:8s}  boost={boost:+.4f}")

    print(f"\n[舆情] 采集完成，共 {len(analyzed)} 条数据 → {len(signals)} 个信号")


def run_sentiment_status():
    """查看当前情绪指标。"""
    from sentiment.store import query_latest_signal
    from tabulate import tabulate

    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", ""]
    rows = []
    for symbol in symbols:
        sig = query_latest_signal(symbol)
        if sig:
            rows.append([
                sig.get("symbol") or "全局",
                f"{sig['score']:+.3f}",
                sig["direction"],
                f"{sig['confidence']:.2f}",
                sig["created_at"],
            ])
    if rows:
        print(tabulate(rows, headers=["币种", "情绪分", "方向", "置信度", "更新时间"]))
    else:
        print("[舆情] 暂无数据，请先运行: coin sentiment scan")


def run_portfolio_status(portfolio_config: dict):
    """查看当前各策略权重。"""
    from portfolio.store import query_latest_weights, query_nav_history
    from tabulate import tabulate

    weights = query_latest_weights()
    if not weights:
        print("[组合] 暂无权重数据，请先运行: coin portfolio rebalance")
        return

    rows = [[sid, f"{w:.1%}"] for sid, w in sorted(weights.items())]
    print(tabulate(rows, headers=["策略", "权重"]))

    nav_history = query_nav_history(limit=1)
    if nav_history:
        latest = nav_history[0]
        print(f"\n净值: {latest['nav']:.2f}  高水位: {latest['high_water_mark']:.2f}")


def run_portfolio_rebalance(portfolio_config: dict):
    """手动触发再平衡。"""
    from datetime import date
    from portfolio.allocator import optimize_weights
    from portfolio.models import StrategyResult
    from portfolio.store import save_weights, query_latest_weights
    from scanner.tracker import get_closed_trades

    if not portfolio_config.get("enabled"):
        print("[组合] 未启用，请在 config.yaml 中设置 portfolio.enabled: true")
        return

    # 从历史交易计算各策略绩效
    trades = get_closed_trades()
    strategy_returns: dict[str, list[float]] = {}
    for t in trades:
        mode = t.get("mode", "unknown")
        strategy_returns.setdefault(mode, []).append(t.get("pnl_pct", 0.0))

    if not strategy_returns:
        print("[组合] 没有足够的交易数据来优化权重")
        return

    strategies = []
    for sid, returns in strategy_returns.items():
        from portfolio.tracker import compute_strategy_stats
        stats = compute_strategy_stats(sid, returns)
        strategies.append(StrategyResult(
            strategy_id=sid,
            sharpe=stats["sharpe"],
            win_rate=stats["win_rate"],
            max_drawdown=stats["max_drawdown"],
            daily_returns=returns,
        ))

    weights = optimize_weights(
        strategies,
        max_weight=portfolio_config.get("max_strategy_weight", 0.5),
        min_weight=portfolio_config.get("min_strategy_weight", 0.05),
    )

    save_weights(date.today(), weights)
    print("[组合] 再平衡完成:")
    for sid, w in sorted(weights.items()):
        print(f"  {sid:20s}  {w:.1%}")


def run_portfolio_report(portfolio_config: dict):
    """生成组合绩效报告。"""
    from portfolio.tracker import generate_portfolio_report
    from portfolio.store import query_latest_weights
    from scanner.tracker import get_closed_trades

    trades = get_closed_trades()
    strategy_returns: dict[str, list[float]] = {}
    for t in trades:
        mode = t.get("mode", "unknown")
        strategy_returns.setdefault(mode, []).append(t.get("pnl_pct", 0.0))

    weights = query_latest_weights()
    if not weights:
        weights = {sid: 1.0 / len(strategy_returns) for sid in strategy_returns}

    output = "results/portfolio_report.html"
    generate_portfolio_report(strategy_returns, weights, output)
    print(f"[组合] 报告已生成: {output}")
```

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add cli/__init__.py main.py
git commit -m "feat: add sentiment/portfolio CLI subcommands and entry functions"
```

---

### Task 15: serve 模式扩展定时任务

**Files:**
- Modify: `main.py` (run_serve 函数)

- [ ] **Step 1: Locate run_serve in main.py and add sentiment/portfolio scheduled jobs**

Find the existing `run_serve` function and add new scheduled jobs:

```python
# 在 run_serve 的 scheduler 初始化部分，添加：

    # 舆情定时采集（每 15 分钟）
    if sentiment_config.get("enabled"):
        interval = sentiment_config.get("news", {}).get("interval_minutes", 15)
        scheduler.add_job(
            run_sentiment_scan,
            "interval",
            minutes=interval,
            args=[sentiment_config],
            id="sentiment_scan",
        )
        print(f"[调度] 舆情采集已启用，每 {interval} 分钟")

    # 组合周度再平衡（每周一 08:00）
    if portfolio_config.get("enabled"):
        scheduler.add_job(
            run_portfolio_rebalance,
            "cron",
            day_of_week="mon",
            hour=8,
            minute=0,
            args=[portfolio_config],
            id="portfolio_rebalance",
        )
        print("[调度] 组合再平衡已启用，每周一 08:00")
```

- [ ] **Step 2: Update run_serve signature to accept new configs**

```python
def run_serve(config, signal_config, trading_config, schedule_config, sentiment_config=None, portfolio_config=None):
```

Update the caller in `cli/__init__.py`:

```python
    elif args.command == "serve":
        run_serve(config, signal_config, trading_config, schedule_config, sentiment_config, portfolio_config)
```

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add main.py cli/__init__.py
git commit -m "feat: add sentiment/portfolio scheduled jobs to serve mode"
```

---

### Task 16: 舆情信号注入扫描评分

**Files:**
- Modify: `main.py` (run_divergence, run, run_breakout 函数)
- Test: `tests/test_sentiment_integration.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/test_sentiment_integration.py
import os

import pytest

from sentiment.models import SentimentSignal
from sentiment.aggregator import compute_boost


class TestSentimentBoostIntegration:
    def test_boost_adjusts_score(self):
        """验证 sentiment boost 正确调整 scanner score。"""
        scanner_score = 0.75
        signal = SentimentSignal(
            symbol="BTC/USDT", score=0.8, direction="bullish", confidence=0.9,
        )
        boost = compute_boost(signal, boost_range=0.2)
        adjusted = scanner_score * (1 + boost)

        assert adjusted > scanner_score  # 看多情绪 → 分数提高
        assert adjusted <= scanner_score * 1.2  # 不超过 +20%

    def test_boost_zero_when_no_signal(self):
        """无舆情数据时 boost=0。"""
        scanner_score = 0.75
        boost = 0.0  # 降级
        adjusted = scanner_score * (1 + boost)
        assert adjusted == scanner_score

    def test_bearish_reduces_score(self):
        """看空情绪降低分数。"""
        scanner_score = 0.75
        signal = SentimentSignal(
            symbol="BTC/USDT", score=-0.6, direction="bearish", confidence=0.8,
        )
        boost = compute_boost(signal, boost_range=0.2)
        adjusted = scanner_score * (1 + boost)

        assert adjusted < scanner_score
```

- [ ] **Step 2: Run test to verify it passes** (this should already pass since compute_boost is implemented)

Run: `.venv/bin/pytest tests/test_sentiment_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Integrate boost into scan functions in main.py**

In the `run_divergence`, `run`, and `run_breakout` functions, after signals are generated and before `save_scan`, add:

```python
    # 舆情信号加权（如果启用）
    sentiment_config = config.get("_sentiment_config", {})
    if sentiment_config.get("enabled"):
        from sentiment.store import query_latest_signal
        from sentiment.aggregator import compute_boost
        from sentiment.models import SentimentSignal
        from dataclasses import replace as dc_replace

        boost_range = sentiment_config.get("boost_range", 0.2)
        boosted_signals = []
        for sig in signals:
            latest = query_latest_signal(sig.symbol)
            if latest:
                sent_signal = SentimentSignal(
                    symbol=latest["symbol"], score=latest["score"],
                    direction=latest["direction"], confidence=latest["confidence"],
                )
                boost = compute_boost(sent_signal, boost_range)
                new_score = max(0.0, min(1.0, sig.score * (1 + boost)))
                boosted_signals.append(dc_replace(sig, score=new_score))
            else:
                boosted_signals.append(sig)
        signals = boosted_signals
```

- [ ] **Step 4: Pass sentiment_config through config dict**

In `load_config`, add `sentiment_cfg` into the scanner config dict for easy access:

```python
    scanner_cfg["_sentiment_config"] = sentiment_cfg
```

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_sentiment_integration.py
git commit -m "feat: integrate sentiment boost into scan signal scoring"
```

---

### Task 17: 更新 CLAUDE.md + 最终验证

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update CLAUDE.md with new commands and architecture**

Add to the Commands section:

```markdown
# Sentiment
.venv/bin/python main.py sentiment scan            # 手动采集舆情
.venv/bin/python main.py sentiment status           # 查看情绪指标

# Portfolio
.venv/bin/python main.py portfolio status           # 查看策略权重
.venv/bin/python main.py portfolio rebalance        # 手动再平衡
.venv/bin/python main.py portfolio report           # 生成绩效报告
```

Add to the Architecture section:

```markdown
**sentiment/ module responsibilities:**
- `models.py` — SentimentItem, SentimentSignal dataclasses
- `store.py` — SQLite persistence for sentiment data
- `sources/twitter.py` — Twitter/X scraping via snscrape
- `sources/telegram.py` — Telegram channel monitoring via Telethon
- `sources/news.py` — CryptoPanic API + RSS aggregation
- `sources/onchain.py` — Etherscan whale tracking
- `analyzer.py` — VADER + crypto lexicon + onchain rule engine
- `aggregator.py` — Multi-source fusion → SentimentSignal

**portfolio/ module responsibilities:**
- `models.py` — StrategyResult, PortfolioState dataclasses
- `store.py` — SQLite for NAV, weights, risk events
- `allocator.py` — Riskfolio-Lib CVaR weight optimization
- `risk.py` — Three-layer risk control (position/strategy/portfolio)
- `rebalancer.py` — Drift detection + adjustment calculation
- `tracker.py` — QuantStats performance reports
```

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with sentiment and portfolio modules"
```

- [ ] **Step 4: Verify all new commands work** (smoke test)

```bash
.venv/bin/python main.py sentiment status
.venv/bin/python main.py portfolio status
```

Expected: Both run without errors (may print "暂无数据" messages)
