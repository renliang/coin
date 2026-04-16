"""测试 /api/sentiment/* JSON 端点。"""

import os
from datetime import datetime

import pytest

from sentiment.models import SentimentItem, SentimentSignal
from sentiment.store import save_items, save_signal


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db = str(tmp_path / "test.db")
    monkeypatch.setenv("COIN_DB_PATH", db)
    from history_ui.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, db


def _make_signal(symbol: str, score: float = 0.6, direction: str = "bullish") -> SentimentSignal:
    return SentimentSignal(symbol=symbol, score=score, direction=direction, confidence=0.8)


def _make_item(
    symbol: str = "BTC/USDT",
    source: str = "twitter",
    score: float = 0.5,
) -> SentimentItem:
    return SentimentItem(
        source=source,
        symbol=symbol,
        score=score,
        confidence=0.8,
        raw_text=f"sample text {symbol}",
        timestamp=datetime(2024, 1, 10, 12, 0, 0),
    )


class TestSentimentLatest:
    def test_returns_200_empty(self, client):
        c, _ = client
        resp = c.get("/api/sentiment/latest")
        assert resp.status_code == 200

    def test_response_has_signals_key(self, client):
        c, _ = client
        data = c.get("/api/sentiment/latest").get_json()
        assert "signals" in data

    def test_empty_db_returns_empty_list(self, client):
        c, _ = client
        data = c.get("/api/sentiment/latest").get_json()
        assert data["signals"] == []

    def test_returns_latest_per_symbol(self, client):
        c, db = client
        save_signal(_make_signal("BTC/USDT", score=0.3, direction="neutral"), db_path=db)
        save_signal(_make_signal("BTC/USDT", score=0.8, direction="bullish"), db_path=db)
        save_signal(_make_signal("ETH/USDT", score=-0.5, direction="bearish"), db_path=db)

        data = c.get("/api/sentiment/latest").get_json()
        signals = data["signals"]
        # Should return exactly one entry per symbol (2 symbols)
        symbols = [s["symbol"] for s in signals]
        assert len(symbols) == 2
        assert "BTC/USDT" in symbols
        assert "ETH/USDT" in symbols

    def test_btc_signal_is_most_recent(self, client):
        c, db = client
        save_signal(_make_signal("BTC/USDT", score=0.3, direction="neutral"), db_path=db)
        save_signal(_make_signal("BTC/USDT", score=0.8, direction="bullish"), db_path=db)

        data = c.get("/api/sentiment/latest").get_json()
        btc = next(s for s in data["signals"] if s["symbol"] == "BTC/USDT")
        assert btc["direction"] == "bullish"
        assert btc["score"] == pytest.approx(0.8)

    def test_signal_has_expected_fields(self, client):
        c, db = client
        save_signal(_make_signal("BTC/USDT"), db_path=db)
        data = c.get("/api/sentiment/latest").get_json()
        sig = data["signals"][0]
        for field in ("id", "symbol", "score", "direction", "confidence", "created_at"):
            assert field in sig


class TestSentimentHistory:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/sentiment/history")
        assert resp.status_code == 200

    def test_response_has_history_key(self, client):
        c, _ = client
        data = c.get("/api/sentiment/history").get_json()
        assert "history" in data

    def test_empty_db_returns_empty_list(self, client):
        c, _ = client
        data = c.get("/api/sentiment/history").get_json()
        assert data["history"] == []

    def test_history_entry_has_expected_fields(self, client, monkeypatch):
        c, db = client
        # Insert a signal with created_at within the query window
        from sentiment.store import _get_conn
        conn = _get_conn(db)
        conn.execute(
            "INSERT INTO sentiment_signals (symbol, score, direction, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("BTC/USDT", 0.6, "bullish", 0.8, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

        data = c.get("/api/sentiment/history?symbol=BTC/USDT&days=7").get_json()
        assert len(data["history"]) >= 1
        entry = data["history"][0]
        for field in ("date", "score", "direction"):
            assert field in entry

    def test_symbol_filter(self, client):
        c, db = client
        from sentiment.store import _get_conn
        conn = _get_conn(db)
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO sentiment_signals (symbol, score, direction, confidence, created_at) VALUES (?,?,?,?,?)",
            ("BTC/USDT", 0.6, "bullish", 0.8, now),
        )
        conn.execute(
            "INSERT INTO sentiment_signals (symbol, score, direction, confidence, created_at) VALUES (?,?,?,?,?)",
            ("ETH/USDT", -0.5, "bearish", 0.7, now),
        )
        conn.commit()
        conn.close()

        data = c.get("/api/sentiment/history?symbol=BTC/USDT&days=7").get_json()
        # All returned entries should be aggregated — since we filtered by BTC we should only get BTC data
        # (direction derived from BTC score 0.6 -> bullish)
        assert len(data["history"]) == 1
        assert data["history"][0]["direction"] == "bullish"

    def test_days_parameter_defaults_to_7(self, client):
        c, _ = client
        resp = c.get("/api/sentiment/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "history" in data


class TestSentimentItems:
    def test_returns_200(self, client):
        c, _ = client
        resp = c.get("/api/sentiment/items")
        assert resp.status_code == 200

    def test_response_shape(self, client):
        c, _ = client
        data = c.get("/api/sentiment/items").get_json()
        for field in ("items", "total", "page", "per_page"):
            assert field in data

    def test_empty_db(self, client):
        c, _ = client
        data = c.get("/api/sentiment/items").get_json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_pagination_defaults(self, client):
        c, _ = client
        data = c.get("/api/sentiment/items").get_json()
        assert data["page"] == 1
        assert data["per_page"] == 20

    def test_custom_pagination(self, client):
        c, db = client
        items = [_make_item("BTC/USDT") for _ in range(5)]
        save_items(items, db_path=db)

        data = c.get("/api/sentiment/items?page=1&per_page=3").get_json()
        assert len(data["items"]) == 3
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["per_page"] == 3

    def test_source_filter(self, client):
        c, db = client
        save_items([
            _make_item("BTC/USDT", source="twitter"),
            _make_item("BTC/USDT", source="telegram"),
        ], db_path=db)

        data = c.get("/api/sentiment/items?source=twitter").get_json()
        assert data["total"] == 1
        assert data["items"][0]["source"] == "twitter"

    def test_symbol_filter(self, client):
        c, db = client
        save_items([
            _make_item("BTC/USDT"),
            _make_item("ETH/USDT"),
        ], db_path=db)

        data = c.get("/api/sentiment/items?symbol=ETH/USDT").get_json()
        assert data["total"] == 1
        assert data["items"][0]["symbol"] == "ETH/USDT"

    def test_combined_source_and_symbol_filter(self, client):
        c, db = client
        save_items([
            _make_item("BTC/USDT", source="twitter"),
            _make_item("BTC/USDT", source="telegram"),
            _make_item("ETH/USDT", source="twitter"),
        ], db_path=db)

        data = c.get("/api/sentiment/items?source=twitter&symbol=BTC/USDT").get_json()
        assert data["total"] == 1

    def test_item_fields(self, client):
        c, db = client
        save_items([_make_item("BTC/USDT")], db_path=db)
        data = c.get("/api/sentiment/items").get_json()
        item = data["items"][0]
        for field in ("id", "source", "symbol", "score", "confidence", "raw_text", "timestamp"):
            assert field in item

    def test_page_2_returns_correct_slice(self, client):
        c, db = client
        items = [_make_item("BTC/USDT", score=float(i) / 10) for i in range(5)]
        save_items(items, db_path=db)

        data = c.get("/api/sentiment/items?page=2&per_page=3").get_json()
        assert len(data["items"]) == 2  # 5 - 3 = 2 on page 2
        assert data["page"] == 2
