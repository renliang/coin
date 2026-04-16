"""Tests for sentiment SQLite store."""
import os
from datetime import datetime

import pytest

from sentiment.models import SentimentItem, SentimentSignal
from sentiment.store import query_items, query_latest_signal, save_items, save_signal


def _make_item(symbol: str = "BTC/USDT", source: str = "twitter", score: float = 0.5) -> SentimentItem:
    return SentimentItem(
        source=source,
        symbol=symbol,
        score=score,
        confidence=0.8,
        raw_text=f"{symbol} sentiment from {source}",
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )


def _make_signal(symbol: str = "BTC/USDT", score: float = 0.6, direction: str = "bullish") -> SentimentSignal:
    return SentimentSignal(
        symbol=symbol,
        score=score,
        direction=direction,
        confidence=0.85,
    )


class TestSaveAndQueryItems:
    def test_save_and_query_by_symbol(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        items = [_make_item("BTC/USDT"), _make_item("ETH/USDT")]
        save_items(items, db_path=db)

        results = query_items(symbol="BTC/USDT", db_path=db)
        assert len(results) == 1
        assert results[0].symbol == "BTC/USDT"
        assert results[0].source == "twitter"

    def test_query_by_source(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        items = [
            _make_item("BTC/USDT", source="twitter"),
            _make_item("BTC/USDT", source="telegram"),
        ]
        save_items(items, db_path=db)

        results = query_items(symbol="BTC/USDT", source="twitter", db_path=db)
        assert len(results) == 1
        assert results[0].source == "twitter"

    def test_query_no_filter_returns_all(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        items = [_make_item("BTC/USDT"), _make_item("ETH/USDT"), _make_item("SOL/USDT")]
        save_items(items, db_path=db)

        results = query_items(db_path=db)
        assert len(results) == 3

    def test_query_limit(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        items = [_make_item("BTC/USDT", score=float(i) / 10 - 0.5) for i in range(10)]
        save_items(items, db_path=db)

        results = query_items(symbol="BTC/USDT", limit=3, db_path=db)
        assert len(results) == 3

    def test_save_empty_list(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        save_items([], db_path=db)
        results = query_items(db_path=db)
        assert results == []

    def test_returned_items_are_sentiment_items(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        item = _make_item("BTC/USDT", score=0.3)
        save_items([item], db_path=db)

        results = query_items(symbol="BTC/USDT", db_path=db)
        assert isinstance(results[0], SentimentItem)
        assert results[0].score == pytest.approx(0.3)
        assert results[0].confidence == pytest.approx(0.8)


class TestSaveAndQuerySignal:
    def test_save_and_query_latest(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        signal = _make_signal("BTC/USDT", score=0.7, direction="bullish")
        save_signal(signal, db_path=db)

        result = query_latest_signal("BTC/USDT", db_path=db)
        assert result is not None
        assert result.symbol == "BTC/USDT"
        assert result.direction == "bullish"
        assert result.score == pytest.approx(0.7)

    def test_query_latest_returns_most_recent(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        save_signal(_make_signal("BTC/USDT", score=0.3, direction="neutral"), db_path=db)
        save_signal(_make_signal("BTC/USDT", score=0.8, direction="bullish"), db_path=db)

        result = query_latest_signal("BTC/USDT", db_path=db)
        assert result is not None
        assert result.score == pytest.approx(0.8)
        assert result.direction == "bullish"

    def test_query_nonexistent_symbol_returns_none(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        result = query_latest_signal("NONEXISTENT/USDT", db_path=db)
        assert result is None

    def test_query_signal_isolation_by_symbol(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        save_signal(_make_signal("BTC/USDT", score=0.7, direction="bullish"), db_path=db)
        save_signal(_make_signal("ETH/USDT", score=-0.5, direction="bearish"), db_path=db)

        btc = query_latest_signal("BTC/USDT", db_path=db)
        eth = query_latest_signal("ETH/USDT", db_path=db)

        assert btc is not None and btc.direction == "bullish"
        assert eth is not None and eth.direction == "bearish"

    def test_returned_signal_is_sentiment_signal(self, tmp_path, monkeypatch):
        db = str(tmp_path / "test.db")
        monkeypatch.setenv("COIN_DB_PATH", db)

        save_signal(_make_signal("BTC/USDT"), db_path=db)
        result = query_latest_signal("BTC/USDT", db_path=db)
        assert isinstance(result, SentimentSignal)
